---
name: gme-test-generation
description: 协调 GME 模块测试生成流程。用于 GME 测试 Agent 要求 Codex 分析已有模块测试、分析 GME/ACIS 可对比接口，并在 tests/gme 现有测试文件中插入 GoogleTest 对比测试。
---

# GME 测试生成协调器

## 目标

为用户选择的 GME 模块生成聚焦的 GoogleTest 测试，用来对比 GME 和 ACIS 行为。你工作在已经准备好的 GME superproject worktree 中。后端会准备 `tests/gme`、`module/<module>` 和 `_deps/acis`；其他无关模块源码可能不存在。

## 必须按顺序使用的技能

1. 使用 `gme-module-test-analyzer` 分析已有测试，写入 `.gme-agent/module_test_profile.md`。
2. 使用 `gme-acis-interface-analyzer` 分析 GME 和 ACIS 可对比接口，写入 `.gme-agent/acis_interface_candidates.md`。
3. 使用 `gme-test-writer` 将新测试插入最相关的现有 `.cpp` 文件，并写入 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。

如果 `.gme-agent/` 不存在，先创建它。这些文件只是本次任务的工作笔记和机器可读清单，不是要提交到 PR 的源代码。

## 硬性边界

- 只允许修改配置的测试仓库，通常是 `tests/gme`，以及 `.gme-agent/*.md`、`.gme-agent/generated_tests.json` 工作笔记。
- 不要修改 `module/<module>`、`_deps/acis`、`include`、`module_lib`、`.gitmodules`、构建文件或子仓库指针。
- 结束前检查 worktree 根目录和目标测试仓库以外的路径；如果出现临时副产物或空文件，例如 `timer_res_.csv`、日志、缓存、测试运行产物，必须删除。最终只能留下目标测试仓库和 `.gme-agent` 的改动。
- 不要创建 `gme_agent_<module>_generated_test.cpp` 或任何新的 generated `.cpp`。
- 新测试必须按已有测试文件职责归类，插入对应已有 `.cpp`。
- 不同类型测试放到不同的对应 `.cpp`，不要把所有测试塞进一个文件。
- 不要新增 helper 函数、helper 类、helper 头文件、宏或共享工具。
- 每个新增测试的所有逻辑必须写在单个 `TEST_F` 函数体内。
- 新增测试必须写成 `TEST_F`，不要写裸 `TEST`。
- 必须复用 `tests/gme/src/<module>/` 和 `tests/gme/include/tests/<module>/` 中已有 fixture、include 风格和比较方式。
- 生成某个接口的测试前，必须使用完整 `UniqueSymbol`、类名和方法名搜索目标测试仓库，定位所有对应的已有测试。
- 若存在对应测试，必须在 `.gme-agent/module_test_profile.md` 中逐条总结其测试名、输入和断言，并且只生成尚未覆盖的行为。
- 结束前必须先构建测试目标。如果构建失败是由本次生成的测试导致的，必须先修正这些测试；修不稳的测试必须删除，并同步更新 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`，不能把不可构建的测试留给 runner。
- 每次修复、删除或补充生成测试后，必须重新构建。持续执行“构建 -> 修复/删除/补充 -> 再构建”的循环，直到构建通过，或确认已经没有可安全生成且可构建的测试。
- 如果删除坏测试导致本次生成数量低于用户要求，必须补充新的可构建测试，并再次构建验证。只有在没有安全可测 API、接口不可链接、只能访问非公开成员或缺少可靠对比方式时，才允许少于用户要求，并在最终回复说明缺口原因。
- 构建修复只能改本次生成的测试代码和 `.gme-agent` 清单，不要通过修改 GME/ACIS 源码、CMake、公共 helper 或无关测试来让生成测试通过构建。
- 如果出现 unresolved external/LNK2019，说明该 API 当前不可链接使用，删除或替换对应生成测试；如果出现 private/protected 访问错误，改用公开行为验证，不能访问非公开成员。
- 构建成功后，必须使用 `.gme-agent/generated_tests.json` 中的准确 filter 实际运行本次所有生成测试；仅构建通过不算完成。异常退出或没有标准 GTest 结果的测试必须先分析、修正并重新验证。
- 第一次生成测试时不要添加 `GTEST_SKIP`。runner 执行测试并提供失败日志后，才进入 skip 标记步骤。

## 中文注释与编码保护

- 第一次修改每个目标 C++ 文件前，必须先按原始字节检查并记录该文件的编码、是否带 UTF-8 BOM，以及换行符是 CRLF 还是 LF；后续所有编辑都必须保持这三个属性不变。
- 只能使用 `apply_patch` 或等价的最小范围局部补丁插入新的 `TEST_F`。禁止读取后重新写回整个文件，禁止整文件替换，禁止为了添加测试运行会重写整个文件的脚本或格式转换命令。
- 修改目标 C++ 文件时，不得转换文件编码，不得新增或删除 BOM，不得把 CRLF 转为 LF，也不得把 LF 转为 CRLF，不得产生混合换行。
- 禁止使用 PowerShell `Get-Content`、`Set-Content`、`Out-File` 读取或重写 C++ 源文件。不得使用未显式保留原始编码、BOM 和换行符的 Python、Node.js 或其他脚本重写 C++ 文件。
- 不得修改、复制或重新编码已有中文注释。新增测试不得导致目标 `TEST_F` 之外的已有注释发生变化。
- `.gme-agent` 目录中的 JSON 文件必须使用 UTF-8 无 BOM；Markdown 文件使用 UTF-8，并且不得把 BOM 要求从 C++ 源文件扩展到 JSON。
- 修改完成后必须同时检查 `git diff` 和目标文件的原始字节格式。不能只依赖 `git diff`，因为 Git 可能隐藏 CRLF/LF 的整文件变化。必须确认只有目标测试发生预期变化，并满足以下条件：
  - 已有中文注释没有变化；
  - 不存在 `�` 或明显乱码；
  - 目标文件的 BOM 状态和换行符没有变化。
- 如果发现乱码、非预期的整文件注释变化、BOM 变化或换行符变化，必须先从 Git 恢复受影响文件，再以最小范围局部补丁重新添加本次测试；禁止通过整文件转码、统一换行、添加 BOM 或删除 BOM 来修补，且不得继续构建或保留格式异常的文件。

## 构建命令

用户提示词如果提供了 “Build validation commands from the GME Test Agent settings”，必须优先使用那里给出的 configure/build 命令。没有提供时，在当前 GME worktree 根目录使用默认命令：

```powershell
cmake -S . -B build/vscode -G "Visual Studio 17 2022" -A x64 -DBUILD_ALL_MODULE=OFF -DBUILD_DEMO=OFF -DBUILD_BENCHTEST=OFF -DBUILD_TEST=ON -DBUILD_FORMAT=OFF -DDEVELOP_<MODULE>=ON -DTEST_<MODULE>=ON
cmake --build build/vscode --config Debug --target tests --parallel
```

`<MODULE>` 是模块名大写，非字母数字替换为 `_`，例如 `laws` 使用 `-DDEVELOP_LAWS=ON -DTEST_LAWS=ON`，`base` 使用 `-DDEVELOP_BASE=ON -DTEST_BASE=ON`。

构建通过后，必须用 `.gme-agent/generated_tests.json` 中的精确 filter 运行本次所有新增测试：

```powershell
build/vscode/Debug/tests.exe --gtest_filter=<exact-generated-filter>
```

## 输出要求

最终回复必须简洁列出：

- 修改的文件
- 生成的测试 suite/test name
- 建议的精确 `--gtest_filter`
- 覆盖的 API
- 已执行的构建命令和结果；如果本机无法构建，必须明确说明原因，不能声称构建通过
- 如果未达到用户要求的测试数量，说明最终数量、删除/未补足的测试和原因
- 有哪些假设，以及哪些 API 暂时没有测试

`.gme-agent/generated_tests.json` 必须包含本次任务所有新增测试：

```json
{
  "tests": [
    {
      "file": "tests/gme/src/<module>/existing_test.cpp",
      "suite": "ExistingSuite",
      "name": "NewTestName",
      "api": "api_or_class_under_test",
      "anchor": "nearby existing test name"
    }
  ]
}
```
