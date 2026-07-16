from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
            from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, SkillInput, TextInput  # type: ignore
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
            run_input = self._skill_inputs(skill_names, SkillInput) + [TextInput(prompt)]
            result = thread.run(
                run_input,
                approval_mode=approval_mode,
                cwd=str(cwd),
                model=self.config.model or None,
                sandbox=sandbox,
            )
            final_response = result.final_response or ""
            return CodexResult(
                final_response=final_response,
                thread_id=thread.id,
                raw=str(result),
            )

    def _skill_inputs(self, skill_names: list[str], skill_input_type) -> list:
        if not self.config.use_builtin_skills:
            return []

        inputs = []
        for name in skill_names:
            skill_dir = self._builtin_skill_dir(name)
            if not skill_dir:
                self.emit("warn", f"Built-in Codex skill not found: {name}")
                continue
            skill_file = (skill_dir / "SKILL.md").resolve()
            self.emit("info", f"Using built-in Codex skill: {name} ({skill_file})")
            inputs.append(skill_input_type(name=name, path=str(skill_file)))
        return inputs

    @staticmethod
    def _builtin_skill_dir(name: str) -> Path | None:
        safe_name = "".join(ch for ch in name if ch.isalnum() or ch == "-")
        if not safe_name:
            return None
        path = skill_root() / safe_name
        return path if (path / "SKILL.md").exists() else None
