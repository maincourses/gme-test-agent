from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock
from pathlib import Path
from typing import Any
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
    _classify_selected_tests,
    _failure_suite_filter,
    _format_generated_tests,
    _prune_manifest_tests_to_failures,
    _prune_manifest_tests_to_selection,
    _prune_generated_test_text,
    _require_selected_tests_reported,
    _restore_generated_tests,
    _selected_manifest_tests,
    _selected_pr_body,
    _selected_pr_branch_name,
    _skip_pr_branch_name,
    _skip_pr_body,
    _skip_pr_title,
    _snapshot_generated_tests,
    _validate_selected_test_results,
)
from gme_agent.flows.generated_test_edit_flow import delete_generated_tests
from gme_agent.flows.build_test_flow import record_failures
from gme_agent.flows.bug_fix_flow import _gtest_status, validate_fix_failure
from gme_agent.generated_tests import (
    ensure_generated_tests_use_selected_files,
    ensure_generated_tests_use_existing_files,
    load_generated_tests_manifest,
    require_generated_tests_manifest,
)
from gme_agent.services.orchestrator import JobAlreadyActiveError, Orchestrator
from gme_agent.api.server import _match_job_action, create_server
from gme_agent.prompts import (
    bug_fix_prompt,
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

    def test_api_requires_runtime_token_and_restricts_browser_origins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            save_config(
                config_path,
                AgentConfig(
                    gme_repo_path=str(root / "gme"),
                    worktree_root=str(root / "worktrees"),
                    artifact_root=str(root / "artifacts"),
                    database_path=str(root / "agent.db"),
                ),
            )
            token = "a" * 64
            server = create_server(config_path, "127.0.0.1", 0, token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}/api/health"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def status(headers: dict[str, str] | None = None, *, method: str = "GET") -> tuple[int, dict, Any]:
                request = urllib.request.Request(base_url, headers=headers or {}, method=method)
                try:
                    response = opener.open(request, timeout=5)
                    return response.status, json.loads(response.read().decode("utf-8")), response.headers
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read().decode("utf-8")), exc.headers

            try:
                self.assertEqual(status()[0], 401)
                self.assertEqual(status({"Authorization": "Bearer wrong-token"})[0], 401)
                self.assertEqual(
                    status(
                        {
                            "Authorization": f"Bearer {token}",
                            "Origin": "https://malicious.example",
                        }
                    )[0],
                    403,
                )

                code, data, headers = status(
                    {
                        "Authorization": f"Bearer {token}",
                        "Origin": "http://127.0.0.1:5173",
                    }
                )
                self.assertEqual(code, 200)
                self.assertTrue(data["authenticated"])
                self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:5173")
                self.assertNotEqual(headers.get("Access-Control-Allow-Origin"), "*")

                code, _, headers = status({"Origin": "null"}, method="OPTIONS")
                self.assertEqual(code, 200)
                self.assertIn("Authorization", headers.get("Access-Control-Allow-Headers", ""))
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
                server.agent_state.db.close()  # type: ignore[attr-defined]

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
                db.upsert_test_case_result(
                    job_id=job["id"],
                    test_suite="Suite",
                    test_name="Case",
                    status="passed",
                    run_id="run-1",
                )

                deleted = db.delete_job(job["id"])

                self.assertEqual(deleted["jobs"], 1)
                self.assertEqual(deleted["events"], 1)
                self.assertEqual(deleted["failures"], 1)
                self.assertEqual(deleted["test_case_results"], 1)
                with self.assertRaises(KeyError):
                    db.get_job(job["id"])
                self.assertEqual(db.list_events(job["id"]), [])
                self.assertEqual(db.list_failures(), [])
            finally:
                db.close()

    def test_delete_stale_running_job_discovers_unrecorded_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree_root = root / "worktrees"
            worktree = worktree_root / "testgen-base-20260708-181048-e477f65e"
            worktree.mkdir(parents=True)
            cfg = AgentConfig(
                gme_repo_path=str(root / "gme"),
                worktree_root=str(worktree_root),
                artifact_root=str(root / "artifacts"),
                database_path=str(root / "agent.db"),
            )
            db = AgentDb(cfg.database_path)
            try:
                job_id = "e477f65e-01ff-4f7e-99ae-bd2b0f12f082"
                db.create_job(job_id=job_id, job_type="test_generation", title="Generate base tests", module="base")
                db.update_job(job_id, status="creating_worktree")
                orchestrator = Orchestrator(cfg, db)

                with mock.patch("gme_agent.services.job_service.remove_worktree") as remove:
                    result = orchestrator.delete_job(job_id)

                remove.assert_called_once()
                self.assertEqual(Path(remove.call_args.args[1]).resolve(), worktree.resolve())
                self.assertTrue(result["deleted_worktree"])
                self.assertEqual(result["deleted_rows"]["jobs"], 1)
                with self.assertRaises(KeyError):
                    db.get_job(job_id)
            finally:
                db.close()

    def test_delete_active_running_job_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AgentConfig(database_path=str(Path(tmp) / "agent.db"))
            db = AgentDb(cfg.database_path)
            try:
                job_id = "job-active"
                db.create_job(job_id=job_id, job_type="test_generation", title="Generate tests")
                db.update_job(job_id, status="creating_worktree")
                orchestrator = Orchestrator(cfg, db)
                with orchestrator._active_jobs_lock:
                    orchestrator._active_jobs.add(job_id)

                with self.assertRaisesRegex(JobAlreadyActiveError, "already running another action"):
                    orchestrator.delete_job(job_id)
            finally:
                db.close()

    def test_job_actions_are_mutually_exclusive_until_background_thread_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AgentConfig(database_path=str(Path(tmp) / "agent.db"))
            db = AgentDb(cfg.database_path)
            started = threading.Event()
            release = threading.Event()
            try:
                job_id = "job-exclusive"
                db.create_job(job_id=job_id, job_type="test_generation", title="Generate tests")
                orchestrator = Orchestrator(cfg, db)

                def blocking_build(_job_id: str) -> None:
                    started.set()
                    release.wait(timeout=5)

                with mock.patch.object(orchestrator, "_run_build_job", side_effect=blocking_build):
                    response = orchestrator.build_job(job_id)
                    self.assertTrue(started.wait(timeout=2))
                    self.assertTrue(response["active"])
                    self.assertTrue(orchestrator.is_job_active(job_id))

                    with self.assertRaises(JobAlreadyActiveError):
                        orchestrator.run_tests_for_job(job_id)
                    with self.assertRaises(JobAlreadyActiveError):
                        orchestrator.cleanup_job_worktree(job_id)
                    with self.assertRaises(JobAlreadyActiveError):
                        orchestrator.delete_generated_tests_for_job(job_id, [{"suite": "Suite", "name": "Case"}])
                    with self.assertRaises(JobAlreadyActiveError):
                        orchestrator.delete_job(job_id)

                    release.set()
                    deadline = time.time() + 2
                    while orchestrator.is_job_active(job_id) and time.time() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(orchestrator.is_job_active(job_id))
            finally:
                release.set()
                db.close()

    def test_record_failures_keeps_stable_id_status_and_observation_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                orchestrator = Orchestrator(cfg, db)
                artifact_dir = orchestrator._artifact_dir(job["id"])
                output = """
D:/repo/tests/gme/src/laws/law_base_test.cpp:42: Failure
Expected equality of these values:
[  FAILED  ] Laws_BaseTest.GeneratedCase (1 ms)
"""

                first = record_failures(orchestrator, job["id"], output, "Laws_BaseTest.GeneratedCase", artifact_dir=artifact_dir)
                db.update_failure(first[0]["id"], status="fix_ready", metadata={"fix_job_id": "fix-1"})
                second = record_failures(orchestrator, job["id"], output, "Laws_BaseTest.GeneratedCase", artifact_dir=artifact_dir)

                self.assertEqual(second[0]["id"], first[0]["id"])
                self.assertEqual(second[0]["status"], "fix_ready")
                self.assertEqual(second[0]["metadata"]["fix_job_id"], "fix-1")
                observations = db.list_failure_observations(first[0]["id"])
                self.assertEqual(len(observations), 2)
                self.assertEqual({item["outcome"] for item in observations}, {"failed"})
                self.assertEqual(len({item["run_id"] for item in observations}), 2)
            finally:
                db.close()

    def test_record_failures_resolves_only_open_tests_reported_as_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                orchestrator = Orchestrator(cfg, db)
                artifact_dir = orchestrator._artifact_dir(job["id"])
                failed_output = """
D:/repo/tests/gme/src/laws/law_base_test.cpp:42: Failure
[  FAILED  ] Suite.Case (1 ms)
"""
                failure = record_failures(orchestrator, job["id"], failed_output, "Suite.Case", artifact_dir=artifact_dir)[0]

                record_failures(orchestrator, job["id"], "[       OK ] Suite.Case (1 ms)", "Suite.Case", artifact_dir=artifact_dir)
                self.assertEqual(db.get_failure(failure["id"])["status"], "resolved")
                self.assertEqual(
                    {item["outcome"] for item in db.list_failure_observations(failure["id"])},
                    {"failed", "passed"},
                )

                reopened = record_failures(orchestrator, job["id"], failed_output, "Suite.Case", artifact_dir=artifact_dir)[0]
                self.assertEqual(reopened["id"], failure["id"])
                self.assertEqual(reopened["status"], "open")
                record_failures(orchestrator, job["id"], "test executable was not found", "Suite.Case", artifact_dir=artifact_dir)
                self.assertEqual(db.get_failure(failure["id"])["status"], "open")
            finally:
                db.close()

    def test_partial_test_run_updates_only_reported_test_case_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                orchestrator = Orchestrator(cfg, db)
                artifact_dir = orchestrator._artifact_dir(job["id"])

                record_failures(
                    orchestrator,
                    job["id"],
                    "[       OK ] Suite.CaseA (1 ms)\n[       OK ] Suite.CaseB (1 ms)",
                    "Suite.*",
                    artifact_dir=artifact_dir,
                )
                initial = {
                    (item["test_suite"], item["test_name"]): item["status"]
                    for item in db.list_test_case_results(job["id"])
                }
                self.assertEqual(initial, {("Suite", "CaseA"): "passed", ("Suite", "CaseB"): "passed"})

                record_failures(
                    orchestrator,
                    job["id"],
                    "D:/repo/case.cpp:42: Failure\n[  FAILED  ] Suite.CaseA (1 ms)",
                    "Suite.CaseA",
                    artifact_dir=artifact_dir,
                )
                partial = {
                    (item["test_suite"], item["test_name"]): item["status"]
                    for item in db.list_test_case_results(job["id"])
                }
                self.assertEqual(partial, {("Suite", "CaseA"): "failed", ("Suite", "CaseB"): "passed"})
            finally:
                db.close()

    def test_db_migration_merges_duplicate_failure_identity_and_rewrites_job_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                create table jobs (
                    id text primary key, type text not null, status text not null, title text not null,
                    module text, api_name text, branch text, worktree_path text, codex_thread_id text,
                    created_at text not null, updated_at text not null,
                    metadata_json text not null default '{}', error text
                );
                create table events (
                    id integer primary key autoincrement, job_id text not null, ts text not null,
                    level text not null, message text not null
                );
                create table failures (
                    id text primary key, job_id text not null, status text not null,
                    test_suite text, test_name text, file text, line integer, reason text,
                    reproduce_command text, skip_id text, created_at text not null,
                    updated_at text not null, metadata_json text not null default '{}'
                );
                """
            )
            conn.execute(
                "insert into jobs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "job-1", "test_generation", "needs_review", "Generate tests", "laws", "", "", "", "",
                    "2026-07-08T10:00:00+0800", "2026-07-11T10:00:00+0800",
                    json.dumps({"skip_failure_ids": ["failure-open"]}), None,
                ),
            )
            conn.execute(
                "insert into failures values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "failure-fix", "job-1", "fix_ready", "Suite", "Case", "old.cpp", 10, "old",
                    "old command", "failure-fix", "2026-07-08T10:00:00+0800", "2026-07-08T11:00:00+0800",
                    json.dumps({"fix_job_id": "fix-1"}),
                ),
            )
            conn.execute(
                "insert into failures values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "failure-open", "job-1", "open", "Suite", "Case", "new.cpp", 20, "latest",
                    "new command", "failure-open", "2026-07-11T10:00:00+0800", "2026-07-11T10:00:00+0800",
                    "{}",
                ),
            )
            conn.commit()
            conn.close()

            db = AgentDb(path)
            try:
                failures = db.list_failures()
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0]["id"], "failure-fix")
                self.assertEqual(failures[0]["status"], "fix_ready")
                self.assertEqual(failures[0]["reason"], "latest")
                self.assertEqual(failures[0]["metadata"]["fix_job_id"], "fix-1")
                self.assertEqual(db.get_job("job-1")["metadata"]["skip_failure_ids"], ["failure-fix"])
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
        self.assertEqual(_match_job_action("/api/jobs/job-1/selected-tests-pr", "selected-tests-pr"), "job-1")

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
                db.upsert_test_case_result(
                    job_id=job["id"], test_suite="Suite", test_name="GeneratedA", status="passed", run_id="run-1"
                )
                db.upsert_test_case_result(
                    job_id=job["id"], test_suite="Suite", test_name="GeneratedB", status="failed", run_id="run-1"
                )
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
                self.assertEqual(
                    [(item["test_suite"], item["test_name"], item["status"]) for item in db.list_test_case_results(job["id"])],
                    [("Suite", "GeneratedB", "failed")],
                )
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
        self.assertIn("只能修改 `tests/gme`", prompt)
        self.assertIn("需要标记的失败测试", prompt)
        self.assertNotIn("GME_AGENT_KNOWN_FAILURE", prompt)
        self.assertNotIn("gme_agent_known_failure.hxx", prompt)
        self.assertNotIn("Failures to mark", prompt)

    def test_bug_fix_prompt_forbids_test_and_include_changes(self) -> None:
        prompt = bug_fix_prompt(
            {"id": "gmefail-1", "test_suite": "Suite", "test_name": "Case", "reason": "mismatch"},
            "module/laws",
            test_repo="tests/gme",
            test_file="tests/gme/src/laws/foo_test.cpp",
            gtest_filter="Suite.Case",
            before_output="[  FAILED  ] Suite.Case",
        )

        self.assertIn("生产代码只能修改 `module/laws`", prompt)
        self.assertIn("不要修改 `include/`", prompt)
        self.assertIn("不要修改 `tests/gme`", prompt)
        self.assertIn("不要添加 `GTEST_SKIP`", prompt)
        self.assertIn("只运行给定的准确 GTest filter", prompt)
        self.assertNotIn("You are working in the GME repository", prompt)

    def test_validate_fix_failure_requires_generated_open_unskipped_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "worktree"
            target = worktree / "tests" / "gme"
            rel_path = "src/laws/foo_test.cpp"
            (target / "src" / "laws").mkdir(parents=True)
            (target / rel_path).write_text(
                """#include "gtest/gtest.h"

