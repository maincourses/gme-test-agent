from __future__ import annotations

from pathlib import Path

from ..codex.runner import CodexRunner
from ..git.diff import ensure_only_target_repo_changed
from ..git.repositories import prepare_target_repo, prepare_worktree_dependencies
from ..git.worktree import create_worktree
from ..prompts import continue_test_generation_prompt, skip_known_failure_prompt, test_generation_prompt


AGENT_NOTES_PATH = ".gme-agent"


def run_test_generation_job(ctx, job_id: str, module: str, api_name: str, target_repo: str) -> None:
    emit = ctx._job_emit(job_id)
    try:
        ctx.db.update_job(job_id, status="creating_worktree")
        worktree = create_worktree(ctx.config, job_id, f"testgen-{module}", emit)
        prepared_paths = prepare_worktree_dependencies(ctx.config, worktree.path, module, target_repo, emit)
        target = prepare_target_repo(ctx.config, worktree.path, target_repo, worktree.branch, emit)
        ctx.db.update_job(
            job_id,
            branch=target.branch,
            worktree_path=str(worktree.path),
            metadata=ctx._merge_metadata(
                job_id,
                {
                    **ctx._target_metadata(worktree.branch, target),
                    "prepared_paths": prepared_paths,
                },
            ),
        )

        artifact_dir = ctx._artifact_dir(job_id)
        prompt = test_generation_prompt(module, api_name, target.rel_path)
        (artifact_dir / "test_generation_prompt.md").write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote prompt artifact: {artifact_dir / 'test_generation_prompt.md'}")

        ctx.db.update_job(job_id, status="running_codex")
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree.path, skill_names=ctx._test_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)
        if not ctx.config.codex_enabled:
            emit("warn", "Codex execution is disabled; only prompt and worktree were generated.")
        allowed_paths = [*prepared_paths, AGENT_NOTES_PATH]
        ensure_only_target_repo_changed(worktree.path, target.rel_path, allowed_support_paths=allowed_paths)

        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree.path)

        if ctx.config.auto_run_tests:
            test_output = ctx._run_tests(job_id, worktree.path, "*")
            failures = ctx._record_failures(job_id, test_output, "*", artifact_dir=artifact_dir)
            if failures:
                emit("warn", f"Recorded {len(failures)} failing tests.")
                if ctx.config.auto_apply_skips:
                    skip_prompt = skip_known_failure_prompt(
                        test_output,
                        failures,
                        target.rel_path,
                    )
                    (artifact_dir / "skip_prompt.md").write_text(skip_prompt, encoding="utf-8")
                    ctx.db.update_job(job_id, status="applying_skips")
                    skip_result = codex.run(skip_prompt, worktree.path, result.thread_id, skill_names=ctx._test_skill_names())
                    (artifact_dir / "codex_skip_result.txt").write_text(skip_result.final_response, encoding="utf-8")
                    ensure_only_target_repo_changed(worktree.path, target.rel_path, allowed_support_paths=allowed_paths)
                    if ctx.config.auto_run_build:
                        ctx._run_configure_and_build(job_id, worktree.path)
                    if ctx.config.auto_rerun_after_skip:
                        ctx._run_tests(job_id, worktree.path, "*", artifact_name="gtest_output_after_skip.txt")
                else:
                    (artifact_dir / "skip_prompt.md").write_text(
                        skip_known_failure_prompt(
                            test_output,
                            failures,
                            target.rel_path,
                        ),
                        encoding="utf-8",
                    )
                    emit("warn", "auto_apply_skips is disabled; review skip_prompt.md manually.")

        ctx._write_job_artifacts(job_id, worktree.path, artifact_dir)
        ctx.db.update_job(job_id, status="needs_review", metadata=ctx._merge_metadata(job_id, {"artifact_dir": str(artifact_dir)}))
        emit("info", "Job finished and is ready for review.")
        if ctx.config.auto_create_pr:
            ctx._run_pr_job(job_id)
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        emit("error", str(exc))


def run_test_extension_job(ctx, job_id: str, api_name: str) -> None:
    emit = ctx._job_emit(job_id)
    try:
        job = ctx.db.get_job(job_id)
        worktree_path = job.get("worktree_path")
        if not worktree_path:
            raise RuntimeError("Selected job has no worktree path. Create a test task first.")

        worktree = Path(worktree_path)
        if not worktree.exists():
            raise RuntimeError(f"Selected job worktree does not exist: {worktree}")

        module = str(job.get("module") or "")
        target_repo = ctx._job_target_repo(job)
        artifact_dir = ctx._artifact_dir(job_id)
        prompt = continue_test_generation_prompt(module, api_name or str(job.get("api_name") or ""), target_repo)
        prompt_path = artifact_dir / "test_generation_extend_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote extension prompt artifact: {prompt_path}")

        ctx.db.update_job(
            job_id,
            status="running_codex",
            api_name=api_name or job.get("api_name") or "",
            metadata=ctx._merge_metadata(job_id, {"last_extension_prompt": api_name}),
        )
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree, job.get("codex_thread_id"), skill_names=ctx._test_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        (artifact_dir / "codex_extend_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)

        allowed_paths = list((job.get("metadata") or {}).get("prepared_paths") or [])
        if AGENT_NOTES_PATH not in allowed_paths:
            allowed_paths.append(AGENT_NOTES_PATH)
        ensure_only_target_repo_changed(worktree, target_repo, allowed_support_paths=allowed_paths)

        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree)

        if ctx.config.auto_run_tests:
            test_output = ctx._run_tests(job_id, worktree, "*")
            ctx._record_failures(job_id, test_output, "*", artifact_dir=artifact_dir)

        ctx._write_job_artifacts(job_id, worktree, artifact_dir)
        ctx.db.update_job(job_id, status="needs_review", metadata=ctx._merge_metadata(job_id, {"artifact_dir": str(artifact_dir)}))
        emit("info", "Test extension finished and is ready for review.")
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        emit("error", str(exc))
