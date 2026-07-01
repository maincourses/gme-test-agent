from __future__ import annotations


def test_generation_prompt(module: str, api_name: str, target_repo: str = "tests/gme") -> str:
    target = api_name or "the selected API"
    module_path = module.strip().replace("\\", "/").strip("/")
    module_token = "_".join(part for part in module_path.split("/") if part) or "module"
    module_prefix = "".join(part[:1].upper() + part[1:] for part in module_token.split("_") if part) or "Module"
    generated_file = f"{target_repo}/src/{module_path}/gme_agent_{module_token}_generated_test.cpp"
    generated_suite = f"{module_prefix}_GmeAgentGeneratedTest"
    generated_filter = f"{generated_suite}.*"
    return f"""You are working in the GME repository.

Goal:
- Add focused GoogleTest coverage comparing GME behavior with ACIS behavior.
- Target module: {module_path}
- Target API: {target}
- Target repository for edits: `{target_repo}`
- Generated test file: `{generated_file}`
- Generated test suite: `{generated_suite}`
- Suggested GTest filter: `{generated_filter}`

Required staged workflow:
1. Use the `gme-module-test-analyzer` skill to analyze existing tests and write `.gme-agent/module_test_profile.md`.
2. Use the `gme-acis-interface-analyzer` skill to analyze comparable GME and ACIS interfaces, including `_deps/acis/R35`, and write `.gme-agent/acis_interface_candidates.md`.
3. Use the `gme-test-writer` skill to generate the new tests in `{generated_file}` and write `.gme-agent/generated_tests.md`.

Create `.gme-agent/` if it does not exist. The `.gme-agent/*.md` files are working notes for this task; do not put them under `tests/gme` and do not treat them as test source files.

Rules:
- The GME superproject worktree is module-scoped: the selected module source, `{module_path}`, the test repo, `include/`, `module_lib/`, and `_deps/acis/` are available; unrelated module source trees may be empty.
- Modify test code only under `{target_repo}`. The only allowed non-test edits are `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, and `.gme-agent/generated_tests.md`.
- Modify tests only. Do not modify production code in module/ or include/ for this test-generation task.
- Follow the existing test style, includes, naming, initialization, and ACIS/GME conversion helpers.
- Place all generated module tests in `{generated_file}`.
- Use the generated suite `{generated_suite}` for every new TEST.
- Prefer small deterministic tests over broad randomized tests.
- If the user prompt implies a quantity or scope, follow that prompt; otherwise choose a small useful set of focused tests based on the analysis.
- A failing comparison is useful, but the test code itself must compile and be reviewable.
- Do not add GTEST_SKIP in this first pass. The runner will execute the tests first and then request guarded skips for true mismatches.

Deliverables:
- `.gme-agent/module_test_profile.md`
- `.gme-agent/acis_interface_candidates.md`
- `.gme-agent/generated_tests.md`
- `{generated_file}`
- A concise final summary listing modified files, generated tests, APIs covered, and `{generated_filter}`.
"""


def continue_test_generation_prompt(module: str, api_name: str, target_repo: str = "tests/gme") -> str:
    target = api_name or "continue expanding the selected module coverage"
    module_path = module.strip().replace("\\", "/").strip("/")
    module_token = "_".join(part for part in module_path.split("/") if part) or "module"
    module_prefix = "".join(part[:1].upper() + part[1:] for part in module_token.split("_") if part) or "Module"
    generated_file = f"{target_repo}/src/{module_path}/gme_agent_{module_token}_generated_test.cpp"
    generated_suite = f"{module_prefix}_GmeAgentGeneratedTest"
    generated_filter = f"{generated_suite}.*"
    return f"""You are continuing an existing GME Test Agent test-generation task.

Goal:
- Continue expanding focused GoogleTest coverage comparing GME behavior with ACIS behavior.
- Target module: {module_path}
- Additional user request: {target}
- Target repository for edits: `{target_repo}`
- Existing generated test file: `{generated_file}`
- Generated test suite: `{generated_suite}`
- Suggested GTest filter: `{generated_filter}`

Required workflow:
1. Read `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, and `.gme-agent/generated_tests.md` if they exist.
2. Re-check the current generated test file and nearby existing tests to avoid duplicates.
3. Add new focused tests to `{generated_file}` only. Keep using `{generated_suite}`.
4. Update `.gme-agent/generated_tests.md` with the new tests and any GTest filter changes. Update the other `.gme-agent/*.md` notes only if your new analysis changes them.

Rules:
- Reuse the existing worktree. Do not create new generated test files for this module.
- Modify test code only under `{target_repo}`. The only allowed non-test edits are `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, and `.gme-agent/generated_tests.md`.
- Do not modify production code in module/ or include/ for this test-generation task.
- Prefer small deterministic GME-vs-ACIS comparison tests that extend coverage beyond the existing generated tests.
- Do not add GTEST_SKIP in this pass.

Deliverables:
- Updated `{generated_file}`
- Updated `.gme-agent/generated_tests.md`
- A concise final summary listing newly added tests, APIs covered, and `{generated_filter}`.
"""
