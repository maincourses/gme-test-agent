from __future__ import annotations


def test_generation_prompt(module: str, api_name: str, target_repo: str = "tests/gme", build_guidance: str | None = None) -> str:
    target = api_name or "the selected API"
    module_path = module.strip().replace("\\", "/").strip("/")
    build_guidance_block = _build_guidance_block(module_path, build_guidance)
    return f"""You are working in the GME repository.

Goal:
- Add focused GoogleTest coverage comparing GME behavior with ACIS behavior.
- Target module: {module_path}
- Target API: {target}
- Target repository for edits: `{target_repo}`
- Test placement: insert each new test into the most relevant existing `.cpp` under `{target_repo}/src/{module_path}/`.
- Manifest: `.gme-agent/generated_tests.json`

Required staged workflow:
1. Use the `gme-module-test-analyzer` skill to analyze existing test files and write `.gme-agent/module_test_profile.md`.
2. Use the `gme-acis-interface-analyzer` skill to analyze comparable GME and ACIS interfaces, including `_deps/acis/R35`, and write `.gme-agent/acis_interface_candidates.md`.
3. Use the `gme-test-writer` skill to insert the new tests into the appropriate existing `.cpp` files and write `.gme-agent/generated_tests.md` plus `.gme-agent/generated_tests.json`.

Create `.gme-agent/` if it does not exist. The `.gme-agent/*.md` and `.gme-agent/generated_tests.json` files are working notes for this task; do not put them under `{target_repo}` and do not treat them as test source files.

Rules:
- The GME superproject worktree is module-scoped: the selected module source, `{module_path}`, the test repo, `include/`, `module_lib/`, and `_deps/acis/` are available; unrelated module source trees may be empty.
- Modify test code only under `{target_repo}`. The only allowed non-test edits are `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, `.gme-agent/generated_tests.md`, and `.gme-agent/generated_tests.json`.
- Modify tests only. Do not modify production code in module/ or include/ for this test-generation task.
- Before finishing, delete any temporary files outside `{target_repo}` and `.gme-agent`, such as `timer_res_.csv`, logs, caches, or test-run side effects. The final worktree must contain no out-of-scope changes.
- Do not create `gme_agent_<module>_generated_test.cpp` or any other new generated test `.cpp`.
- Do not add new helper functions, helper classes, helper headers, macros, or shared utilities. Put all setup, conversion, comparison, and cleanup logic directly inside each individual `TEST_F` body.
- Write generated tests as `TEST_F` cases, not standalone `TEST` cases.
- Reuse an existing fixture/suite from the chosen file. Do not create a new fixture unless the file has no usable fixture and the test cannot compile otherwise.
- Place each test near the closest existing tests for the same API, type, or behavior.
- Follow the existing include style, naming, initialization, tolerance, object lifetime, and ACIS/GME comparison patterns in the target file.
- Prefer small deterministic tests over broad randomized tests.
- Do not call private/protected members. Do not assume an API is linkable only because a header declares it; prefer APIs already used by existing tests or confirmed by implementation/exported symbols.
- If the user prompt implies a quantity or scope, follow that prompt; otherwise choose a small useful set of focused tests based on the analysis.
- A failing comparison is useful, but the test code itself must compile and be reviewable.
- Before your final response, build the test target using the configured or discoverable build command for this worktree. If the build fails because of tests you generated, fix those tests first. If a generated test cannot be made buildable with only test-code changes, delete that test and update `.gme-agent/generated_tests.md` and `.gme-agent/generated_tests.json`.
- After every generated-test fix, deletion, or replacement, build again. Repeat the build -> fix/delete/replace -> rebuild loop until the build passes or until you confirm there are no safe buildable tests left to generate.
- If deleting an invalid generated test leaves fewer tests than the user requested, add a replacement buildable test and rebuild again. Only finish with fewer tests than requested when no safe comparable API remains, an API is not linkable, the only useful checks require private/protected access, or there is no reliable GME-vs-ACIS comparison; explain the shortfall in the final response.
- Build-failure fixes must stay limited to the generated test code and `.gme-agent` notes. Do not modify GME production code, ACIS code, CMake files, shared helpers, or unrelated tests to make generated tests build.
- Treat unresolved external/LNK2019 as an API that is not linkable in this test target: remove or replace that generated test. Treat private/protected member access errors as invalid generated tests: use public behavior checks instead.
- If local build tools are unavailable, say exactly why in the final response; do not claim the generated tests build.
- Do not add GTEST_SKIP in this first pass. The runner will execute the tests first and then request guarded skips for true mismatches.

{build_guidance_block}

`.gme-agent/generated_tests.json` must be valid JSON with this shape:
```json
{{
  "tests": [
    {{
      "file": "{target_repo}/src/{module_path}/existing_test.cpp",
      "suite": "ExistingSuiteName",
      "name": "NewTestName",
      "api": "api_or_class_under_test",
      "anchor": "nearby existing test name"
    }}
  ]
}}
```

Deliverables:
- `.gme-agent/module_test_profile.md`
- `.gme-agent/acis_interface_candidates.md`
- `.gme-agent/generated_tests.md`
- `.gme-agent/generated_tests.json`
- Modified existing test `.cpp` file(s) under `{target_repo}/src/{module_path}/`
- A concise final summary listing modified files, generated tests, APIs covered, the exact suggested `--gtest_filter`, the build command/result, and any requested-count shortfall with reasons.
"""


