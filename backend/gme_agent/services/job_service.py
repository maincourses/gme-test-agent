from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from ..git.worktree import remove_worktree


RUNNING_JOB_STATUSES = {
    "creating_worktree",
    "running_codex",
    "building",
    "running_tests",
    "applying_skips",
    "creating_pr",
    "cleaning_worktree",
}


def delete_job_record(ctx, job_id: str, *, cleanup_worktree: bool = True, delete_artifacts: bool = True) -> dict[str, Any]:
    job = ctx.db.get_job(job_id)
    emit = ctx._job_emit(job_id)
    if job.get("status") in RUNNING_JOB_STATUSES:
        emit("warn", f"Deleting stale job record with non-active status: {job.get('status')}")

    deleted_worktree = False
    deleted_artifacts = False

    if cleanup_worktree:
        paths = job_worktree_paths(ctx, job)
        if not paths:
            emit("warn", "Job has no recorded or discoverable worktree to delete.")
        for worktree_path in paths:
            if worktree_path.exists():
                try:
                    emit("info", f"Deleting worktree {worktree_path}")
                    remove_worktree(ctx.config, worktree_path, emit)
                    deleted_worktree = True
                except Exception as exc:
                    emit("warn", f"Could not remove worktree before deleting job record: {exc}")
            else:
                emit("warn", f"Worktree path no longer exists: {worktree_path}")

    if delete_artifacts:
        artifact_dir = ctx._artifact_dir(job_id)
        artifact_root = Path(ctx.config.artifact_root).resolve()
        target = artifact_dir.resolve()
        if target.exists():
            if target == artifact_root or artifact_root not in target.parents:
                raise RuntimeError(f"Refusing to remove artifact directory outside configured root: {target}")
            shutil.rmtree(target)
            deleted_artifacts = True

    deleted_rows = ctx.db.delete_job(job_id)
    return {
        "ok": True,
        "id": job_id,
        "deleted_rows": deleted_rows,
        "deleted_worktree": deleted_worktree,
        "deleted_artifacts": deleted_artifacts,
    }


def job_worktree_paths(ctx, job: dict[str, Any]) -> list[Path]:
    root = Path(ctx.config.worktree_root).resolve()
    result: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(path: str | Path) -> None:
        candidate = Path(path).resolve()
        if candidate == root or root not in candidate.parents:
            return
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)

    path = job.get("worktree_path")
    if path:
        add_candidate(path)

    job_id = str(job.get("id") or "")
    token = job_id[:8]
    if token and root.exists():
        for child in root.iterdir():
            if child.is_dir() and child.name.endswith(token):
                add_candidate(child)

    return result
