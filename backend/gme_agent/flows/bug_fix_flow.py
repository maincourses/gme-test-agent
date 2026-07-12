from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import shutil

from ..codex.runner import CodexRunner
from ..generated_tests import load_generated_tests_manifest
from ..git.diff import git_diff, git_status
from ..git.repositories import prepare_target_repo, prepare_worktree_dependencies
from ..git.worktree import normalize_repo_path, create_worktree
from ..prompts import bug_fix_prompt
from .skip_pr_flow import _test_blocks


def validate_fix_failure(ctx, failure: dict[str, Any]) -> dict[str, Any]:
    if failure.get("status") != "open":
        raise RuntimeError("Only open generated failures can be used to create a fix job.")
    if not failure.get("job_id"):
        raise RuntimeError("The selected failure is not associated with a test-generation job.")

    source_job = ctx.db.get_job(str(failure["job_id"]))
    if source_job.get("type") != "test_generation":
        raise RuntimeError("Only failures from test-generation jobs can be used to create a fix job.")
    if not source_job.get("worktree_path"):
        raise RuntimeError("The source test-generation job has no worktree path.")

    module = str(source_job.get("module") or "").strip()
    if not module:
        raise RuntimeError("The source test-generation job has no module.")

    source_worktree = Path(str(source_job["worktree_path"]))
    if not source_worktree.exists():
        raise RuntimeError(f"Source test-generation worktree does not exist: {source_worktree}")

    source_target_repo = _source_test_target_repo(ctx, source_job)
    manifest = load_generated_tests_manifest(source_worktree, source_target_repo)
    selected = _selected_manifest_test(manifest, failure)
    if selected is None:
        raise RuntimeError("Only failures listed in .gme-agent/generated_tests.json can be used for repair.")

    source_test_file = source_worktree / source_target_repo / selected["file"]
    if not source_test_file.exists():
        raise RuntimeError(f"Generated failure test file does not exist: {source_test_file}")
    block = _selected_test_block(source_test_file, selected["suite"], selected["name"])
    if "GTEST_SKIP" in block:
        raise RuntimeError("The selected failure test already contains GTEST_SKIP and should not be used for repair.")

    source_metadata = source_job.get("metadata") or {}
    if str(failure.get("id") or "") in set(source_metadata.get("skip_failure_ids") or []):
        raise RuntimeError("The selected failure was already submitted through a skip PR.")

    return {
        "source_job_id": source_job["id"],
        "source_worktree_path": str(source_worktree),
        "test_target_repo": source_target_repo,
        "generated_test_file": selected["file"],
        "test_suite": selected["suite"],
        "test_name": selected["name"],
        "gtest_filter": f"{selected['suite']}.{selected['name']}",
    }


def run_fix_job(ctx, job_id: str, failure: dict) -> None:
    emit = ctx._job_emit(job_id)
    try:
        fix_context = validate_fix_failure(ctx, failure)
        ctx.db.update_job(job_id, status="creating_worktree")
        module = str(ctx.db.get_job(job_id).get("module") or "")
        worktree = create_worktree(ctx.config, job_id, f"fix-{module}-{failure['id']}", emit)
        job = ctx.db.get_job(job_id)
        target_repo = ctx._job_target_repo(job)
        test_target_repo = fix_context["test_target_repo"]
        prepared_paths = prepare_worktree_dependencies(ctx.config, worktree.path, module, test_target_repo, emit)
        target = prepare_target_repo(ctx.config, worktree.path, target_repo, worktree.branch, emit)
        ctx.db.update_job(
            job_id,
            branch=target.branch,
            worktree_path=str(worktree.path),
            metadata=ctx._merge_metadata(
                job_id,
                {
                    **fix_context,
                    **ctx._target_metadata(worktree.branch, target),
                    "prepared_paths": prepared_paths,
                },
            ),
        )

        artifact_dir = ctx._artifact_dir(job_id)
        copied_test = _copy_failure_test_file(worktree.path, fix_context, emit)
        test_repo_path = worktree.path / test_target_repo
        test_repo_baseline_diff = git_diff(test_repo_path)

        gtest_filter = fix_context["gtest_filter"]
        ctx._run_configure_and_build(job_id, worktree.path)
        before_output = ctx._run_tests(job_id, worktree.path, gtest_filter, artifact_name="gtest_reproduce_before_fix.txt")
        _require_gtest_status(before_output, gtest_filter, "FAILED", "The selected test must fail before repair.")
        validation_commands = _validation_commands(ctx, job_id, worktree.path, gtest_filter, artifact_dir)

        prompt = bug_fix_prompt(
            failure,
            target.rel_path,
            test_repo=test_target_repo,
            test_file=copied_test,
            gtest_filter=gtest_filter,
            before_output=before_output,
            configure_command=validation_commands["configure"],
            build_command=validation_commands["build"],
            test_command=validation_commands["test"],
        )
        (artifact_dir / "bug_fix_prompt.md").write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote prompt artifact: {artifact_dir / 'bug_fix_prompt.md'}")

        ctx.db.update_job(job_id, status="running_codex")
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree.path, skill_names=ctx._bug_fix_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)

        ctx._run_configure_and_build(job_id, worktree.path)
        after_output = ctx._run_tests(job_id, worktree.path, gtest_filter, artifact_name="gtest_verify_after_fix.txt")
        _require_gtest_status(after_output, gtest_filter, "OK", "The selected test must pass after repair.")
        _ensure_fix_scope(worktree.path, target.rel_path, test_target_repo, test_repo_baseline_diff)

        ctx._write_job_artifacts(job_id, worktree.path, artifact_dir)
        ctx.db.update_job(
            job_id,
            status="needs_review",
            metadata=ctx._merge_metadata(
                job_id,
                {
                    "artifact_dir": str(artifact_dir),
                    "fix_validated": True,
                },
            ),
        )
        ctx.db.update_failure(failure["id"], status="fix_ready")
        emit("info", "Bug fix job finished and is ready for review.")
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        ctx.db.update_failure(failure["id"], status="fix_failed")
        emit("error", str(exc))


