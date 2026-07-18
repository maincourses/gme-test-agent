from __future__ import annotations

from collections import defaultdict
from typing import Any


def test_generation_prompt(
    module: str,
    api_name: str,
    target_repo: str = "tests/gme",
    build_guidance: str | None = None,
    *,
    selected_interfaces: list[dict[str, Any]] | None = None,
    tests_per_interface: int = 1,
    extra_requirements: str = "",
) -> str:
    selected = list(selected_interfaces or [])
    target = f"目录中选中的 {len(selected)} 个接口" if selected else (api_name or "选中的 API")
    module_path = module.strip().replace("\\", "/").strip("/")
    build_guidance_block = _build_guidance_block(module_path, build_guidance)
    selection_block = _selection_block(
        selected,
        tests_per_interface,
        extra_requirements,
        continuation=False,
    )
    placement = (
        "只修改下方目录选择结果中列出的现有 `.cpp` 文件"
        if selected
        else f"将每个新测试插入 `{target_repo}/src/{module_path}/` 下职责最匹配的现有 `.cpp` 文件"
    )
    writer_step = (
        "使用 `gme-test-writer` skill 将要求的测试插入下方明确选中的文件"
        if selected
        else "使用 `gme-test-writer` skill 将新测试插入适当的现有 `.cpp` 文件"
    )
    return f"""你正在 GME 仓库中工作。

目标：
- 新增聚焦的 GoogleTest，用于对比 GME 与 ACIS 的行为。
- 目标模块：{module_path}
- 目标接口：{target}
- 允许编辑的目标测试仓库：`{target_repo}`
- 测试放置规则：{placement}。
- 生成测试清单：`.gme-agent/generated_tests.json`

{selection_block}

必须按阶段执行：
1. 使用 `gme-module-test-analyzer` skill 分析现有测试文件，并写入 `.gme-agent/module_test_profile.md`。
2. 使用 `gme-acis-interface-analyzer` skill 校验要求的 GME 与 ACIS 接口，包括 `_deps/acis/R35`，并写入 `.gme-agent/acis_interface_candidates.md`。
3. {writer_step}，并写入 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。

如果 `.gme-agent/` 不存在，先创建它。`.gme-agent/*.md` 和 `.gme-agent/generated_tests.json` 是本任务的工作笔记，不要放到 `{target_repo}` 下，也不要把它们当作测试源文件。

规则：
- GME superproject worktree 按模块准备：当前模块源码 `{module_path}`、测试仓库、`include/`、`module_lib/` 和 `_deps/acis/` 可用；无关模块源码目录可能为空。
- 测试代码只能修改 `{target_repo}`。唯一允许的非测试代码改动是 `.gme-agent/module_test_profile.md`、`.gme-agent/acis_interface_candidates.md`、`.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
- 本任务只生成测试。不要修改 `module/` 或 `include/` 中的生产代码。
- 上方列出目录选择接口时，不得修改所选文件之外的测试 `.cpp`，也不得用未选择的 API 替换所选 API。
- 结束前删除 `{target_repo}` 和 `.gme-agent` 之外的临时文件，例如 `timer_res_.csv`、日志、缓存或测试运行副产物。最终 worktree 不得包含越界改动。
- 不要创建 `gme_agent_<module>_generated_test.cpp` 或其他新的 generated test `.cpp`。
- 不要新增 helper 函数、helper 类、helper 头文件、宏或共享工具。每个测试的构造、转换、比较和清理逻辑必须直接写在各自的 `TEST_F` 函数体内。
- 生成的测试必须使用 `TEST_F`，不要使用独立的 `TEST`。
- 复用目标文件已有的 fixture/suite。只有目标文件没有可用 fixture 且测试无法编译时，才允许创建新 fixture。
- 生成某个接口的测试前，必须使用完整 `UniqueSymbol`、类名和方法名搜索目标测试仓库，定位所有对应的已有测试；不得只按文件名或模糊 API 名判断是否已有覆盖。
- 若存在对应测试，必须在 `.gme-agent/module_test_profile.md` 中逐条总结其测试名、输入和断言，并且只生成这些已有测试尚未覆盖的行为。
- 每个测试应放在相同 API、类型或行为的最近现有测试附近。
- 遵循目标文件已有的 include 风格、命名、初始化、容差、对象生命周期和 ACIS/GME 对比方式。
- 优先编写小型、确定性的测试，不要编写宽泛的随机测试。
- 不要调用 private/protected 成员。不要因为头文件存在声明就假设 API 可链接；优先使用已有测试采用的 API，或通过实现/导出符号确认。
- 目录选择指定数量时，每个选中接口都必须生成指定数量的测试；否则遵循用户要求，或根据分析选择少量有价值的场景。
- 对比失败本身有价值，但测试代码必须能够编译且适合审查。
- 最终回复前，必须使用当前 worktree 配置或可发现的构建命令构建测试目标。若构建失败由本次生成测试导致，先修复测试；若只修改测试仍无法稳定构建，删除该测试并同步更新 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
- 每次修复、删除或替换生成测试后都必须重新构建。持续执行“构建 -> 修复/删除/替换 -> 重新构建”，直到构建通过，或确认没有可安全生成且可构建的测试。
- 删除无效测试导致数量少于用户要求时，必须补充新的可构建测试并再次构建。只有不存在安全可对比 API、API 不可链接、只能访问 private/protected 成员或缺少可靠 GME/ACIS 对比方式时，才允许最终数量不足，并在最终回复中说明原因。
- 构建失败修复只能修改本次生成的测试和 `.gme-agent` 工作笔记。不得为了让测试通过构建而修改 GME 生产代码、ACIS 代码、CMake 文件、共享 helper 或无关测试。
- 遇到 unresolved external/LNK2019，视为该 API 无法在当前测试目标中链接，删除或替换该测试。遇到 private/protected 访问错误，视为测试无效，改用公开行为验证。
- 构建成功后，必须使用 `.gme-agent/generated_tests.json` 生成的准确 GTest filter 实际运行本次所有生成测试；仅构建通过不算完成。若测试异常退出或未产生 `OK`、`FAILED`、`SKIPPED` 结果，必须分析并修正无效测试后重新构建、重新运行。
- 如果本地构建工具不可用，在最终回复中准确说明原因，不得声称构建通过。
- 第一次生成时不要添加 `GTEST_SKIP`。runner 会先执行测试，再针对真实差异请求受控的 skip。

{build_guidance_block}

`.gme-agent/generated_tests.json` 必须是符合以下结构的合法 JSON：
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

交付物：
- `.gme-agent/module_test_profile.md`
- `.gme-agent/acis_interface_candidates.md`
- `.gme-agent/generated_tests.md`
- `.gme-agent/generated_tests.json`
- `{target_repo}/src/{module_path}/` 下已修改的现有测试 `.cpp` 文件
- 简洁的最终总结：列出修改文件、生成测试、覆盖 API、准确建议的 `--gtest_filter`、构建命令与结果，以及测试数量不足及其原因。
"""


