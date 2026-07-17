from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from ..runtime import skill_root
from ..settings.config import AgentConfig


EventCallback = Callable[[str, str], None]


@dataclass(slots=True)
class CodexResult:
    final_response: str
    thread_id: str | None = None
    raw: str = ""


class CodexRunner:
    def __init__(self, config: AgentConfig, emit: EventCallback):
        self.config = config
        self.emit = emit

    def run(
        self,
        prompt: str,
        cwd: str | Path,
        thread_id: str | None = None,
        skill_names: list[str] | None = None,
    ) -> CodexResult:
        if not self.config.codex_enabled:
            self.emit("info", "Codex is disabled in config; wrote the prompt artifact instead of executing it.")
            return CodexResult(final_response="Codex disabled by config.", thread_id=thread_id)

        return self._run_python_sdk(prompt, cwd, thread_id, skill_names or [])

    def _run_python_sdk(self, prompt: str, cwd: str | Path, thread_id: str | None, skill_names: list[str]) -> CodexResult:
        try:
            from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, TextInput  # type: ignore
            from openai_codex.types import ReasoningEffort  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Codex Python SDK is required. Install it with: python -m pip install -r requirements.txt"
            ) from exc

        sandbox = {
            "read-only": Sandbox.read_only,
            "workspace-write": Sandbox.workspace_write,
            "full-access": Sandbox.full_access,
            "danger-full-access": Sandbox.full_access,
        }.get(self.config.sandbox, Sandbox.workspace_write)
        approval_mode = {
            "never": ApprovalMode.deny_all,
            "deny_all": ApprovalMode.deny_all,
            "on-request": ApprovalMode.auto_review,
            "on_request": ApprovalMode.auto_review,
            "auto_review": ApprovalMode.auto_review,
        }.get(self.config.approval_policy, ApprovalMode.deny_all)
        reasoning_effort = self._reasoning_effort(self.config.reasoning_effort, ReasoningEffort)

        with self._staged_skills(cwd, skill_names) as staged_skill_names:
            with Codex(CodexConfig(cwd=str(cwd))) as codex:
                if thread_id:
                    thread = codex.thread_resume(
                        thread_id,
                        approval_mode=approval_mode,
                        cwd=str(cwd),
                        model=self.config.model or None,
                        sandbox=sandbox,
                    )
                else:
                    thread = codex.thread_start(
                        approval_mode=approval_mode,
                        cwd=str(cwd),
                        model=self.config.model or None,
                        sandbox=sandbox,
                    )
                self.emit("info", f"Running Codex SDK thread {thread.id}.")
                run_input = self._run_inputs(prompt, staged_skill_names, TextInput)
                result = thread.run(
                    run_input,
                    approval_mode=approval_mode,
                    cwd=str(cwd),
                    effort=reasoning_effort,
                    model=self.config.model or None,
                    sandbox=sandbox,
                )
                final_response = result.final_response or ""
                return CodexResult(
                    final_response=final_response,
                    thread_id=thread.id,
                    raw=str(result),
                )

    @staticmethod
    def _reasoning_effort(value: str, effort_type):
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        try:
            return effort_type(normalized)
        except ValueError as exc:
            raise RuntimeError(f"Unsupported Codex reasoning effort: {value}") from exc

    def _run_inputs(self, prompt: str, skill_names: list[str], text_input_type) -> list:
        if not skill_names:
            return [text_input_type(prompt)]

        invocation = "\n".join(f"${name}" for name in skill_names)
        return [text_input_type(f"{invocation}\n\n{prompt}")]

    @contextmanager
    def _staged_skills(self, cwd: str | Path, skill_names: list[str]) -> Iterator[list[str]]:
        resolved_skills = self._resolved_skills(skill_names)
        if not resolved_skills:
            yield []
            return

        skills_root = Path(cwd).resolve() / ".agents" / "skills"
        created_targets: list[Path] = []
        staged_names: list[str] = []
        try:
            for name, skill_file in resolved_skills:
                source_dir = Path(skill_file).parent
                target_dir = skills_root / name
                if target_dir.exists():
                    if not (target_dir / "SKILL.md").is_file():
                        raise RuntimeError(f"Codex skill target exists but has no SKILL.md: {target_dir}")
                    self.emit("info", f"Using existing repository Codex skill: {name} ({target_dir / 'SKILL.md'})")
                else:
                    target_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source_dir, target_dir)
                    created_targets.append(target_dir)
                    self.emit("info", f"Staged Codex skill for this task: {name} ({target_dir / 'SKILL.md'})")
                staged_names.append(name)
            yield staged_names
        finally:
            for target_dir in reversed(created_targets):
                shutil.rmtree(target_dir, ignore_errors=True)
            for directory in (skills_root, skills_root.parent):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def _resolved_skills(self, skill_names: list[str]) -> list[tuple[str, str]]:
        if not self.config.use_builtin_skills:
            return []

        resolved = []
        seen = set()
        for name in skill_names:
            if name in seen:
                continue
            seen.add(name)
            skill_dir = self._builtin_skill_dir(name)
            if not skill_dir:
                self.emit("warn", f"Built-in Codex skill not found: {name}")
                continue
            skill_file = (skill_dir / "SKILL.md").resolve()
            self.emit("info", f"Using built-in Codex skill: {name} ({skill_file})")
            resolved.append((name, str(skill_file)))
        return resolved

    @staticmethod
    def _builtin_skill_dir(name: str) -> Path | None:
        safe_name = "".join(ch for ch in name if ch.isalnum() or ch == "-")
        if not safe_name:
            return None
        path = skill_root() / safe_name
        return path if (path / "SKILL.md").exists() else None