def continue_test_generation_prompt(module: str, api_name: str, target_repo: str = "tests/gme", build_guidance: str | None = None) -> str:
    target = api_name or "continue expanding the selected module coverage"
    module_path = module.strip().replace("\\", "/").strip("/")
    build_guidance_block = _build_guidance_block(module_path, build_guidance)
    return f"""You are continuing an existing GME Test Agent test-generation task.

Goal:
- Continue expanding focused GoogleTest coverage comparing GME behavior with ACIS behavior.
- Target module: {module_path}
- Additional user request: {target}
- Target repository for edits: `{target_repo}`
- Test placement: insert each new test into the most relevant existing `.cpp` under `{target_repo}/src/{module_path}/`.
- Manifest: `.gme-agent/generated_tests.json`

Required workflow:
1. Read `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, `.gme-agent/generated_tests.md`, and `.gme-agent/generated_tests.json` if they exist.
2. Re-check nearby existing tests to avoid duplicates.
3. Add new focused tests to the appropriate existing `.cpp` files. Do not create generated test files.
4. Update `.gme-agent/generated_tests.json` so it contains all generated tests for this task, including earlier generated tests and the newly added ones.
5. Update `.gme-agent/generated_tests.md` with the new tests and exact GTest filter changes. Update the other `.gme-agent/*.md` notes only if your new analysis changes them.

Rules:
- Reuse the existing worktree.
- Modify test code only under `{target_repo}`. The only allowed non-test edits are `.gme-agent/module_test_profile.md`, `.gme-agent/acis_interface_candidates.md`, `.gme-agent/generated_tests.md`, and `.gme-agent/generated_tests.json`.
- Do not modify production code in module/ or include/ for this test-generation task.
- Before finishing, delete any temporary files outside `{target_repo}` and `.gme-agent`, such as `timer_res_.csv`, logs, caches, or test-run side effects. The final worktree must contain no out-of-scope changes.
- Do not create `gme_agent_<module>_generated_test.cpp` or any other new generated test `.cpp`.
- Do not add new helper functions, helper classes, helper headers, macros, or shared utilities. Put all setup, conversion, comparison, and cleanup logic directly inside each individual `TEST_F` body.
- Write generated tests as `TEST_F` cases, not standalone `TEST` cases.
- Reuse an existing fixture/suite from the chosen file. Do not create a new fixture unless the file has no usable fixture and the test cannot compile otherwise.
- Place each test near the closest existing tests for the same API, type, or behavior.
- Prefer small deterministic GME-vs-ACIS comparison tests that extend coverage beyond existing tests.
- Do not call private/protected members. Do not assume an API is linkable only because a header declares it; prefer APIs already used by existing tests or confirmed by implementation/exported symbols.
- Before your final response, build the test target using the configured or discoverable build command for this worktree. If the build fails because of tests you generated, fix those tests first. If a generated test cannot be made buildable with only test-code changes, delete that test and update `.gme-agent/generated_tests.md` and `.gme-agent/generated_tests.json`.
- After every generated-test fix, deletion, or replacement, build again. Repeat the build -> fix/delete/replace -> rebuild loop until the build passes or until you confirm there are no safe buildable tests left to generate.
- If deleting an invalid generated test leaves fewer tests than the user requested, add a replacement buildable test and rebuild again. Only finish with fewer tests than requested when no safe comparable API remains, an API is not linkable, the only useful checks require private/protected access, or there is no reliable GME-vs-ACIS comparison; explain the shortfall in the final response.
- Build-failure fixes must stay limited to the generated test code and `.gme-agent` notes. Do not modify GME production code, ACIS code, CMake files, shared helpers, or unrelated tests to make generated tests build.
- Treat unresolved external/LNK2019 as an API that is not linkable in this test target: remove or replace that generated test. Treat private/protected member access errors as invalid generated tests: use public behavior checks instead.
- If local build tools are unavailable, say exactly why in the final response; do not claim the generated tests build.
- Do not add GTEST_SKIP in this pass.

{build_guidance_block}

Deliverables:
- Updated existing test `.cpp` file(s)
- Updated `.gme-agent/generated_tests.md`
- Updated `.gme-agent/generated_tests.json`
- A concise final summary listing newly added tests, APIs covered, the exact suggested `--gtest_filter`, the build command/result, and any requested-count shortfall with reasons.
"""


def _build_guidance_block(module_path: str, build_guidance: str | None) -> str:
    if build_guidance:
        return build_guidance.strip()
    develop_option, test_option = _module_cmake_options(module_path)
    return f"""Build validation commands:
- Use these default commands when the GME Test Agent prompt does not provide task-specific commands.
- Build directory: `{{worktree}}/build/vscode`
- Configure:
  `cmake -S {{worktree}} -B {{worktree}}/build/vscode -G "Visual Studio 17 2022" -A x64 -DBUILD_ALL_MODULE=OFF -DBUILD_DEMO=OFF -DBUILD_BENCHTEST=OFF -DBUILD_TEST=ON -DBUILD_FORMAT=OFF {develop_option} {test_option}`
- Build:
  `cmake --build {{worktree}}/build/vscode --config Debug --target tests --parallel`
- Optional focused run after a successful build, using the exact filter from `.gme-agent/generated_tests.json`:
  `{{worktree}}/build/vscode/Debug/tests.exe --gtest_filter=<exact-generated-filter>`"""


def _module_cmake_options(module_path: str) -> tuple[str, str]:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in module_path).strip("_").upper()
    if not normalized:
        return "", ""
    return f"-DDEVELOP_{normalized}=ON", f"-DTEST_{normalized}=ON"