def continue_test_generation_prompt(
    module: str,
    api_name: str,
    target_repo: str = "tests/gme",
    build_guidance: str | None = None,
    *,
    selected_interfaces: list[dict[str, Any]] | None = None,
    tests_per_interface: int = 1,
    extra_requirements: str = "",
) -> str:
    selected = list(selected_interfaces or [])
    target = f"本次新选择的 {len(selected)} 个目录接口" if selected else (api_name or "继续扩展选中模块的测试覆盖")
    module_path = module.strip().replace("\\", "/").strip("/")
    build_guidance_block = _build_guidance_block(module_path, build_guidance)
    selection_block = _selection_block(
        selected,
        tests_per_interface,
        extra_requirements,
        continuation=True,
    )
    return f"""你正在继续一个已有的 GME Test Agent 测试生成任务。

目标：
- 继续扩展用于对比 GME 与 ACIS 行为的聚焦 GoogleTest 覆盖。
- 目标模块：{module_path}
- 本次补充要求：{target}
- 允许编辑的目标测试仓库：`{target_repo}`
- 测试放置规则：{"只修改下方本次新选择的现有 `.cpp` 文件" if selected else f"将每个新测试插入 `{target_repo}/src/{module_path}/` 下职责最匹配的现有 `.cpp` 文件"}。
- 生成测试清单：`.gme-agent/generated_tests.json`

{selection_block}

必须执行的流程：
1. 如果存在，读取 `.gme-agent/module_test_profile.md`、`.gme-agent/acis_interface_candidates.md`、`.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
2. 使用每个接口的完整 `UniqueSymbol`、类名和方法名重新搜索目标测试仓库；若存在对应测试，在 `.gme-agent/module_test_profile.md` 中逐条总结其测试名、输入和断言，避免重复已有行为。
3. 将新的聚焦测试添加到适当的现有 `.cpp` 文件，不要创建 generated test 文件。
4. 更新 `.gme-agent/generated_tests.json`，使其包含本任务之前生成和本次新增的全部测试。
5. 更新 `.gme-agent/generated_tests.md`，记录新测试和准确的 GTest filter 变化。只有新分析确实改变内容时，才更新其他 `.gme-agent/*.md` 工作笔记。

规则：
- 复用现有 worktree。
- 测试代码只能修改 `{target_repo}`。唯一允许的非测试代码改动是 `.gme-agent/module_test_profile.md`、`.gme-agent/acis_interface_candidates.md`、`.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
- 本任务不要修改 `module/` 或 `include/` 中的生产代码。
- 对于目录选择接口，本次新增测试只能写入上方列出的选中文件，不得替换成未选择的 API；保留本任务之前的 manifest 条目。
- 结束前删除 `{target_repo}` 和 `.gme-agent` 之外的临时文件，例如 `timer_res_.csv`、日志、缓存或测试运行副产物。最终 worktree 不得包含越界改动。
- 不要创建 `gme_agent_<module>_generated_test.cpp` 或其他新的 generated test `.cpp`。
- 不要新增 helper 函数、helper 类、helper 头文件、宏或共享工具。每个测试的构造、转换、比较和清理逻辑必须直接写在各自的 `TEST_F` 函数体内。
- 生成的测试必须使用 `TEST_F`，不要使用独立的 `TEST`。
- 复用目标文件已有的 fixture/suite。只有目标文件没有可用 fixture 且测试无法编译时，才允许创建新 fixture。
- 生成某个接口的测试前，必须使用完整 `UniqueSymbol`、类名和方法名搜索目标测试仓库，定位所有对应的已有测试；不得只按文件名或模糊 API 名判断是否已有覆盖。
- 若存在对应测试，只生成这些已有测试尚未覆盖的行为。
- 每个测试应放在相同 API、类型或行为的最近现有测试附近。
- 优先编写小型、确定性的 GME/ACIS 对比测试，并覆盖已有测试尚未覆盖的场景。
- 不要调用 private/protected 成员。不要因为头文件存在声明就假设 API 可链接；优先使用已有测试采用的 API，或通过实现/导出符号确认。
- 最终回复前，必须使用当前 worktree 配置或可发现的构建命令构建测试目标。若构建失败由本次生成测试导致，先修复测试；若只修改测试仍无法稳定构建，删除该测试并同步更新 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
- 每次修复、删除或替换生成测试后都必须重新构建。持续执行“构建 -> 修复/删除/替换 -> 重新构建”，直到构建通过，或确认没有可安全生成且可构建的测试。
- 删除无效测试导致数量少于用户要求时，必须补充新的可构建测试并再次构建。只有不存在安全可对比 API、API 不可链接、只能访问 private/protected 成员或缺少可靠 GME/ACIS 对比方式时，才允许最终数量不足，并在最终回复中说明原因。
- 构建失败修复只能修改本次生成的测试和 `.gme-agent` 工作笔记。不得为了让测试通过构建而修改 GME 生产代码、ACIS 代码、CMake 文件、共享 helper 或无关测试。
- 遇到 unresolved external/LNK2019，视为该 API 无法在当前测试目标中链接，删除或替换该测试。遇到 private/protected 访问错误，视为测试无效，改用公开行为验证。
- 构建成功后，必须使用 `.gme-agent/generated_tests.json` 生成的准确 GTest filter 实际运行本次所有生成测试；仅构建通过不算完成。若测试异常退出或未产生 `OK`、`FAILED`、`SKIPPED` 结果，必须分析并修正无效测试后重新构建、重新运行。
- 如果本地构建工具不可用，在最终回复中准确说明原因，不得声称构建通过。
- 本次扩展不要添加 `GTEST_SKIP`。

{build_guidance_block}

交付物：
- 已更新的现有测试 `.cpp` 文件
- 已更新的 `.gme-agent/generated_tests.md`
- 已更新的 `.gme-agent/generated_tests.json`
- 简洁的最终总结：列出本次新增测试、覆盖 API、准确建议的 `--gtest_filter`、构建命令与结果，以及测试数量不足及其原因。
"""


