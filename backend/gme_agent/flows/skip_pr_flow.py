from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import shutil
import subprocess
import time
import uuid

from ..codex.runner import CodexRunner
from ..git.diff import commit_paths, create_pr, push_branch
from ..git.worktree import normalize_repo_path, run_git
from ..prompts import skip_known_failure_prompt


def run_skip_pr_job(ctx, job_id: str) -> None:
    emit = ctx._job_emit(job_id)
    job = ctx.db.get_job(job_id)
    worktree_path = job.get("worktree_path")
    branch = job.get("branch")
    if not worktree_path or not branch:
        emit("error", "Job is missing worktree or branch.")
        return

    restore_target_path: Path | None = None
    restore_branch = ""
    full_generated_snapshots: dict[str, str] = {}
    try:
        worktree = Path(worktree_path)
        artifact_dir = ctx._artifact_dir(job_id)
        target_repo = ctx._job_target_repo(job)
        target_path = ctx._target_repo_path(worktree, target_repo)
        restore_target_path = target_path
        failures = _latest_open_failures_for_job(ctx.db.list_failures(), job_id)
        if not failures:
            raise RuntimeError("No latest open failures were found for the selected job.")

        commit_rel_paths = _generated_test_paths(job, failures, target_path)
        allowed_files = [normalize_repo_path(f"{target_repo}/{path}") for path in commit_rel_paths]
        test_log = _read_text(artifact_dir / "gtest_output.txt")
        prompt = skip_known_failure_prompt(test_log, failures, target_repo, allowed_files)
        (artifact_dir / "skip_prompt.md").write_text(prompt, encoding="utf-8")

        ctx.db.update_job(job_id, status="applying_skips")
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree, job.get("codex_thread_id"), skill_names=ctx._test_skill_names())
        (artifact_dir / "codex_skip_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)

        _format_generated_tests(worktree, target_path, commit_rel_paths, emit)
        full_generated_snapshots = _snapshot_generated_tests(target_path, commit_rel_paths)
        _prune_generated_tests_to_failures(target_path, commit_rel_paths, failures, emit)
        _format_generated_tests(worktree, target_path, commit_rel_paths, emit)
        ctx._run_configure_and_build(job_id, worktree)
        gtest_filter = _failure_suite_filter(failures)
        output = ctx._run_tests(job_id, worktree, gtest_filter, artifact_name="gtest_output_after_skip.txt")
        remaining_failures = ctx._record_failures(job_id, output, gtest_filter, artifact_dir=artifact_dir)
        ctx._write_job_artifacts(job_id, worktree, artifact_dir)
        if remaining_failures:
            names = ", ".join(f"{item.get('test_suite')}.{item.get('test_name')}" for item in remaining_failures)
            raise RuntimeError(f"Tests still failed after adding skips; PR was not created. Remaining failures: {names}")

        ctx.db.update_job(job_id, status="creating_pr")
        task_target_branch = str(job.get("metadata", {}).get("target_branch") or branch)
        restore_branch = task_target_branch
        skip_branch = _skip_pr_branch_name(job)
        target_base_branch = str(job.get("metadata", {}).get("target_base_branch") or ctx.config.base_branch)
        title = _skip_pr_title(job)
        _checkout_new_skip_branch(target_path, skip_branch, emit)
        commit_paths(target_path, commit_rel_paths, title, emit)
        push_branch(ctx.config, target_path, skip_branch, emit)
        pr_url = create_pr(ctx.config, target_path, title, _skip_pr_body(job, failures, gtest_filter), emit, base_branch=target_base_branch)
        _checkout_branch(target_path, task_target_branch, emit)
        _restore_generated_tests(target_path, full_generated_snapshots, emit)
        restored_paths = sorted(full_generated_snapshots)
        full_generated_snapshots = {}
        restore_branch = ""

        metadata = dict(ctx.db.get_job(job_id).get("metadata") or {})
        metadata["pr_url"] = pr_url
        metadata["skip_pr_url"] = pr_url
        metadata["skip_pr_branch"] = skip_branch
        metadata["skip_failure_ids"] = [str(failure.get("id") or "") for failure in failures]
        metadata["skip_commit_paths"] = commit_rel_paths
        metadata["skip_local_restored_paths"] = restored_paths
        ctx.db.update_job(job_id, status="pr_created", metadata=metadata)
    except Exception as exc:
        if full_generated_snapshots and restore_target_path is not None:
            try:
                if restore_branch:
                    _try_checkout_branch(restore_target_path, restore_branch, emit)
                _restore_generated_tests(restore_target_path, full_generated_snapshots, emit)
            except Exception as restore_exc:
                emit("error", f"Failed to restore full generated tests after skip PR staging: {restore_exc}")
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        emit("error", str(exc))


def _latest_open_failures_for_job(failures: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for failure in failures:
        if failure.get("job_id") != job_id or failure.get("status") != "open":
            continue
        key = (str(failure.get("test_suite") or ""), str(failure.get("test_name") or ""))
        if not key[0] or not key[1]:
            continue
        current = latest.get(key)
        if current is None or _failure_timestamp(failure) > _failure_timestamp(current):
            latest[key] = failure
    return sorted(latest.values(), key=_failure_timestamp, reverse=True)


def _failure_timestamp(failure: dict[str, Any]) -> str:
    return str(failure.get("updated_at") or failure.get("created_at") or "")


def _generated_test_paths(job: dict[str, Any], failures: list[dict[str, Any]], target_path: Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    resolved_target = target_path.resolve()
    for failure in failures:
        path_value = str(failure.get("file") or "")
        if not path_value:
            continue
        try:
            rel = Path(path_value).resolve().relative_to(resolved_target)
        except ValueError:
            continue
        rel_path = normalize_repo_path(rel)
        if not _is_generated_test_file(rel_path) or rel_path in seen:
            continue
        seen.add(rel_path)
        result.append(rel_path)

    if result:
        return result

    fallback = _generated_test_path_for_module(str(job.get("module") or ""))
    if fallback:
        return [fallback]
    raise RuntimeError("Could not determine the generated test file to update.")


def _generated_test_path_for_module(module: str) -> str:
    module_name = normalize_repo_path(module)
    if module_name == ".":
        return ""
    module_token = "_".join(part for part in module_name.split("/") if part)
    return normalize_repo_path(f"src/{module_name}/gme_agent_{module_token}_generated_test.cpp")


def _is_generated_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("gme_agent_") and name.endswith("_generated_test.cpp")


def _skip_pr_branch_name(job: dict[str, Any]) -> str:
    module = _branch_slug(str(job.get("module") or "generated"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_token = str(job.get("id") or "job")[:8]
    suffix = uuid.uuid4().hex[:6]
    return f"gme-agent/skip-{module}-{stamp}-{job_token}-{suffix}"


def _branch_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "generated"


def _checkout_new_skip_branch(target_path: Path, branch: str, emit) -> None:
    run_git(["checkout", "-b", branch], target_path, emit)


def _checkout_branch(target_path: Path, branch: str, emit) -> None:
    run_git(["checkout", branch], target_path, emit)


def _try_checkout_branch(target_path: Path, branch: str, emit) -> None:
    try:
        _checkout_branch(target_path, branch, emit)
    except Exception as exc:
        emit("warn", f"Could not switch back to {branch} before restoring generated tests: {exc}")


def _snapshot_generated_tests(target_path: Path, rel_paths: list[str]) -> dict[str, str]:
    snapshots: dict[str, str] = {}
    for rel_path in rel_paths:
        file_path = target_path / rel_path
        if not file_path.exists():
            raise RuntimeError(f"Generated test file was not found: {rel_path}")
        snapshots[rel_path] = file_path.read_text(encoding="utf-8", errors="replace")
    return snapshots


def _restore_generated_tests(target_path: Path, snapshots: dict[str, str], emit) -> None:
    for rel_path, text in snapshots.items():
        file_path = target_path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")
        emit("info", f"Restored full generated test file in local worktree: {rel_path}")


def _format_generated_tests(worktree: Path, target_path: Path, rel_paths: list[str], emit) -> None:
    if not rel_paths:
        return
    clang_format = shutil.which("clang-format")
    if clang_format is None:
        raise RuntimeError("clang-format was not found on PATH; cannot prepare format-clean skip PR.")

    style_file = worktree / ".clang-format"
    style = f"file:{style_file}" if style_file.exists() else "file"
    cmd = [clang_format, "-i", f"--style={style}", *rel_paths]
    emit("cmd", "clang-format -i --style=file " + " ".join(rel_paths))
    proc = subprocess.run(
        cmd,
        cwd=str(target_path),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout.strip():
        emit("cmd", proc.stdout.strip())
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or "clang-format failed.")


def _prune_generated_tests_to_failures(target_path: Path, rel_paths: list[str], failures: list[dict[str, Any]], emit) -> None:
    tests_by_path = _failure_tests_by_generated_path(target_path, rel_paths, failures)
    for rel_path in rel_paths:
        keep_tests = tests_by_path.get(rel_path, set())
        if not keep_tests:
            continue
        file_path = target_path / rel_path
        if not file_path.exists():
            raise RuntimeError(f"Generated test file was not found: {rel_path}")
        text = file_path.read_text(encoding="utf-8", errors="replace")
        pruned = _prune_generated_test_text(text, keep_tests, rel_path)
        file_path.write_text(pruned, encoding="utf-8")
        emit("info", f"Pruned {rel_path} to {len(keep_tests)} skipped failure test(s).")


def _failure_tests_by_generated_path(
    target_path: Path,
    rel_paths: list[str],
    failures: list[dict[str, Any]],
) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {}
    rel_set = set(rel_paths)
    unresolved: list[tuple[str, str]] = []
    resolved_target = target_path.resolve()
    for failure in failures:
        key = (str(failure.get("test_suite") or ""), str(failure.get("test_name") or ""))
        if not key[0] or not key[1]:
            continue
        path_value = str(failure.get("file") or "")
        rel_path = ""
        if path_value:
            try:
                rel_path = normalize_repo_path(Path(path_value).resolve().relative_to(resolved_target))
            except ValueError:
                rel_path = ""
        if rel_path in rel_set:
            result.setdefault(rel_path, set()).add(key)
        else:
            unresolved.append(key)

    if unresolved:
        if len(rel_paths) == 1:
            result.setdefault(rel_paths[0], set()).update(unresolved)
        else:
            names = ", ".join(f"{suite}.{name}" for suite, name in unresolved)
            raise RuntimeError(f"Could not map failures to generated test files: {names}")
    return result


_TEST_DECL_RE = re.compile(
    r"(?m)^[ \t]*(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)\s*\(\s*([^,\s]+)\s*,\s*([^)]+?)\s*\)\s*\{"
)


def _prune_generated_test_text(text: str, keep_tests: set[tuple[str, str]], rel_path: str = "generated test") -> str:
    blocks = _test_blocks(text, rel_path)
    if not blocks:
        raise RuntimeError(f"No GoogleTest test blocks were found in {rel_path}.")

    kept: set[tuple[str, str]] = set()
    chunks: list[str] = []
    last = 0
    for start, end, suite, test_name in blocks:
        key = (suite, test_name)
        if key in keep_tests:
            block_text = text[start:end]
            if "GTEST_SKIP" not in block_text:
                raise RuntimeError(f"Failure test {suite}.{test_name} in {rel_path} does not contain GTEST_SKIP().")
            chunks.append(text[last:end])
            last = end
            kept.add(key)
        else:
            chunks.append(text[last:start])
            last = end
    chunks.append(text[last:])

    missing = keep_tests - kept
    if missing:
        names = ", ".join(f"{suite}.{name}" for suite, name in sorted(missing))
        raise RuntimeError(f"Could not find failure tests in {rel_path}: {names}")
    return "".join(chunks)


def _test_blocks(text: str, rel_path: str) -> list[tuple[int, int, str, str]]:
    blocks: list[tuple[int, int, str, str]] = []
    pos = 0
    while True:
        match = _TEST_DECL_RE.search(text, pos)
        if match is None:
            return blocks
        brace = text.find("{", match.end() - 1)
        if brace < 0:
            raise RuntimeError(f"Could not find test body start in {rel_path}.")
        end = _matching_brace(text, brace)
        if end < 0:
            suite = _clean_test_name(match.group(2))
            name = _clean_test_name(match.group(3))
            raise RuntimeError(f"Could not find test body end for {suite}.{name} in {rel_path}.")
        blocks.append((match.start(), end + 1, _clean_test_name(match.group(2)), _clean_test_name(match.group(3))))
        pos = end + 1


def _clean_test_name(value: str) -> str:
    return value.strip().rstrip()


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    state = "code"
    i = start
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if ch == '"':
                state = "string"
                i += 1
                continue
            if ch == "'":
                state = "char"
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
        elif state == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                state = "code"
        elif state == "char":
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                state = "code"
        i += 1
    return -1


def _failure_suite_filter(failures: list[dict[str, Any]]) -> str:
    suites = []
    seen: set[str] = set()
    for failure in failures:
        suite = str(failure.get("test_suite") or "")
        if suite and suite not in seen:
            seen.add(suite)
            suites.append(f"{suite}.*")
    return ":".join(suites) or "*"


def _skip_pr_title(job: dict[str, Any]) -> str:
    module = str(job.get("module") or "generated").strip() or "generated"
    return f"feature({module}):gme agent test"


def _skip_pr_body(job: dict[str, Any], failures: list[dict[str, Any]], gtest_filter: str) -> str:
    lines = [
        "该 PR 由 GME Test Agent 自动生成，新增 GME vs ACIS 对比测试，并对当前已确认存在差异的失败用例增加 skip。",
        "",
        "本次新增测试用例：",
    ]
    for failure in failures:
        lines.append(f"{failure.get('test_suite')}.{failure.get('test_name')}")
    return "\n".join(lines)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
