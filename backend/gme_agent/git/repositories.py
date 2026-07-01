from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import shutil

from ..settings.config import AgentConfig
from .worktree import EventCallback, is_git_repo, normalize_repo_path, origin_remote, remote_ref_exists, run_git


COMMON_REQUIRED_SUBMODULES = ("_deps/acis",)
TEST_PARTNER_SUBMODULES = ("tests/hudong", "tests/yunji", "tests/haizhou")


@dataclass(slots=True)
class TargetRepoInfo:
    branch: str
    path: Path
    rel_path: str
    base_branch: str


def prepare_worktree_dependencies(
    config: AgentConfig,
    worktree: str | Path,
    module: str,
    target_repo: str,
    emit: EventCallback,
) -> list[str]:
    worktree_path = Path(worktree)
    paths = module_scoped_submodule_paths(config, worktree_path, module, target_repo)
    prepared: list[str] = []

    for rel_path in paths:
        _prepare_git_dependency(config, worktree_path, rel_path, emit)
        prepared.append(rel_path)

    return _dedupe_paths(prepared)


def module_scoped_submodule_paths(config: AgentConfig, worktree: str | Path, module: str, target_repo: str) -> list[str]:
    module_root = normalize_repo_path(config.module_repo_root)
    target_module = normalize_repo_path(f"{module_root}/{normalize_repo_path(module)}") if module else "."
    target_repo = normalize_repo_path(target_repo)
    available_paths = set(list_submodule_paths(worktree))
    required_paths = [target_repo, *TEST_PARTNER_SUBMODULES, target_module, *COMMON_REQUIRED_SUBMODULES]
    return [path for path in _dedupe_paths(required_paths) if path in available_paths]


def list_submodule_paths(repo: str | Path) -> list[str]:
    gitmodules = Path(repo) / ".gitmodules"
    if not gitmodules.exists():
        return []
    try:
        output = run_git(["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"], repo)
    except RuntimeError:
        return []
    paths = []
    for line in output.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            paths.append(normalize_repo_path(parts[1]))
    return paths


def submodule_url(repo: str | Path, rel_path: str) -> str:
    rel_path = normalize_repo_path(rel_path)
    try:
        output = run_git(["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"], repo)
    except RuntimeError:
        return ""

    for line in output.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        key, value = parts
        if normalize_repo_path(value) != rel_path:
            continue
        prefix = key.removesuffix(".path")
        try:
            return run_git(["config", "-f", ".gitmodules", "--get", f"{prefix}.url"], repo).strip()
        except RuntimeError:
            return ""
    return ""


def submodule_gitlink_commit(repo: str | Path, rel_path: str) -> str:
    rel_path = normalize_repo_path(rel_path)
    try:
        output = run_git(["ls-tree", "HEAD", rel_path], repo).strip()
    except RuntimeError:
        return ""
    if not output:
        return ""
    parts = output.split()
    return parts[2] if len(parts) >= 3 and parts[1] == "commit" else ""


def prepare_target_repo(
    config: AgentConfig,
    worktree: str | Path,
    target_rel_path: str,
    branch: str,
    emit: EventCallback,
) -> TargetRepoInfo:
    worktree_path = Path(worktree)
    rel_path = normalize_repo_path(target_rel_path)
    target_path = worktree_path if rel_path == "." else worktree_path / rel_path
    if not target_path.exists():
        raise RuntimeError(f"Target repository path does not exist: {target_path}")
    if not is_git_repo(target_path):
        raise RuntimeError(f"Target path is not a git repository or submodule: {target_path}")

    base_branch = submodule_base_branch(worktree_path, rel_path, config.base_branch)
    if target_path != worktree_path:
        emit("info", f"Preparing target repo {rel_path} on branch {branch} from {base_branch}.")
        run_git(["checkout", "-B", branch], target_path, emit)
    return TargetRepoInfo(branch=branch, path=target_path, rel_path=rel_path, base_branch=base_branch)


def submodule_base_branch(worktree: str | Path, rel_path: str, default_branch: str) -> str:
    rel_path = normalize_repo_path(rel_path)
    if rel_path == ".":
        return default_branch

    try:
        output = run_git(["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"], worktree)
    except RuntimeError:
        return default_branch

    for line in output.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        key, value = parts
        if normalize_repo_path(value) != rel_path:
            continue
        prefix = key.removesuffix(".path")
        try:
            branch = run_git(["config", "-f", ".gitmodules", "--get", f"{prefix}.branch"], worktree).strip()
            return branch or default_branch
        except RuntimeError:
            return default_branch
    return default_branch


def _prepare_git_dependency(config: AgentConfig, worktree: Path, rel_path: str, emit: EventCallback) -> None:
    rel_path = normalize_repo_path(rel_path)
    source = Path(config.gme_repo_path) / rel_path
    target = worktree / rel_path
    branch = submodule_base_branch(worktree, rel_path, config.base_branch)
    desired_commit = submodule_gitlink_commit(worktree, rel_path)

    _prepare_dependency_target(worktree, target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if is_git_repo(source):
        emit("info", f"Preparing {rel_path} from local Git cache: {source}")
        _sync_local_cache_repo(source, branch, emit)
        run_git(["worktree", "add", "--detach", str(target), "HEAD"], source, emit)
    else:
        url = submodule_url(worktree, rel_path)
        if not url:
            raise RuntimeError(f"No submodule URL found for required dependency: {rel_path}")
        emit("info", f"Local Git cache is missing for {rel_path}; cloning from {url}")
        run_git(["clone", url, str(target)], worktree, emit)

    _sync_task_dependency_repo(target, branch, desired_commit, emit)


def _sync_local_cache_repo(repo: Path, branch: str, emit: EventCallback) -> None:
    remote = origin_remote(repo)
    if not remote:
        emit("warn", f"Local cache repo has no origin remote, skipped fetch/pull: {repo}")
        return

    emit("info", f"Syncing local cache repo {repo} on branch {branch}")
    run_git(["fetch", remote], repo, emit)
    if remote_ref_exists(repo, remote, branch):
        run_git(["checkout", "-B", branch, f"{remote}/{branch}"], repo, emit)
        run_git(["pull", "--ff-only", remote, branch], repo, emit)
    else:
        emit("warn", f"Remote branch {remote}/{branch} was not found for {repo}; keeping current HEAD.")


def _sync_task_dependency_repo(repo: Path, branch: str, desired_commit: str, emit: EventCallback) -> None:
    remote = origin_remote(repo)
    if remote:
        emit("info", f"Syncing task dependency repo {repo}")
        run_git(["fetch", remote], repo, emit)

    if desired_commit:
        run_git(["checkout", "--detach", desired_commit], repo, emit)
    elif remote and remote_ref_exists(repo, remote, branch):
        run_git(["checkout", "--detach", f"{remote}/{branch}"], repo, emit)
    else:
        emit("warn", f"No desired commit or remote branch found for task dependency {repo}; keeping current HEAD.")


def _prepare_dependency_target(worktree: Path, target: Path) -> None:
    resolved_worktree = worktree.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_worktree or resolved_worktree not in resolved_target.parents:
        raise RuntimeError(f"Refusing to replace path outside worktree: {resolved_target}")
    if not target.exists():
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def _dedupe_paths(paths: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for path in paths:
        value = normalize_repo_path(path)
        if value == "." or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
