from __future__ import annotations

from ..codex.runner import CodexRunner
from ..git.diff import ensure_only_target_repo_changed
from ..git.repositories import prepare_target_repo, prepare_worktree_dependencies
from ..git.worktree import create_worktree
from ..prompts import bug_fix_prompt


def run_fix_job(ctx, job_id: str, failure: dict) -> None:
    emit = ctx._job_emit(job_id)
    try:
        ctx.db.update_job(job_id, status="creating_worktree")
        worktree = create_worktree(ctx.config, job_id, f"fix-{failure['id']}", emit)
        job = ctx.db.get_job(job_id)
        target_repo = ctx._job_target_repo(job)
        prepared_paths = prepare_worktree_dependencies(ctx.config, worktree.path, str(job.get("module") or ""), target_repo, emit)
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
        prompt = bug_fix_prompt(failure, target.rel_path)
        (artifact_dir / "bug_fix_prompt.md").write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote prompt artifact: {artifact_dir / 'bug_fix_prompt.md'}")

        gtest_filter = ctx._failure_filter(failure)
        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree.path)
        if ctx.config.auto_run_tests:
            ctx._run_tests(job_id, worktree.path, gtest_filter, artifact_name="gtest_reproduce_before_fix.txt")

        ctx.db.update_job(job_id, status="running_codex")
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree.path, skill_names=ctx._bug_fix_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)
        ensure_only_target_repo_changed(worktree.path, target.rel_path, allowed_support_paths=prepared_paths)

        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree.path)
        if ctx.config.auto_run_tests:
            ctx._run_tests(job_id, worktree.path, gtest_filter, artifact_name="gtest_verify_after_fix.txt")

        ctx._write_job_artifacts(job_id, worktree.path, artifact_dir)
        ctx.db.update_job(job_id, status="needs_review", metadata=ctx._merge_metadata(job_id, {"artifact_dir": str(artifact_dir)}))
        ctx.db.update_failure(failure["id"], status="fix_ready")
        emit("info", "Bug fix job finished and is ready for review.")
        if ctx.config.auto_create_pr:
            ctx._run_pr_job(job_id)
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        ctx.db.update_failure(failure["id"], status="fix_failed")
        emit("error", str(exc))
