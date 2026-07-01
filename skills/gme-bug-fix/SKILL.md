---
name: gme-bug-fix
description: Fix GME production-code bugs exposed by GME vs ACIS comparison tests. Use when Codex is asked by the GME Test Agent to repair a failing comparison case and limit edits to the configured module repository such as module/laws.
---

# GME Bug Fix

## Operating Model

Work in a GME superproject worktree. The full worktree is available for reading context, but bug-fix edits must stay inside the target module repository named in the user prompt, normally `module/<module>`.

The failing GTest compares GME behavior against ACIS. Treat ACIS as the expected behavior unless the prompt or code clearly shows the test is invalid. Fix the smallest production-code issue that makes GME match ACIS for the failing case.

The worktree is module-scoped: only the target module source is guaranteed to exist under `module/<module>`. Other module source trees may be empty and are expected to link from `module_lib/Debug` or `module_lib/Release`; do not attempt to repair or populate unrelated modules.

## Workflow

1. Read the failure id, test suite, test name, reason, reproduce command, and target repository from the prompt.
2. Inspect the failing test and the target module implementation.
3. Reproduce mentally from the code first; run the provided GTest command when the environment is available.
4. Identify the narrowest module-code change that resolves the mismatch.
5. Modify only files under the target module repository.
6. Add or keep focused regression coverage when the target repository already owns relevant tests or when the prompt permits edits there. If tests live outside the target repository, do not edit them; mention the needed test follow-up.
7. Run the target test and the smallest relevant module-level regression tests when possible.
8. Summarize the root cause, fix, validation, and residual risk.

## Hard Rules

- Do not edit files outside the target module repository.
- Do not edit the generated known-failure skip if it lives outside the target repository. Mention it in the summary instead.
- Do not paper over a production mismatch by changing expected values, weakening assertions, or adding skips.
- Do not update submodule pointers manually.
- Do not make broad refactors while fixing a single comparison failure.

## Fix Quality

Prefer localized, behavior-preserving changes. Preserve existing API contracts, error handling style, and numerical/geometric tolerance conventions. If the ACIS behavior depends on edge-case parsing or geometry semantics, document the condition in code only when the local style already uses comments for similar cases.
