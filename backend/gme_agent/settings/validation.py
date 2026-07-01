from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from string import Formatter
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess

from ..runtime import skill_root
from .config import AgentConfig


KNOWN_PLACEHOLDERS = {
    "worktree",
    "build_dir",
    "test_executable",
    "gtest_filter",
    "test_module_name",
    "develop_module_option",
    "test_module_option",
    "artifact_dir",
    "gtest_xml_path",
}


def validate_config(config: AgentConfig) -> dict:
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    repo = Path(config.gme_repo_path)
    add("GME repo path exists", repo.exists(), str(repo))
    add("GME repo has .git", (repo / ".git").exists(), str(repo / ".git"))
    if config.initialize_submodules:
        add("GME repo has .gitmodules", (repo / ".gitmodules").exists(), str(repo / ".gitmodules"))
    test_target = repo / _repo_rel_path(config.test_target_repo)
    module_root = repo / _repo_rel_path(config.module_repo_root)
    add("Configured test target repo path", test_target.exists(), str(test_target))
    add("Configured module repo root path", module_root.exists(), str(module_root))
    add("PR strategy: target repo only", config.pr_strategy == "target_repo_only", config.pr_strategy)
    if config.use_builtin_skills:
        root = skill_root()
        for label, skill_name in (
            ("Built-in test-generation skill", config.test_generation_skill),
            ("Built-in module test analyzer skill", "gme-module-test-analyzer"),
            ("Built-in ACIS interface analyzer skill", "gme-acis-interface-analyzer"),
            ("Built-in test writer skill", "gme-test-writer"),
            ("Built-in bug-fix skill", config.bug_fix_skill),
        ):
            skill_file = root / skill_name / "SKILL.md"
            add(label, skill_file.exists(), str(skill_file))

    worktree_root = Path(config.worktree_root)
    artifact_root = Path(config.artifact_root)
    add("Worktree root parent exists", worktree_root.parent.exists(), str(worktree_root.parent))
    add("Artifact root parent exists", artifact_root.parent.exists(), str(artifact_root.parent))

    for tool in ("git", "cmake", "clang-format"):
        found = shutil.which(tool)
        add(f"Tool on PATH: {tool}", bool(found), found or "not found")

    sdk_spec = importlib.util.find_spec("openai_codex")
    if sdk_spec:
        try:
            version = importlib.metadata.version("openai-codex")
        except importlib.metadata.PackageNotFoundError:
            version = "installed"
        add("Codex Python SDK", True, f"openai-codex {version}")
    else:
        add("Codex Python SDK", False, "not installed; run: python -m pip install -r requirements.txt")

    auth_ok, auth_detail = _codex_auth_status()
    add("Codex auth", auth_ok, auth_detail)

    gh = shutil.which("gh")
    add("Tool on PATH: gh", bool(gh), gh or "not found; required for PR creation")

    if repo.exists():
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
            add("Git status readable", out.returncode == 0, out.stdout.strip())
        except Exception as exc:
            add("Git status readable", False, str(exc))

    for field in ("configure_command", "build_command", "test_command", "test_executable", "gtest_xml_path"):
        value = str(getattr(config, field))
        unknown = sorted(set(_extract_placeholders(value)) - KNOWN_PLACEHOLDERS)
        add(f"Template placeholders: {field}", not unknown, "unknown: " + ", ".join(unknown) if unknown else "ok")

    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks, "config": asdict(config)}


def _extract_placeholders(template: str) -> list[str]:
    names = []
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            names.append(field_name.split(".", 1)[0].split("[", 1)[0])
    return names


def _repo_rel_path(value: str) -> Path:
    normalized = str(value or ".").replace("\\", "/").strip("/")
    return Path("." if not normalized else normalized)


def _codex_auth_status() -> tuple[bool, str]:
    if os.environ.get("OPENAI_API_KEY"):
        return True, "OPENAI_API_KEY is set"
    auth_file = Path.home() / ".codex" / "auth.json"
    if auth_file.exists():
        return True, str(auth_file)
    return False, f"not found: {auth_file}; open Codex and sign in first"