def _selection_block(
    interfaces: list[dict[str, Any]],
    tests_per_interface: int,
    extra_requirements: str,
    *,
    continuation: bool,
) -> str:
    if not interfaces:
        return "结构化目录选择：未提供；按照上方自由文本目标执行。"

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for interface in interfaces:
        grouped[str(interface.get("target_file") or "")].append(interface)
    requested_count = len(interfaces) * tests_per_interface
    lines = [
        "结构化目录选择（权威输入）：",
        f"- 每个选中接口准确生成 {tests_per_interface} 个新测试，共生成 {requested_count} 个新测试。",
        "- 每个测试都必须调用并对比该选中接口的 ACIS 与 GME 行为。",
        "- 每个 `TEST_F` 函数体第一行必须写 `RecordProperty(\"UniqueSymbol\", \"...\")`，并使用下方给出的准确符号。",
        "- 必须使用列出的现有 fixture/suite 和目标文件，不得将接口移动到其他文件。",
        "- 不得为列表之外的接口新增测试。若某个选中接口无法安全测试，应报告该接口的准确缺口，不得替换成其他接口。",
    ]
    if continuation:
        lines.append("- 这些接口只用于本次扩展；保留之前生成的所有测试和 manifest 条目不变。")
    for file_path, file_interfaces in grouped.items():
        lines.append(f"- 目标文件：`{file_path}`")
        for interface in file_interfaces:
            lines.append(
                "  - "
                f"接口 ID `{interface.get('id')}`；"
                f"fixture `{interface.get('test_suite')}`；"
                f"UniqueSymbol `{interface.get('unique_symbol')}`"
            )
    requirements = extra_requirements.strip()
    lines.append(f"- 补充要求：{requirements}" if requirements else "- 补充要求：无。")
    return "\n".join(lines)


