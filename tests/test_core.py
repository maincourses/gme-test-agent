from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys
import subprocess


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from gme_agent.codex.runner import CodexRunner
from gme_agent.git.diff import commit_paths, create_pr, ensure_only_target_repo_changed, git_diff
from gme_agent.git.repositories import (
    module_scoped_submodule_paths,
    prepare_worktree_dependencies,
    submodule_base_branch,
)
from gme_agent.git.worktree import normalize_repo_path
from gme_agent.execution.runner import merge_failures, parse_gtest_failures, parse_gtest_xml
from gme_agent.flows.skip_pr_flow import (
    _failure_suite_filter,
    _format_generated_tests,
    _prune_manifest_tests_to_failures,
    _prune_generated_test_text,
    _restore_generated_tests,
    _skip_pr_branch_name,
    _skip_pr_body,
    _skip_pr_title,
    _snapshot_generated_tests,
)
from gme_agent.flows.generated_test_edit_flow import delete_generated_tests
from gme_agent.generated_tests import (
    ensure_generated_tests_use_existing_files,
    load_generated_tests_manifest,
    require_generated_tests_manifest,
)
from gme_agent.services.orchestrator import Orchestrator
from gme_agent.api.server import _match_job_action
from gme_agent.prompts import (
    continue_test_generation_prompt,
    skip_known_failure_prompt,
    test_generation_prompt,
)
from gme_agent.settings.config import AgentConfig, load_config, save_config
from gme_agent.settings.options import load_config_options
from gme_agent.settings.validation import validate_config
from gme_agent.storage.db import AgentDb


