from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AgentConfig


DEFAULT_REASONING_EFFORTS = ["low", "medium", "high", "xhigh"]


def load_codex_model_options(config: AgentConfig) -> dict[str, Any]:
    try:
        from openai_codex import Codex, CodexConfig  # type: ignore

        cwd = str(Path(config.gme_repo_path)) if Path(config.gme_repo_path).exists() else None
        with Codex(CodexConfig(cwd=cwd)) as codex:
            response = codex.models()
        return {
            "models": serialize_codex_models(response),
            "reasoning_efforts": DEFAULT_REASONING_EFFORTS,
            "error": "",
        }
    except Exception as exc:
        models = []
        if config.model:
            models.append(
                {
                    "id": config.model,
                    "display_name": config.model,
                    "description": "当前配置的模型",
                    "default_reasoning_effort": "",
                    "supported_reasoning_efforts": DEFAULT_REASONING_EFFORTS,
                }
            )
        return {
            "models": models,
            "reasoning_efforts": DEFAULT_REASONING_EFFORTS,
            "error": str(exc),
        }


def serialize_codex_models(response: Any) -> list[dict[str, Any]]:
    models = []
    for model in getattr(response, "data", []) or []:
        model_id = str(getattr(model, "id", "") or getattr(model, "model", "")).strip()
        if not model_id:
            continue
        efforts = []
        for option in getattr(model, "supported_reasoning_efforts", []) or []:
            effort = getattr(option, "reasoning_effort", option)
            value = str(getattr(effort, "value", effort)).strip()
            if value:
                efforts.append(value)
        default_effort = getattr(model, "default_reasoning_effort", "")
        models.append(
            {
                "id": model_id,
                "display_name": str(getattr(model, "display_name", "") or model_id),
                "description": str(getattr(model, "description", "") or ""),
                "default_reasoning_effort": str(getattr(default_effort, "value", default_effort) or ""),
                "supported_reasoning_efforts": list(dict.fromkeys(efforts)),
            }
        )
    return models
