from __future__ import annotations


def bug_fix_prompt(failure: dict, target_repo: str = "") -> str:
    reproduce = failure.get("reproduce_command") or "Run the target GTest filter for this failure."
    target_rule = (
        f"- Modify files only under `{target_repo}`. Read the rest of the GME worktree for context.\n"
        if target_repo
        else ""
    )
    return f"""You are working in the GME repository.

Goal:
- Fix this known GME-vs-ACIS mismatch in production code.
- Failure id: {failure.get("id")}
- Test: {failure.get("test_suite")}.{failure.get("test_name")}
- Reason: {failure.get("reason")}

Reproduce:
```powershell
{reproduce}
```

Rules:
- The GME superproject worktree is module-scoped; unrelated module source trees may be empty and linked from `module_lib`.
{target_rule.rstrip()}
- First reproduce the failure with the provided GTest filter if possible.
- Make the smallest production-code change that makes GME match ACIS for the failing case.
- Keep or add focused regression coverage.
- If the corresponding guarded skip is inside the target repository, remove or update it only after the target test passes.
- If the skip is outside the target repository, do not edit it; mention it in the summary.
- Run the target test, then the most relevant module-level regression tests.

Deliverables:
- Code change.
- Test result summary.
- Any residual risk or follow-up needed.
"""
