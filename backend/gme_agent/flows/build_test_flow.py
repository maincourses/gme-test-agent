from __future__ import annotations

from pathlib import Path
import uuid
import shutil

from ..execution.runner import merge_failures, parse_gtest_failures, parse_gtest_xml, run_template_command


def run_tests_job(ctx, job_id: str, gtest_filter: str) -> None:
    job = ctx.db.get_job(job_id)
    path = job.get("worktree_path")
    if not path:
        ctx._emit(job_id, "error", "Job has no worktree path.")
        return
    try:
        ctx.db.update_job(job_id, status="running_tests")
        output = ctx._run_tests(job_id, Path(path), gtest_filter)
        ctx._record_failures(job_id, output, gtest_filter, artifact_dir=ctx._artifact_dir(job_id))
        ctx._write_job_artifacts(job_id, Path(path), ctx._artifact_dir(job_id))
        ctx.db.update_job(job_id, status="needs_review")
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        ctx._emit(job_id, "error", str(exc))


def run_build_job(ctx, job_id: str) -> None:
    job = ctx.db.get_job(job_id)
    path = job.get("worktree_path")
    if not path:
        ctx._emit(job_id, "error", "Job has no worktree path.")
        return
    try:
        ctx._run_configure_and_build(job_id, Path(path))
        ctx._write_job_artifacts(job_id, Path(path), ctx._artifact_dir(job_id))
        ctx.db.update_job(job_id, status="needs_review")
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        ctx._emit(job_id, "error", str(exc))


def run_configure_and_build(ctx, job_id: str, worktree: Path) -> str:
    emit = ctx._job_emit(job_id)
    ctx.db.update_job(job_id, status="building")
    build_dir = worktree / "build" / "vscode"
    _clean_build_dir(worktree, build_dir, emit)
    mapping = ctx._command_mapping(worktree, build_dir, "*", artifact_dir=ctx._artifact_dir(job_id))
    code, configure_output = run_template_command(ctx.config.configure_command, mapping, worktree, emit)
    if code != 0:
        raise RuntimeError(f"Configure failed with exit code {code}\n{configure_output[-4000:]}")
    code, build_output = run_template_command(ctx.config.build_command, mapping, worktree, emit)
    if code != 0:
        raise RuntimeError(f"Build failed with exit code {code}\n{build_output[-4000:]}")
    output = configure_output + "\n" + build_output
    (ctx._artifact_dir(job_id) / "build_output.txt").write_text(output, encoding="utf-8")
    return output


def _clean_build_dir(worktree: Path, build_dir: Path, emit) -> None:
    if not build_dir.exists():
        return
    resolved_worktree = worktree.resolve()
    resolved_build_dir = build_dir.resolve()
    if resolved_build_dir == resolved_worktree or resolved_worktree not in resolved_build_dir.parents:
        raise RuntimeError(f"Refusing to clean build directory outside worktree: {resolved_build_dir}")
    emit("info", f"Cleaning CMake build directory before configure: {build_dir}")
    if build_dir.is_dir():
        shutil.rmtree(build_dir)
    else:
        build_dir.unlink()


def run_tests(
    ctx,
    job_id: str,
    worktree: Path,
    gtest_filter: str,
    *,
    artifact_name: str = "gtest_output.txt",
) -> str:
    emit = ctx._job_emit(job_id)
    ctx.db.update_job(job_id, status="running_tests")
    build_dir = worktree / "build" / "vscode"
    artifact_dir = ctx._artifact_dir(job_id)
    mapping = ctx._command_mapping(worktree, build_dir, gtest_filter, artifact_dir=artifact_dir)
    xml_path = Path(mapping["gtest_xml_path"])
    if xml_path.exists():
        xml_path.unlink()
    code, output = run_template_command(ctx.config.test_command, mapping, worktree, emit)
    (artifact_dir / artifact_name).write_text(output, encoding="utf-8")
    if code != 0:
        emit("warn", f"Tests exited with code {code}")
    return output


def record_failures(ctx, job_id: str, test_output: str, gtest_filter: str, *, artifact_dir: Path) -> list[dict]:
    parsed = merge_failures(parse_gtest_xml(ctx._gtest_xml_path(artifact_dir)), parse_gtest_failures(test_output))
    failures = []
    job = ctx.db.get_job(job_id)
    cleared = _clear_stale_open_failures(ctx, job_id, parsed, gtest_filter)
    if cleared:
        ctx._emit(job_id, "info", f"Cleared {cleared} stale open failure records.")
    for item in parsed:
        failure_id = f"gmefail-{uuid.uuid4().hex[:10]}"
        failure = ctx.db.create_failure(
            failure_id=failure_id,
            job_id=job_id,
            test_suite=str(item.get("test_suite") or ""),
            test_name=str(item.get("test_name") or ""),
            file=str(item.get("file") or ""),
            line=int(item.get("line") or 0),
            reason=str(item.get("reason") or ""),
            reproduce_command=ctx._reproduce_command(gtest_filter),
            skip_id=failure_id,
            metadata={"gtest_filter": gtest_filter, "module": job.get("module") or "", "target_repo": ctx._job_target_repo(job)},
        )
        failures.append(failure)
        ctx._emit(job_id, "warn", f"Recorded failure {failure_id}: {failure['test_suite']}.{failure['test_name']}")
    return failures


def _clear_stale_open_failures(ctx, job_id: str, parsed: list[dict], gtest_filter: str) -> int:
    if _is_broad_gtest_filter(gtest_filter):
        return ctx.db.delete_open_failures_for_job(job_id)
    test_keys = _failure_test_keys(parsed) or _specific_gtest_filter_keys(gtest_filter)
    return ctx.db.delete_open_failures_for_tests(job_id, test_keys)


def _failure_test_keys(items: list[dict]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (str(item.get("test_suite") or ""), str(item.get("test_name") or ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _is_broad_gtest_filter(gtest_filter: str) -> bool:
    text = (gtest_filter or "*").strip() or "*"
    positive = text.split("-", 1)[0]
    patterns = [part for part in positive.split(":") if part]
    return not patterns or any("*" in pattern or "?" in pattern for pattern in patterns)


def _specific_gtest_filter_keys(gtest_filter: str) -> list[tuple[str, str]]:
    positive = (gtest_filter or "").split("-", 1)[0]
    keys: list[tuple[str, str]] = []
    for pattern in positive.split(":"):
        pattern = pattern.strip()
        if not pattern or "*" in pattern or "?" in pattern or "." not in pattern:
            continue
        suite, test = pattern.rsplit(".", 1)
        if suite and test:
            keys.append((suite, test))
    return keys
