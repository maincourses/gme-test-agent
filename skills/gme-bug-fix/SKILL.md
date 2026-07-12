---
name: gme-bug-fix
description: Fix GME production-code bugs exposed by selected generated GME vs ACIS comparison tests. Use when Codex is asked by the GME Test Agent to repair one failing generated test and limit edits to the configured module repository such as module/laws.
---

# GME Bug Fix

## Operating Model

Work in a GME superproject repair worktree. The full worktree is available for reading context, but bug-fix edits must stay inside the target module repository named in the user prompt, normally `module/<module>`.

The selected failing GTest compares GME behavior against ACIS. Treat ACIS as the expected behavior unless the prompt or code clearly shows the generated test is invalid. Fix the smallest production-code issue that makes GME match ACIS for that one failing case.

The worktree is module-scoped: only the target module source is guaranteed to exist under `module/<module>`. Other module source trees may be empty and are expected to link from `module_lib/Debug` or `module_lib/Release`; do not attempt to repair or populate unrelated modules.

The generated test has already been copied into `tests/gme` by the agent only so the bug can be reproduced. That copied test is verification input, not part of the repair.

## Workflow

1. Read the failure id, test suite, test name, reason, GTest filter, reproduced failure output, generated test file, and target module repository from the prompt.
2. Inspect the failing generated test and the target module implementation.
3. Reproduce mentally from the code first; run the provided exact GTest filter when the environment is available.
4. Identify the narrowest module-code change that resolves the mismatch.
5. Modify only files under the target module repository.
6. Build the tests target.
7. Run the exact selected GTest filter.
8. If the build or selected test still fails, fix the module implementation and repeat build/test until the selected test passes or no safe production fix is possible.
9. Summarize the root cause, fix, validation, and residual risk.

## Hard Rules

- Do not edit files outside the target module repository.
- Do not edit `include/` paths.
- Do not edit `tests/gme`, generated tests, fixtures, or any test file.
- Do not paper over a production mismatch by changing expected values, weakening assertions, deleting tests, or adding skips.
- Do not add `GTEST_SKIP`.
- Do not update submodule pointers manually.
- Do not make broad refactors while fixing a single comparison failure.

## Fix Quality

Prefer localized, behavior-preserving changes. Preserve existing API contracts, error handling style, and numerical/geometric tolerance conventions. If the ACIS behavior depends on edge-case parsing or geometry semantics, document the condition in code only when the local style already uses comments for similar cases.