def _build_guidance_block(module_path: str, build_guidance: str | None) -> str:
    if build_guidance:
        return build_guidance.strip()
    develop_option, test_option = _module_cmake_options(module_path)
    return f"""构建验证命令：
- GME Test Agent 未提供任务专用命令时，使用以下默认命令。
- 构建目录：`{{worktree}}/build/vscode`
- 配置：
  `cmake -S {{worktree}} -B {{worktree}}/build/vscode -G "Visual Studio 17 2022" -A x64 -DBUILD_ALL_MODULE=OFF -DBUILD_DEMO=OFF -DBUILD_BENCHTEST=OFF -DBUILD_TEST=ON -DBUILD_FORMAT=OFF {develop_option} {test_option}`
- 构建：
  `cmake --build {{worktree}}/build/vscode --config Debug --target tests --parallel`
- 构建成功后，必须使用 `.gme-agent/generated_tests.json` 中的准确 filter 运行本次所有生成测试；仅构建通过不算完成：
  `{{worktree}}/build/vscode/Debug/tests.exe --gtest_filter=<exact-generated-filter>`"""


def _module_cmake_options(module_path: str) -> tuple[str, str]:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in module_path).strip("_").upper()
    if not normalized:
        return "", ""
    return f"-DDEVELOP_{normalized}=ON", f"-DTEST_{normalized}=ON"