def _source_test_target_repo(ctx, source_job: dict[str, Any]) -> str:
    metadata = source_job.get("metadata") or {}
    return normalize_repo_path(str(metadata.get("target_repo") or ctx._test_target_repo()))


def _selected_manifest_test(manifest: dict[str, Any], failure: dict[str, Any]) -> dict[str, str] | None:
    suite = str(failure.get("test_suite") or "")
    name = str(failure.get("test_name") or "")
    for item in manifest.get("tests") or []:
        if str(item.get("suite") or "") == suite and str(item.get("name") or "") == name:
            return {
                "file": normalize_repo_path(str(item.get("file") or "")),
                "suite": suite,
                "name": name,
            }
    return None


def _selected_test_block(file_path: Path, suite: str, name: str) -> str:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    rel_path = normalize_repo_path(file_path.name)
    for start, end, found_suite, found_name in _test_blocks(text, rel_path):
        if found_suite == suite and found_name == name:
            return text[start:end]
    raise RuntimeError(f"Could not find generated failure test {suite}.{name} in {file_path}")


def _copy_failure_test_file(worktree: Path, fix_context: dict[str, Any], emit) -> str:
    test_target_repo = normalize_repo_path(str(fix_context["test_target_repo"]))
    rel_file = normalize_repo_path(str(fix_context["generated_test_file"]))
    source = Path(str(fix_context["source_worktree_path"])) / test_target_repo / rel_file
    target = worktree / test_target_repo / rel_file
    if not source.exists():
        raise RuntimeError(f"Generated failure test file does not exist: {source}")
    if not target.exists():
        raise RuntimeError(f"Base repair worktree is missing the target test file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    emit("info", f"Copied generated failure test into repair worktree: {test_target_repo}/{rel_file}")
    return f"{test_target_repo}/{rel_file}"


def _validation_commands(ctx, job_id: str, worktree: Path, gtest_filter: str, artifact_dir: Path) -> dict[str, str]:
    build_dir = worktree / "build" / "vscode"
    mapping = ctx._command_mapping(worktree, build_dir, gtest_filter, artifact_dir=artifact_dir)
    return {
        "configure": ctx.config.configure_command.format(**mapping),
        "build": ctx.config.build_command.format(**mapping),
        "test": ctx.config.test_command.format(**mapping),
    }


def _require_gtest_status(output: str, full_name: str, expected_status: str, message: str) -> None:
    status = _gtest_status(output, full_name)
    if status == expected_status:
        return
    if status == "SKIPPED":
        raise RuntimeError(f"{message} The selected test was skipped instead: {full_name}")
    if status:
        raise RuntimeError(f"{message} Observed {status} for {full_name}.")
    raise RuntimeError(f"{message} No GTest result line was found for {full_name}.")


def _gtest_status(output: str, full_name: str) -> str:
    for status in ("FAILED", "OK", "SKIPPED"):
        pattern = re.compile(rf"^\[\s*{status}\s*\]\s+{re.escape(full_name)}(?:\s|\(|$)", re.MULTILINE)
        if pattern.search(output or ""):
            return status
    return ""


def _ensure_fix_scope(worktree: Path, module_repo: str, test_repo: str, test_repo_baseline_diff: str) -> None:
    module_rel = normalize_repo_path(module_repo)
    test_rel = normalize_repo_path(test_repo)
    module_path = worktree if module_rel == "." else worktree / module_rel
    test_path = worktree if test_rel == "." else worktree / test_rel

    current_test_diff = git_diff(test_path)
    if current_test_diff != test_repo_baseline_diff:
        raise RuntimeError("Codex changed the reproduced generated test file. Fix jobs may only modify module source code.")

    unexpected: list[str] = []
    for line in git_status(worktree).splitlines():
        path = _status_path(line)
        if not path:
            continue
        norm = normalize_repo_path(path)
        if _is_ignored_worktree_artifact(norm):
            continue
        if _is_under(norm, test_rel):
            continue
        if _is_under(norm, module_rel):
            if _is_include_path(norm):
                unexpected.append(line)
            continue
        unexpected.append(line)

    module_status = git_status(module_path)
    module_changes = []
    for line in module_status.splitlines():
        path = normalize_repo_path(_status_path(line))
        if not path:
            continue
        module_changes.append(path)
        if _is_include_path(path):
            unexpected.append(f"{module_rel}/{path}")

    if unexpected:
        raise RuntimeError(
            "Bug-fix jobs may only change implementation files under the selected module and must not edit include/ or tests. "
            "Unexpected changes:\n"
            + "\n".join(unexpected)
        )
    if not module_changes:
        raise RuntimeError("Codex did not change any module source files, so no repair can be reviewed.")


def _status_path(line: str) -> str:
    value = line[3:] if len(line) > 3 else ""
    if " -> " in value:
        value = value.split(" -> ", 1)[1]
    return value.strip()


def _is_under(path: str, root: str) -> bool:
    root = normalize_repo_path(root)
    if root == ".":
        return True
    return path == root or path.startswith(f"{root}/")


def _is_include_path(path: str) -> bool:
    norm = normalize_repo_path(path)
    return norm == "include" or norm.startswith("include/") or "/include/" in norm


def _is_ignored_worktree_artifact(path: str) -> bool:
    norm = normalize_repo_path(path)
    name = Path(norm).name
    return "/" not in norm and name.endswith(".csv") and name.startswith("timer_res")