class CoreTests(unittest.TestCase):
    def _init_repo(self, path: Path, file_name: str, content: str = "content\n") -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        subprocess.run(["git", "config", "user.email", "agent@example.invalid"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "GME Agent"], cwd=path, check=True)
        (path / file_name).parent.mkdir(parents=True, exist_ok=True)
        (path / file_name).write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True)

    def _clone_repo(self, remote: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", str(remote), str(target)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        subprocess.run(["git", "config", "user.email", "agent@example.invalid"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "GME Agent"], cwd=target, check=True)

    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg = AgentConfig(gme_repo_path="D:/GME", model="gpt-5.5")
            save_config(path, cfg)
            loaded = load_config(path)
            self.assertEqual(Path(loaded.gme_repo_path), Path("D:/GME"))
            self.assertEqual(loaded.model, "gpt-5.5")
            self.assertTrue(loaded.codex_enabled)
            self.assertFalse(loaded.auto_apply_skips)
            self.assertTrue(loaded.use_builtin_skills)
            self.assertEqual(loaded.test_generation_skill, "gme-test-generation")
            self.assertEqual(loaded.bug_fix_skill, "gme-bug-fix")

    def test_db_job_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDb(Path(tmp) / "agent.db")
            try:
                job = db.create_job(job_id="job-1", job_type="test_generation", title="Generate tests")
                db.add_event(job["id"], "info", "hello")
                self.assertEqual(db.get_job("job-1")["status"], "queued")
                self.assertEqual(db.list_events("job-1")[0]["message"], "hello")
            finally:
                db.close()

    def test_db_delete_job_removes_related_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDb(Path(tmp) / "agent.db")
            try:
                job = db.create_job(job_id="job-1", job_type="test_generation", title="Generate tests")
                db.add_event(job["id"], "info", "hello")
                db.create_failure(failure_id="failure-1", job_id=job["id"], test_suite="Suite", test_name="Case")

                deleted = db.delete_job(job["id"])

                self.assertEqual(deleted["jobs"], 1)
                self.assertEqual(deleted["events"], 1)
                self.assertEqual(deleted["failures"], 1)
                with self.assertRaises(KeyError):
                    db.get_job(job["id"])
                self.assertEqual(db.list_events(job["id"]), [])
                self.assertEqual(db.list_failures(), [])
            finally:
                db.close()

    def test_db_delete_open_failures_for_job_preserves_closed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDb(Path(tmp) / "agent.db")
            try:
                job = db.create_job(job_id="job-1", job_type="test_generation", title="Generate tests")
                db.create_failure(failure_id="open-1", job_id=job["id"], test_suite="Suite", test_name="Open")
                db.create_failure(failure_id="fixed-1", job_id=job["id"], test_suite="Suite", test_name="Fixed")
                db.update_failure("fixed-1", status="fixed")

                deleted = db.delete_open_failures_for_job(job["id"])

                self.assertEqual(deleted, 1)
                self.assertEqual([failure["id"] for failure in db.list_failures()], ["fixed-1"])
            finally:
                db.close()

    def test_job_action_route_does_not_match_nested_delete_paths(self) -> None:
        self.assertEqual(_match_job_action("/api/jobs/job-1/delete", "delete"), "job-1")
        self.assertEqual(_match_job_action("/api/jobs/job-1/generated-tests/delete", "delete"), "")
        self.assertEqual(_match_job_action("/api/jobs/job-1/generated-tests/remove", "generated-tests", "remove"), "job-1")

    def test_delete_generated_tests_updates_files_manifest_metadata_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "worktree"
            target = worktree / "tests" / "gme"
            test_rel = "src/laws/generated_test.cpp"
            self._init_repo(
                target,
                test_rel,
                """#include "gtest/gtest.h"

TEST_F(Suite, ManualCase) {
    EXPECT_TRUE(true);
}

/**
 * generated case A
 */
TEST_F(Suite, GeneratedA) {
    EXPECT_TRUE(true);
}

TEST_F(Suite, GeneratedB) {
    EXPECT_TRUE(false);
}
""",
            )
            notes = worktree / ".gme-agent"
            notes.mkdir(parents=True)
            (notes / "generated_tests.json").write_text(
                """
{
  "tests": [
    {"file": "src/laws/generated_test.cpp", "suite": "Suite", "name": "GeneratedA", "api": "api_a"},
    {"file": "src/laws/generated_test.cpp", "suite": "Suite", "name": "GeneratedB", "api": "api_b"}
  ]
}
""",
                encoding="utf-8",
            )
            cfg = AgentConfig(
                artifact_root=str(root / "artifacts"),
                database_path=str(root / "agent.db"),
                test_target_repo="tests/gme",
            )
            db = AgentDb(cfg.database_path)
            try:
                job = db.create_job(
                    job_id="job-1",
                    job_type="test_generation",
                    title="Generate laws tests",
                    module="laws",
                    metadata={"target_repo": "tests/gme"},
                )
                db.update_job(
                    job["id"],
                    worktree_path=str(worktree),
                    metadata={
                        "target_repo": "tests/gme",
                        "generated_tests": load_generated_tests_manifest(worktree, "tests/gme")["tests"],
                    },
                )
                db.create_failure(failure_id="failure-a", job_id=job["id"], test_suite="Suite", test_name="GeneratedA")
                db.create_failure(failure_id="failure-b", job_id=job["id"], test_suite="Suite", test_name="GeneratedB")
                orchestrator = Orchestrator(cfg, db)

                updated = delete_generated_tests(orchestrator, job["id"], [{"suite": "Suite", "name": "GeneratedA"}])

                content = (target / test_rel).read_text(encoding="utf-8")
                self.assertIn("TEST_F(Suite, ManualCase)", content)
                self.assertNotIn("GeneratedA", content)
                self.assertNotIn("generated case A", content)
                self.assertIn("TEST_F(Suite, GeneratedB)", content)
                manifest = load_generated_tests_manifest(worktree, "tests/gme")
                self.assertEqual([(test["suite"], test["name"]) for test in manifest["tests"]], [("Suite", "GeneratedB")])
                self.assertEqual(updated["metadata"]["generated_gtest_filter"], "Suite.GeneratedB")
                self.assertEqual([failure["id"] for failure in db.list_failures()], ["failure-b"])
                self.assertTrue((Path(cfg.artifact_root) / job["id"] / "diff.patch").exists())
            finally:
                db.close()

    def test_parse_gtest_failures(self) -> None:
        output = """
        D:/GME/tests/gme/src/laws/foo_test.cpp:42: Failure
        Expected equality of these values:
        [  FAILED  ] LawsFooTest.CompareCaseA (15 ms)
        [  FAILED  ] 1 test, listed below:
        [  FAILED  ] LawsFooTest.CompareCaseA
        """
        failures = parse_gtest_failures(output)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["test_suite"], "LawsFooTest")
        self.assertEqual(failures[0]["test_name"], "CompareCaseA")
        self.assertEqual(failures[0]["line"], 42)

    def test_parse_gtest_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gtest.xml"
            path.write_text(
                """<?xml version="1.0"?>
<testsuites>
  <testsuite name="Suite" tests="1" failures="1">
    <testcase classname="Suite" name="TestA" file="foo.cpp" line="12">
      <failure message="mismatch">details</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
                encoding="utf-8",
            )
            failures = parse_gtest_xml(path)
            self.assertEqual(failures[0]["test_suite"], "Suite")
            self.assertEqual(failures[0]["test_name"], "TestA")
            self.assertEqual(failures[0]["reason"], "mismatch")

    def test_merge_failures_deduplicates(self) -> None:
        first = [{"test_suite": "A", "test_name": "B", "file": "x.cpp", "line": 1}]
        second = [{"test_suite": "A", "test_name": "B", "file": "x.cpp", "line": 1}]
        self.assertEqual(len(merge_failures(first, second)), 1)

    def test_merge_failures_counts_failed_tests_not_assert_locations(self) -> None:
        xml = [{"test_suite": "A", "test_name": "B", "file": "x.cpp", "line": 10, "reason": "details"}]
        stdout = [{"test_suite": "A", "test_name": "B", "file": "", "line": 0, "reason": "GTest reported failure."}]

        failures = merge_failures(xml, stdout)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["file"], "x.cpp")
        self.assertEqual(failures[0]["line"], 10)

    def test_skip_prompt_uses_direct_gtest_skip(self) -> None:
        prompt = skip_known_failure_prompt(
            "test output",
            [{"id": "gmefail-1", "test_suite": "Suite", "test_name": "Case", "file": "x.cpp", "line": 12, "reason": "mismatch"}],
            "tests/gme",
            ["tests/gme/src/base/base_geometry_test.cpp"],
        )

        self.assertIn("GTEST_SKIP()", prompt)
        self.assertIn("[gme-agent-known-failure:<id>]", prompt)
        self.assertNotIn("GME_AGENT_KNOWN_FAILURE", prompt)
        self.assertNotIn("gme_agent_known_failure.hxx", prompt)

    def test_test_generation_prompt_uses_existing_files_manifest_and_no_helpers(self) -> None:
        prompt = test_generation_prompt("laws", "api_ndifferentiate_law", "tests/gme")

        self.assertIn(".gme-agent/generated_tests.json", prompt)
        self.assertIn("most relevant existing `.cpp`", prompt)
        self.assertIn("Do not create `gme_agent_<module>_generated_test.cpp`", prompt)
        self.assertIn("Do not add new helper functions", prompt)
        self.assertIn("directly inside each individual `TEST_F` body", prompt)
        self.assertIn("Write generated tests as `TEST_F` cases", prompt)
        self.assertIn("delete any temporary files outside", prompt)
        self.assertIn("timer_res_.csv", prompt)
        self.assertIn("build the test target", prompt)
        self.assertIn("Visual Studio 17 2022", prompt)
        self.assertIn("-DDEVELOP_LAWS=ON", prompt)
        self.assertIn("-DTEST_LAWS=ON", prompt)
        self.assertIn("cmake --build", prompt)
        self.assertIn("If the build fails because of tests you generated", prompt)
        self.assertIn("After every generated-test fix, deletion, or replacement, build again", prompt)
        self.assertIn("Repeat the build -> fix/delete/replace -> rebuild loop", prompt)
        self.assertIn("add a replacement buildable test and rebuild again", prompt)
        self.assertIn("any requested-count shortfall with reasons", prompt)
        self.assertIn("delete that test and update `.gme-agent/generated_tests.md`", prompt)
        self.assertIn("unresolved external/LNK2019", prompt)
        self.assertIn("private/protected member access errors", prompt)
        self.assertNotIn("Generated test suite", prompt)

    def test_continue_generation_prompt_uses_existing_files_manifest_and_no_helpers(self) -> None:
        prompt = continue_test_generation_prompt("base", "extend coverage", "tests/gme")

        self.assertIn(".gme-agent/generated_tests.json", prompt)
        self.assertIn("appropriate existing `.cpp` files", prompt)
        self.assertIn("Do not create `gme_agent_<module>_generated_test.cpp`", prompt)
        self.assertIn("Do not add new helper functions", prompt)
        self.assertIn("directly inside each individual `TEST_F` body", prompt)
        self.assertIn("Write generated tests as `TEST_F` cases", prompt)
        self.assertIn("delete any temporary files outside", prompt)
        self.assertIn("timer_res_.csv", prompt)
        self.assertIn("build the test target", prompt)
        self.assertIn("Visual Studio 17 2022", prompt)
        self.assertIn("-DDEVELOP_BASE=ON", prompt)
        self.assertIn("-DTEST_BASE=ON", prompt)
        self.assertIn("cmake --build", prompt)
        self.assertIn("If the build fails because of tests you generated", prompt)
        self.assertIn("After every generated-test fix, deletion, or replacement, build again", prompt)
        self.assertIn("Repeat the build -> fix/delete/replace -> rebuild loop", prompt)
        self.assertIn("add a replacement buildable test and rebuild again", prompt)
        self.assertIn("any requested-count shortfall with reasons", prompt)
        self.assertIn("delete that test and update `.gme-agent/generated_tests.md`", prompt)
        self.assertIn("unresolved external/LNK2019", prompt)
        self.assertIn("private/protected member access errors", prompt)
        self.assertNotIn("Generated test suite", prompt)

    def test_generation_prompt_uses_task_specific_build_guidance(self) -> None:
        prompt = test_generation_prompt(
            "laws",
            "api_ndifferentiate_law",
            "tests/gme",
            "Build validation commands from the GME Test Agent settings:\n- Build:\n  `custom-build-command`",
        )

        self.assertIn("custom-build-command", prompt)
        self.assertNotIn("-DDEVELOP_LAWS=ON", prompt)

    def test_generated_tests_manifest_normalizes_files_and_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            notes = worktree / ".gme-agent"
            notes.mkdir()
            (notes / "generated_tests.json").write_text(
                """
{
  "tests": [
    {
      "file": "tests/gme/src/laws/kernel_kernapi_test.cpp",
      "suite": "Laws_KernapiTest",
      "name": "ApiMakeCubicAsymmetricEndpointSlopes",
      "api": "api_make_cubic"
    },
    {
      "file": "src/laws/law_main_law_test.cpp",
      "suite": "Laws_ClassTest",
      "name": "LawZeroConstantPredicate"
    }
  ]
}
""",
                encoding="utf-8",
            )

            manifest = load_generated_tests_manifest(worktree, "tests/gme")

            self.assertEqual(
                manifest["files"],
                ["src/laws/kernel_kernapi_test.cpp", "src/laws/law_main_law_test.cpp"],
            )
            self.assertEqual(
                manifest["gtest_filter"],
                "Laws_KernapiTest.ApiMakeCubicAsymmetricEndpointSlopes:Laws_ClassTest.LawZeroConstantPredicate",
            )

    def test_generated_tests_manifest_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "generated_tests.json"):
                require_generated_tests_manifest(Path(tmp), "tests/gme")

    def test_generated_tests_manifest_requires_existing_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            repo = worktree / "tests" / "gme"
            self._init_repo(repo, "src/laws/existing_test.cpp", "TEST(Existing, Case) {}\n")
            new_file = repo / "src" / "laws" / "new_agent_test.cpp"
            new_file.write_text("TEST(New, Case) {}\n", encoding="utf-8")

            ensure_generated_tests_use_existing_files(worktree, "tests/gme", ["src/laws/existing_test.cpp"])
            with self.assertRaisesRegex(RuntimeError, "existing test files"):
                ensure_generated_tests_use_existing_files(worktree, "tests/gme", ["src/laws/new_agent_test.cpp"])

    def test_commit_paths_only_commits_selected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._init_repo(repo, "selected.cpp", "old selected\n")
            (repo / "other.cpp").write_text("old other\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "add other"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (repo / "selected.cpp").write_text("new selected\n", encoding="utf-8")
            (repo / "other.cpp").write_text("new other\n", encoding="utf-8")

            commit_paths(repo, ["selected.cpp"], "commit selected", lambda _level, _message: None)

            changed = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
            ).stdout.splitlines()
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=repo,
                check=True,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
            ).stdout
            self.assertEqual(changed, ["selected.cpp"])
            self.assertIn("other.cpp", status)

    def test_create_pr_creates_ready_pr(self) -> None:
        captured: dict[str, list[str]] = {}

        class Proc:
            stdout = "https://example.invalid/pull/1\n"
            returncode = 0

        def fake_run(cmd: list[str], **_kwargs: object) -> Proc:
            captured["cmd"] = cmd
            return Proc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("gme_agent.git.diff.shutil.which", return_value="gh"):
                with mock.patch("gme_agent.git.diff.subprocess.run", side_effect=fake_run):
                    url = create_pr(AgentConfig(base_branch="main"), tmp, "skip failures", "body", lambda _level, _message: None)

        self.assertEqual(url, "https://example.invalid/pull/1")
        self.assertNotIn("--draft", captured["cmd"])
        self.assertIn("--base", captured["cmd"])
        self.assertIn("main", captured["cmd"])

    def test_skip_pr_title_uses_module_feature_format(self) -> None:
        self.assertEqual(_skip_pr_title({"module": "base"}), "feature(base):gme agent test")
        self.assertEqual(_skip_pr_title({"module": " laws "}), "feature(laws):gme agent test")

    def test_skip_pr_branch_name_is_unique_skip_branch(self) -> None:
        first = _skip_pr_branch_name({"id": "06437831-a6a2", "module": "laws"})
        second = _skip_pr_branch_name({"id": "06437831-a6a2", "module": "laws"})

        self.assertRegex(first, r"^gme-agent/skip-laws-\d{8}-\d{6}-06437831-[0-9a-f]{6}$")
        self.assertNotEqual(first, second)

    def test_skip_pr_body_uses_chinese_plain_text(self) -> None:
        body = _skip_pr_body(
            {"id": "job-1", "module": "base"},
            [
                {"test_suite": "BaseGeometryTest", "test_name": "GetPlaneFromPointArrayMatchesAcis"},
                {"test_suite": "BaseGeometryTest", "test_name": "MaxDistanceToParBoxMatchesAcis"},
            ],
            "BaseGeometryTest.GetPlaneFromPointArrayMatchesAcis:BaseGeometryTest.MaxDistanceToParBoxMatchesAcis",
        )

        self.assertEqual(
            body,
            "\n".join(
                [
                    "该 PR 由 GME Test Agent 自动生成，新增 GME vs ACIS 对比测试，并对当前已确认存在差异的失败用例增加 skip。",
                    "",
                    "本次新增测试用例：",
                    "BaseGeometryTest.GetPlaneFromPointArrayMatchesAcis",
                    "BaseGeometryTest.MaxDistanceToParBoxMatchesAcis",
                ]
            ),
        )

    def test_failure_suite_filter_uses_exact_failed_tests(self) -> None:
        self.assertEqual(
            _failure_suite_filter(
                [
                    {"test_suite": "BaseGeometryTest", "test_name": "GetPlaneFromPointArrayMatchesAcis"},
                    {"test_suite": "BaseGeometryTest", "test_name": "MaxDistanceToParBoxMatchesAcis"},
                    {"test_suite": "BaseGeometryTest", "test_name": "GetPlaneFromPointArrayMatchesAcis"},
                ]
            ),
            "BaseGeometryTest.GetPlaneFromPointArrayMatchesAcis:BaseGeometryTest.MaxDistanceToParBoxMatchesAcis",
        )

    def test_prune_generated_test_text_keeps_only_skipped_failures(self) -> None:
        text = """#include "gtest/include/gtest.h"

namespace {
void Helper() {}
}

class Suite : public ::testing::Test {};

TEST_F(Suite, PassingCase) {
    Helper();
    EXPECT_TRUE(true);
}

TEST_F(Suite, FailingCase) {
    GTEST_SKIP() << "[gme-agent-known-failure:gmefail-1] mismatch";
    Helper();
    EXPECT_TRUE(false);
}
"""

        pruned = _prune_generated_test_text(text, {("Suite", "FailingCase")}, "generated.cpp")

        self.assertIn("void Helper()", pruned)
        self.assertIn("TEST_F(Suite, FailingCase)", pruned)
        self.assertIn("GTEST_SKIP()", pruned)
        self.assertNotIn("TEST_F(Suite, PassingCase)", pruned)

    def test_prune_generated_test_text_requires_skip_marker(self) -> None:
        text = """#include "gtest/include/gtest.h"

TEST_F(Suite, FailingCase) {
    EXPECT_TRUE(false);
}
"""

        with self.assertRaisesRegex(RuntimeError, "does not contain GTEST_SKIP"):
            _prune_generated_test_text(text, {("Suite", "FailingCase")}, "generated.cpp")

    def test_prune_manifest_tests_removes_only_generated_passing_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            rel_path = "src/laws/kernel_kernapi_test.cpp"
            file_path = target / rel_path
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """#include "gtest/include/gtest.h"

TEST_F(LawsKernapiTest, ExistingManualCase) {
    EXPECT_TRUE(true);
}

TEST_F(LawsKernapiTest, GeneratedPassingCase) {
    EXPECT_TRUE(true);
}

TEST_F(LawsKernapiTest, GeneratedFailingCase) {
    GTEST_SKIP() << "[gme-agent-known-failure:gmefail-1] ACIS/GME mismatch";
    EXPECT_TRUE(false);
}
""",
                encoding="utf-8",
            )

            _prune_manifest_tests_to_failures(
                target,
                [rel_path],
                [{"test_suite": "LawsKernapiTest", "test_name": "GeneratedFailingCase"}],
                [
                    {"file": rel_path, "suite": "LawsKernapiTest", "name": "GeneratedPassingCase"},
                    {"file": rel_path, "suite": "LawsKernapiTest", "name": "GeneratedFailingCase"},
                ],
                lambda _level, _message: None,
            )

            pruned = file_path.read_text(encoding="utf-8")
            self.assertIn("TEST_F(LawsKernapiTest, ExistingManualCase)", pruned)
            self.assertIn("TEST_F(LawsKernapiTest, GeneratedFailingCase)", pruned)
            self.assertIn("GTEST_SKIP()", pruned)
            self.assertNotIn("GeneratedPassingCase", pruned)

    def test_generated_test_snapshot_restore_keeps_local_full_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            rel_path = "src/base/gme_agent_base_generated_test.cpp"
            file_path = target / rel_path
            file_path.parent.mkdir(parents=True)
            file_path.write_text("full generated tests with skips\n", encoding="utf-8")

            snapshots = _snapshot_generated_tests(target, [rel_path])
            file_path.write_text("pruned PR version\n", encoding="utf-8")
            _restore_generated_tests(target, snapshots, lambda _level, _message: None)

            self.assertEqual(file_path.read_text(encoding="utf-8"), "full generated tests with skips\n")

    def test_format_generated_tests_uses_current_worktree_clang_format(self) -> None:
        captured: dict[str, object] = {}

        class Proc:
            stdout = ""
            returncode = 0

        def fake_run(cmd: list[str], **kwargs: object) -> Proc:
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return Proc()

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "worktree"
            target = Path(tmp) / "tests-gme"
            worktree.mkdir()
            target.mkdir()
            (worktree / ".clang-format").write_text("BasedOnStyle: Google\n", encoding="utf-8")

            with mock.patch("gme_agent.flows.skip_pr_flow.shutil.which", return_value="clang-format"):
                with mock.patch("gme_agent.flows.skip_pr_flow.subprocess.run", side_effect=fake_run):
                    _format_generated_tests(worktree, target, ["src/laws/test.cpp"], lambda _level, _message: None)

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertIn("-i", cmd)
        self.assertIn(f"--style=file:{worktree / '.clang-format'}", cmd)
        self.assertIn("src/laws/test.cpp", cmd)
        self.assertEqual(captured["cwd"], str(target))

    def test_command_mapping_reproduce_command_uses_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AgentConfig(
                database_path=str(Path(tmp) / "agent.db"),
                test_executable="{build_dir}/tests.exe",
                test_command="{test_executable} --gtest_filter={gtest_filter}",
            )
            db = AgentDb(cfg.database_path)
            try:
                orchestrator = Orchestrator(cfg, db)
                cmd = orchestrator._reproduce_command("Suite.Test")
                self.assertIn("--gtest_filter=Suite.Test", cmd)
                self.assertNotIn("FORCE_RUN_ALL", cmd)
            finally:
                db.close()

    def test_command_mapping_adds_selected_module_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AgentConfig(database_path=str(Path(tmp) / "agent.db"))
            db = AgentDb(cfg.database_path)
            try:
                db.create_job(job_id="job-laws", job_type="test_generation", title="Generate laws tests", module="laws")
                orchestrator = Orchestrator(cfg, db)
                mapping = orchestrator._command_mapping(
                    Path("D:/worktree"),
                    Path("D:/worktree/build/vscode"),
                    "*",
                    artifact_dir=Path(tmp) / "job-laws",
                )
                self.assertEqual(mapping["test_module_name"], "laws")
                self.assertEqual(mapping["develop_module_option"], "-DDEVELOP_LAWS=ON")
                self.assertEqual(mapping["test_module_option"], "-DTEST_LAWS=ON")
            finally:
                db.close()

    def test_load_config_drops_legacy_force_run_all_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                """{
  "configure_command": "cmake -S {worktree} -B {build_dir} -DFORCE_RUN_ALL={force_run_all}"
}
""",
                encoding="utf-8",
            )

            loaded = load_config(path)

            self.assertNotIn("FORCE_RUN_ALL", loaded.configure_command)
            self.assertNotIn("force_run_all", loaded.configure_command)
            self.assertNotIn("GME_FULL_MODE", loaded.configure_command)
            self.assertNotIn("GME_HUDONG_MODE", loaded.configure_command)

    def test_load_config_overrides_legacy_full_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                """{
  "configure_command": "cmake -S {worktree} -B {build_dir} -DGME_FULL_MODE=ON -DGME_HUDONG_MODE=ON {develop_module_option}"
}
""",
                encoding="utf-8",
            )

            loaded = load_config(path)

            self.assertNotIn("-DGME_FULL_MODE=ON", loaded.configure_command)
            self.assertNotIn("-DGME_HUDONG_MODE=ON", loaded.configure_command)
            self.assertNotIn("GME_FULL_MODE", loaded.configure_command)
            self.assertNotIn("GME_HUDONG_MODE", loaded.configure_command)

    def test_module_scoped_submodule_paths_keep_only_required_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitmodules").write_text(
                """
[submodule "tests/gme"]
    path = tests/gme
    url = https://example.invalid/tests.git
[submodule "_deps/acis"]
    path = _deps/acis
    url = https://example.invalid/acis.git
[submodule "tests/hudong"]
    path = tests/hudong
    url = https://example.invalid/tests-hudong.git
[submodule "tests/yunji"]
    path = tests/yunji
    url = https://example.invalid/tests-yunji.git
[submodule "tests/haizhou"]
    path = tests/haizhou
    url = https://example.invalid/tests-haizhou.git
[submodule "data/public"]
    path = data/public
    url = https://example.invalid/data-public.git
[submodule "data/gme"]
    path = data/gme
    url = https://example.invalid/data-gme.git
[submodule "module/laws"]
    path = module/laws
    url = https://example.invalid/laws.git
[submodule "module/base"]
    path = module/base
    url = https://example.invalid/base.git
""".lstrip(),
                encoding="utf-8",
            )

            paths = module_scoped_submodule_paths(AgentConfig(), root, "laws", "tests/gme")

            self.assertEqual(paths, ["tests/gme", "tests/hudong", "tests/yunji", "tests/haizhou", "module/laws", "_deps/acis"])

    def test_validate_config_reports_unknown_placeholder(self) -> None:
        cfg = AgentConfig(configure_command="cmake -S {unknown}")
        result = validate_config(cfg)
        placeholder_checks = [c for c in result["checks"] if c["name"] == "Template placeholders: configure_command"]
        self.assertEqual(len(placeholder_checks), 1)
        self.assertFalse(placeholder_checks[0]["ok"])

    def test_validate_config_reports_codex_sdk(self) -> None:
        cfg = AgentConfig()
        result = validate_config(cfg)
        sdk_checks = [c for c in result["checks"] if c["name"] == "Codex Python SDK"]
        self.assertEqual(len(sdk_checks), 1)
        self.assertTrue(sdk_checks[0]["ok"])

    def test_git_diff_includes_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            Path(tmp, "new_test.cpp").write_text("TEST(Suite, Case) {}\n", encoding="utf-8")

            diff = git_diff(tmp)

            self.assertIn("new file mode", diff)
            self.assertIn("new_test.cpp", diff)
            self.assertIn("+TEST(Suite, Case) {}", diff)

    def test_target_repo_path_selection(self) -> None:
        cfg = AgentConfig(test_target_repo="tests\\gme", module_repo_root="module")
        db = AgentDb(":memory:")
        try:
            orchestrator = Orchestrator(cfg, db)
            self.assertEqual(orchestrator._test_target_repo(), "tests/gme")
            self.assertEqual(orchestrator._module_target_repo("laws"), "module/laws")
        finally:
            db.close()

    def test_submodule_base_branch_from_gitmodules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            Path(tmp, ".gitmodules").write_text(
                """
[submodule "tests/gme"]
    path = tests/gme
    url = https://example.invalid/tests-gme.git
    branch = develop
""".lstrip(),
                encoding="utf-8",
            )

            self.assertEqual(submodule_base_branch(tmp, "tests\\gme", "main"), "develop")
            self.assertEqual(submodule_base_branch(tmp, "module/laws", "main"), "main")

    def test_prepare_worktree_dependencies_uses_only_required_local_caches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            worktree = root / "worktree"
            remote_tests = root / "remote-tests"
            remote_hudong = root / "remote-hudong"
            remote_yunji = root / "remote-yunji"
            remote_haizhou = root / "remote-haizhou"
            remote_laws = root / "remote-laws"
            remote_acis = root / "remote-acis"
            worktree.mkdir()

            self._init_repo(remote_tests, "src/laws/existing_test.cpp", "TEST(Existing, Case) {}\n")
            self._init_repo(remote_hudong, "README.md", "hudong tests\n")
            self._init_repo(remote_yunji, "README.md", "yunji tests\n")
            self._init_repo(remote_haizhou, "README.md", "haizhou tests\n")
            self._init_repo(remote_laws, "laws.cpp", "int laws_value = 1;\n")
            self._init_repo(remote_acis, "acis.cpp", "int acis_value = 1;\n")
            self._clone_repo(remote_tests, source_root / "tests" / "gme")
            self._clone_repo(remote_hudong, source_root / "tests" / "hudong")
            self._clone_repo(remote_yunji, source_root / "tests" / "yunji")
            self._clone_repo(remote_haizhou, source_root / "tests" / "haizhou")
            self._clone_repo(remote_laws, source_root / "module" / "laws")
            self._clone_repo(remote_acis, source_root / "_deps" / "acis")

            (worktree / ".gitmodules").write_text(
                f"""
[submodule "tests/gme"]
    path = tests/gme
    url = {remote_tests.as_posix()}
    branch = main
[submodule "_deps/acis"]
    path = _deps/acis
    url = {remote_acis.as_posix()}
    branch = main
[submodule "tests/hudong"]
    path = tests/hudong
    url = {remote_hudong.as_posix()}
    branch = main
[submodule "tests/yunji"]
    path = tests/yunji
    url = {remote_yunji.as_posix()}
    branch = main
[submodule "tests/haizhou"]
    path = tests/haizhou
    url = {remote_haizhou.as_posix()}
    branch = main
[submodule "data/gme"]
    path = data/gme
    url = https://example.invalid/data-gme.git
    branch = main
[submodule "data/public"]
    path = data/public
    url = https://example.invalid/data-public.git
    branch = main
[submodule "module/laws"]
    path = module/laws
    url = {remote_laws.as_posix()}
    branch = main
[submodule "module/base"]
    path = module/base
    url = https://example.invalid/base.git
    branch = main
""".lstrip(),
                encoding="utf-8",
            )

            cfg = AgentConfig(gme_repo_path=str(source_root))
            prepared = prepare_worktree_dependencies(cfg, worktree, "laws", "tests/gme", lambda _level, _message: None)

            self.assertEqual(prepared, ["tests/gme", "tests/hudong", "tests/yunji", "tests/haizhou", "module/laws", "_deps/acis"])
            self.assertTrue((worktree / "tests" / "gme" / ".git").exists())
            self.assertTrue((worktree / "tests" / "gme" / "src" / "laws" / "existing_test.cpp").exists())
            self.assertTrue((worktree / "tests" / "hudong" / ".git").exists())
            self.assertTrue((worktree / "tests" / "yunji" / ".git").exists())
            self.assertTrue((worktree / "tests" / "haizhou" / ".git").exists())
            self.assertTrue((worktree / "module" / "laws" / "laws.cpp").exists())
            self.assertTrue((worktree / "module" / "laws" / ".git").exists())
            self.assertTrue((worktree / "_deps" / "acis" / ".git").exists())
            self.assertFalse((worktree / "data" / "gme").exists())
            self.assertFalse((worktree / "data" / "public").exists())
            self.assertFalse((worktree / "module" / "base").exists())

    def test_prepare_worktree_dependencies_clones_missing_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote_repo = root / "remote-test"
            source_root = root / "source"
            worktree = root / "worktree"
            source_root.mkdir()
            (source_root / "tests" / "gme").mkdir(parents=True)
            worktree.mkdir()

            self._init_repo(remote_repo, "README.md", "test repo\n")
            (worktree / ".gitmodules").write_text(
                f"""
[submodule "tests/gme"]
    path = tests/gme
    url = {remote_repo.as_posix()}
    branch = main
""".lstrip(),
                encoding="utf-8",
            )

            cfg = AgentConfig(gme_repo_path=str(source_root))
            prepared = prepare_worktree_dependencies(cfg, worktree, "laws", "tests/gme", lambda _level, _message: None)

            self.assertEqual(prepared, ["tests/gme"])
            self.assertTrue((worktree / "tests" / "gme" / ".git").exists())
            self.assertTrue((worktree / "tests" / "gme" / "README.md").exists())

    def test_only_target_repo_changes_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            subprocess.run(["git", "config", "user.email", "agent@example.invalid"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "GME Agent"], cwd=tmp, check=True)
            target = Path(tmp, "tests", "gme")
            target.mkdir(parents=True)
            (target / "existing.cpp").write_text("int old_value = 1;\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            (target / "existing.cpp").write_text("int old_value = 2;\n", encoding="utf-8")
            Path(tmp, "timer_res_.csv").write_text("", encoding="utf-8")
            ensure_only_target_repo_changed(tmp, normalize_repo_path("tests\\gme"))

            Path(tmp, "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ensure_only_target_repo_changed(tmp, "tests/gme")

    def test_load_config_options_from_git_and_gitmodules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            subprocess.run(["git", "config", "user.email", "agent@example.invalid"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "GME Agent"], cwd=tmp, check=True)
            Path(tmp, "README.md").write_text("test repo\n", encoding="utf-8")
            Path(tmp, ".gitmodules").write_text(
                """
[submodule "tests/gme"]
    path = tests/gme
    url = https://example.invalid/tests-gme.git
    branch = main
[submodule "module/laws"]
    path = module/laws
    url = https://example.invalid/laws.git
    branch = develop
""".lstrip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmp, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://example.invalid/gme.git"], cwd=tmp, check=True)

            options = load_config_options(AgentConfig(gme_repo_path=tmp))

            self.assertIn("main", options["branches"])
            self.assertIn("origin", options["remotes"])
            self.assertIn("tests/gme", options["test_repos"])
            self.assertIn("laws", options["modules"])
            self.assertIn("module/laws", options["module_repos"])
            self.assertIn("gme-test-generation", options["builtin_skills"])
            self.assertIn("gme-module-test-analyzer", options["builtin_skills"])
            self.assertIn("gme-acis-interface-analyzer", options["builtin_skills"])
            self.assertIn("gme-test-writer", options["builtin_skills"])
            self.assertIn("gme-bug-fix", options["builtin_skills"])

    def test_builtin_skill_dirs_exist(self) -> None:
        self.assertIsNotNone(CodexRunner._builtin_skill_dir("gme-test-generation"))
        self.assertIsNotNone(CodexRunner._builtin_skill_dir("gme-module-test-analyzer"))
        self.assertIsNotNone(CodexRunner._builtin_skill_dir("gme-acis-interface-analyzer"))
        self.assertIsNotNone(CodexRunner._builtin_skill_dir("gme-test-writer"))
        self.assertIsNotNone(CodexRunner._builtin_skill_dir("gme-bug-fix"))

    def test_test_generation_loads_staged_skills(self) -> None:
        db = AgentDb(":memory:")
        try:
            orchestrator = Orchestrator(AgentConfig(), db)
            self.assertEqual(
                orchestrator._test_skill_names(),
                [
                    "gme-test-generation",
                    "gme-module-test-analyzer",
                    "gme-acis-interface-analyzer",
                    "gme-test-writer",
                ],
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
