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
    if job.get("status") in RUNNING_JOB_STATUSES:
        raise RuntimeError(f"Cannot delete a running job: {job_id}")

    deleted_worktree = False
    deleted_artifacts = False
    emit = ctx._job_emit(job_id)

    if cleanup_worktree:
        path = job.get("worktree_path")
        if path:
            worktree_path = Path(path)
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

