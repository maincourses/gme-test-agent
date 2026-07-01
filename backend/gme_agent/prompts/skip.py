from __future__ import annotations


def skip_known_failure_prompt(test_log: str, failures: list[dict], target_repo: str = "tests/gme", allowed_files: list[str] | None = None) -> str:
    failure_lines = "\n".join(
        f"- id={f.get('id')} test={f.get('test_suite')}.{f.get('test_name')} file={f.get('file')} line={f.get('line')} reason={f.get('reason')}"
        for f in failures
    )
    allowed_file_lines = "\n".join(f"- `{path}`" for path in (allowed_files or [])) or f"- generated test files under `{target_repo}`"
    return f"""The newly generated GME-vs-ACIS tests produced failures.

Task:
- Inspect the test output.
- Add known-failure skips for the listed failing generated tests so default CI passes.
- Modify files only under `{target_repo}`. Read the rest of the GME worktree for context.
- Do not add or use helper headers.
- Use direct GoogleTest skips near the start of each failing test body:
  `GTEST_SKIP() << "[gme-agent-known-failure:<id>] <short reason>";`
- Keep `<id>` equal to the listed failure id.
- Do not hide compile errors, test framework errors, or invalid-test-input problems.
- Keep the failure reason and reproduction command visible in comments or skip text.
- Do not change GME source code, test assertions, fixtures, or non-listed tests.
- The final skip PR should contain only the listed failing generated tests plus compile-required includes/fixtures/helpers.

Allowed files:
{allowed_file_lines}

Failures to mark:
{failure_lines}

Test output:
```text
{test_log[-12000:]}
```
"""