TEST_F(Suite, Case) {
    EXPECT_TRUE(false);
}
""",
                encoding="utf-8",
            )
            notes = worktree / ".gme-agent"
            notes.mkdir(parents=True)
            (notes / "generated_tests.json").write_text(
                """
{
  "tests": [
    {"file": "src/laws/foo_test.cpp", "suite": "Suite", "name": "Case"}
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
                db.update_job(job["id"], worktree_path=str(worktree))
                failure = db.create_failure(failure_id="failure-1", job_id=job["id"], test_suite="Suite", test_name="Case")
                orchestrator = Orchestrator(cfg, db)

                context = validate_fix_failure(orchestrator, failure)

                self.assertEqual(context["generated_test_file"], rel_path)
                self.assertEqual(context["gtest_filter"], "Suite.Case")

                (target / rel_path).write_text(
                    """#include "gtest/gtest.h"

TEST_F(Suite, Case) {
    GTEST_SKIP() << "already skipped";
    EXPECT_TRUE(false);
}
""",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "GTEST_SKIP"):
                    validate_fix_failure(orchestrator, failure)
            finally:
                db.close()

    def test_gtest_status_reads_exact_selected_test(self) -> None:
        output = """
[       OK ] Suite.Pass (1 ms)
[  SKIPPED ] Suite.Skip (0 ms)
[  FAILED  ] Suite.Fail (1 ms)
"""
        self.assertEqual(_gtest_status(output, "Suite.Pass"), "OK")
        self.assertEqual(_gtest_status(output, "Suite.Skip"), "SKIPPED")
        self.assertEqual(_gtest_status(output, "Suite.Fail"), "FAILED")
        self.assertEqual(_gtest_status(output, "Suite.Missing"), "")

    def test_test_generation_prompt_uses_existing_files_manifest_and_no_helpers(self) -> None:
        prompt = test_generation_prompt("laws", "api_ndifferentiate_law", "tests/gme")

        self.assertIn(".gme-agent/generated_tests.json", prompt)
        self.assertIn("职责最匹配的现有 `.cpp`", prompt)
        self.assertIn("不要创建 `gme_agent_<module>_generated_test.cpp`", prompt)
        self.assertIn("不要新增 helper 函数", prompt)
        self.assertIn("必须直接写在各自的 `TEST_F` 函数体内", prompt)
        self.assertIn("生成的测试必须使用 `TEST_F`", prompt)
        self.assertIn("结束前删除", prompt)
        self.assertIn("timer_res_.csv", prompt)
        self.assertIn("构建测试目标", prompt)
        self.assertIn("Visual Studio 17 2022", prompt)
        self.assertIn("-DDEVELOP_LAWS=ON", prompt)
        self.assertIn("-DTEST_LAWS=ON", prompt)
        self.assertIn("cmake --build", prompt)
        self.assertIn("若构建失败由本次生成测试导致", prompt)
        self.assertIn("每次修复、删除或替换生成测试后都必须重新构建", prompt)
        self.assertIn("构建 -> 修复/删除/替换 -> 重新构建", prompt)
        self.assertIn("必须补充新的可构建测试并再次构建", prompt)
        self.assertIn("测试数量不足及其原因", prompt)
        self.assertIn("删除该测试并同步更新 `.gme-agent/generated_tests.md`", prompt)
        self.assertIn("unresolved external/LNK2019", prompt)
        self.assertIn("private/protected 访问错误", prompt)
        self.assertNotIn("You are working in the GME repository", prompt)
        self.assertNotIn("Generated test suite", prompt)

    def test_continue_generation_prompt_uses_existing_files_manifest_and_no_helpers(self) -> None:
        prompt = continue_test_generation_prompt("base", "extend coverage", "tests/gme")

        self.assertIn(".gme-agent/generated_tests.json", prompt)
        self.assertIn("职责最匹配的现有 `.cpp` 文件", prompt)
        self.assertIn("不要创建 `gme_agent_<module>_generated_test.cpp`", prompt)
        self.assertIn("不要新增 helper 函数", prompt)
        self.assertIn("必须直接写在各自的 `TEST_F` 函数体内", prompt)
        self.assertIn("生成的测试必须使用 `TEST_F`", prompt)
        self.assertIn("结束前删除", prompt)
        self.assertIn("timer_res_.csv", prompt)
        self.assertIn("构建测试目标", prompt)
        self.assertIn("Visual Studio 17 2022", prompt)
        self.assertIn("-DDEVELOP_BASE=ON", prompt)
        self.assertIn("-DTEST_BASE=ON", prompt)
        self.assertIn("cmake --build", prompt)
        self.assertIn("若构建失败由本次生成测试导致", prompt)
        self.assertIn("每次修复、删除或替换生成测试后都必须重新构建", prompt)
        self.assertIn("构建 -> 修复/删除/替换 -> 重新构建", prompt)
        self.assertIn("必须补充新的可构建测试并再次构建", prompt)
        self.assertIn("测试数量不足及其原因", prompt)
        self.assertIn("删除该测试并同步更新 `.gme-agent/generated_tests.md`", prompt)
        self.assertIn("unresolved external/LNK2019", prompt)
        self.assertIn("private/protected 访问错误", prompt)
        self.assertNotIn("You are continuing an existing", prompt)
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

    def test_generation_prompt_uses_structured_interface_selection(self) -> None:
        selected = [
            {
                "id": "laws.api-make-cubic.abc",
                "unique_symbol": "outcome api_make_cubic(double, double, double, double, double, double, law *&)",
                "target_file": "tests/gme/src/laws/kernel_kernapi_test.cpp",
                "test_suite": "Laws_KernapiTest",
            },
            {
                "id": "laws.law-zero.def",
                "unique_symbol": "int law::zero(double) const",
                "target_file": "tests/gme/src/laws/law_base_test.cpp",
                "test_suite": "Laws_BaseTest",
            },
        ]

        prompt = test_generation_prompt(
            "laws",
            "selected interfaces",
            "tests/gme",
            selected_interfaces=selected,
            tests_per_interface=2,
            extra_requirements="cover tolerance boundaries",
        )

        self.assertIn("共生成 4 个新测试", prompt)
        self.assertIn("tests/gme/src/laws/kernel_kernapi_test.cpp", prompt)
        self.assertIn("outcome api_make_cubic", prompt)
        self.assertIn("fixture `Laws_BaseTest`", prompt)
        self.assertIn("不得修改所选文件之外的测试 `.cpp`", prompt)
        self.assertIn("cover tolerance boundaries", prompt)

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

    def test_generated_tests_manifest_accepts_bom_and_normalizes_to_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            notes = worktree / ".gme-agent"
            notes.mkdir()
            path = notes / "generated_tests.json"
            content = """{
  "tests": [
    {
      "file": "src/laws/law_base_test.cpp",
      "suite": "Laws_BaseTest",
      "name": "GeneratedChineseCommentCase",
      "api": "中文接口"
    }
  ]
}
""".encode("utf-8")
            path.write_bytes(b"\xef\xbb\xbf" + content)

            manifest = load_generated_tests_manifest(worktree, "tests/gme")

            self.assertEqual(manifest["tests"][0]["api"], "中文接口")
            self.assertEqual(path.read_bytes(), content)

    def test_generated_tests_manifest_does_not_rewrite_invalid_bom_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            notes = worktree / ".gme-agent"
            notes.mkdir()
            path = notes / "generated_tests.json"
            content = b"\xef\xbb\xbf{invalid json}"
            path.write_bytes(content)

            with self.assertRaises(json.JSONDecodeError):
                load_generated_tests_manifest(worktree, "tests/gme")

            self.assertEqual(path.read_bytes(), content)

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

    def test_generated_tests_manifest_stays_in_selected_files(self) -> None:
        manifest = {
            "tests": [
                {
                    "file": "src/laws/kernel_kernapi_test.cpp",
                    "suite": "Laws_KernapiTest",
                    "name": "SelectedCase",
                }
            ]
        }

        ensure_generated_tests_use_selected_files(
            manifest,
            "tests/gme",
            ["tests/gme/src/laws/kernel_kernapi_test.cpp"],
        )
        with self.assertRaisesRegex(RuntimeError, "selected target files"):
            ensure_generated_tests_use_selected_files(
                manifest,
                "tests/gme",
                ["tests/gme/src/laws/law_base_test.cpp"],
            )

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
            stdout = "Warning: 1 uncommitted change\nhttps://example.invalid/pull/1\n"
            stderr = ""
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

    def test_selected_pr_branch_name_is_unique_test_branch(self) -> None:
        first = _selected_pr_branch_name({"id": "06437831-a6a2", "module": "laws"})
        second = _selected_pr_branch_name({"id": "06437831-a6a2", "module": "laws"})

        self.assertRegex(first, r"^gme-agent/tests-laws-\d{8}-\d{6}-06437831-[0-9a-f]{6}$")
        self.assertNotEqual(first, second)

    def test_selected_manifest_tests_preserves_request_order_and_rejects_unknown(self) -> None:
        manifest = [
            {"file": "src/laws/a.cpp", "suite": "Suite", "name": "First"},
            {"file": "src/laws/b.cpp", "suite": "Suite", "name": "Second"},
        ]

        selected = _selected_manifest_tests(
            manifest,
            [
                {"suite": "Suite", "name": "Second"},
                {"suite": "Suite", "name": "First"},
            ],
        )

        self.assertEqual([item["name"] for item in selected], ["Second", "First"])
        with self.assertRaisesRegex(RuntimeError, "generated_tests.json"):
            _selected_manifest_tests(manifest, [{"suite": "Suite", "name": "Missing"}])

    def test_selected_tests_are_classified_from_latest_output_and_failures(self) -> None:
        output = """
[       OK ] Suite.Passing (1 ms)
[  SKIPPED ] Suite.AlreadySkipped (0 ms)
[  FAILED  ] Suite.Failing (1 ms)
"""
        passing, skipped, failures = _classify_selected_tests(
            {("Suite", "Passing"), ("Suite", "AlreadySkipped"), ("Suite", "Failing")},
            [{"id": "gmefail-1", "test_suite": "Suite", "test_name": "Failing"}],
            output,
        )

        self.assertEqual(passing, {("Suite", "Passing")})
        self.assertEqual(skipped, {("Suite", "AlreadySkipped")})
        self.assertEqual([item["id"] for item in failures], ["gmefail-1"])

    def test_selected_tests_reject_unknown_status(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            _classify_selected_tests({("Suite", "Unknown")}, [], "[       OK ] Suite.Other (1 ms)")

    def test_selected_pr_body_lists_all_selected_tests(self) -> None:
        selected = [
            {"suite": "Suite", "name": "Passing"},
            {"suite": "Suite", "name": "Failing"},
        ]
        body = _selected_pr_body(
            selected,
            [{"test_suite": "Suite", "test_name": "Failing"}],
        )

        self.assertIn("本次新增测试用例：", body)
        self.assertIn("Suite.Passing", body)
        self.assertIn("Suite.Failing", body)
        self.assertIn("增加 skip", body)

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

    def test_prune_manifest_tests_keeps_only_selected_generated_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            rel_path = "src/laws/law_base_test.cpp"
            file_path = target / rel_path
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """TEST_F(LawsBaseTest, ExistingManualCase) {
    EXPECT_TRUE(true);
}

TEST_F(LawsBaseTest, GeneratedPassingCase) {
    EXPECT_TRUE(true);
}

TEST_F(LawsBaseTest, GeneratedFailingCase) {
    GTEST_SKIP() << "[gme-agent-known-failure:gmefail-1] mismatch";
}

TEST_F(LawsBaseTest, GeneratedUnselectedCase) {
    EXPECT_TRUE(true);
}
""",
                encoding="utf-8",
            )

            manifest = [
                {"file": rel_path, "suite": "LawsBaseTest", "name": "GeneratedPassingCase"},
                {"file": rel_path, "suite": "LawsBaseTest", "name": "GeneratedFailingCase"},
                {"file": rel_path, "suite": "LawsBaseTest", "name": "GeneratedUnselectedCase"},
            ]
            _prune_manifest_tests_to_selection(
                target,
                [rel_path],
                {("LawsBaseTest", "GeneratedPassingCase"), ("LawsBaseTest", "GeneratedFailingCase")},
                {("LawsBaseTest", "GeneratedFailingCase")},
                manifest,
                lambda _level, _message: None,
            )

            pruned = file_path.read_text(encoding="utf-8")
            self.assertIn("ExistingManualCase", pruned)
            self.assertIn("GeneratedPassingCase", pruned)
            self.assertIn("GeneratedFailingCase", pruned)
            self.assertNotIn("GeneratedUnselectedCase", pruned)

    def test_selected_pr_verification_requires_each_expected_status(self) -> None:
        output = """
[       OK ] Suite.Passing (1 ms)
[  SKIPPED ] Suite.Failing (0 ms)
"""
        selected = {("Suite", "Passing"), ("Suite", "Failing")}
        _require_selected_tests_reported(output, selected)
        _validate_selected_test_results(output, {("Suite", "Passing")}, {("Suite", "Failing")})

        with self.assertRaisesRegex(RuntimeError, "did not appear"):
            _require_selected_tests_reported(output, selected | {("Suite", "Missing")})
        with self.assertRaisesRegex(RuntimeError, "expected SKIPPED"):
            _validate_selected_test_results(output, set(), {("Suite", "Passing")})

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
