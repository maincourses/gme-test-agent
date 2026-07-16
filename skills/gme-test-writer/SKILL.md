---
name: gme-test-writer
description: 基于 module_test_profile.md 和 acis_interface_candidates.md，为用户选择的 GME 模块在现有 tests/gme 测试文件中插入 GME vs ACIS GoogleTest 对比测试。
---

# GME 测试编写

## 任务

基于以下材料生成测试：

- `.gme-agent/module_test_profile.md`
- `.gme-agent/acis_interface_candidates.md`
- `tests/gme/src/<module>/` 下已有测试
- `tests/gme/include/tests/<module>/` 下已有 helper

生成测试必须插入最相关的已有 `.cpp` 文件中，不要创建新的 generated test 文件。

示例归类：

- law 相关 kernapi，如 `api_make_cubic`、`api_make_quintic`、`api_ndifferentiate_law`，放到 `tests/gme/src/laws/kernel_kernapi_test.cpp` 附近。
- `api_str_to_law` 放到 `law_api_str_to_law_test.cpp`。
- `api_nsolve_laws`、`api_nroots_of_law` 放到对应 solve equation 文件。
- law 类、表达式、evaluate、deriv 等放到 `law_main_law_test.cpp` 或已有更匹配文件。
- base 的 box/par_box/vector/math 测试放到 base 下对应已有文件。

## 硬性规则

- 只允许修改 `tests/gme` 下相关测试 `.cpp` 文件，以及 `.gme-agent/generated_tests.md`、`.gme-agent/generated_tests.json`。
- 不要修改生产代码、ACIS 代码、CMake 文件、子仓库指针或无关测试。
- 结束前必须清理目标测试仓库和 `.gme-agent` 之外的临时文件；如果 worktree 根目录出现 `timer_res_.csv`、日志、缓存或其他测试运行副产物，删除它们，不要留下越界改动。
- 不要创建 `gme_agent_<module>_generated_test.cpp`。
- 不要创建任何新的测试 `.cpp`，除非目标模块确实没有任何可用测试文件且用户明确同意。
- 不要新增 helper 函数、helper 类、helper 头文件、宏或共享工具。
- 每个新增测试的 setup、输入构造、ACIS/GME 调用、比较、清理都必须写在该 `TEST_F` 的函数体内。
- 新增测试必须写成 `TEST_F`，不要写裸 `TEST`。
- 复用目标文件已有 include、fixture、初始化流程、容差和对象生命周期写法。
- 优先使用目标文件已有 suite/fixture；不要为了 AI 测试创建新的 fixture。
- 不要调用 private/protected 成员；不要只因为头文件里有声明就假设 API 可链接，优先参考已有测试或源码确认该接口能在测试目标中使用。
- 完成编辑后必须构建测试目标。若构建失败来自本次生成的测试，先修测试；修不稳就删除对应测试，并同步更新 `.gme-agent/generated_tests.md` 和 `.gme-agent/generated_tests.json`。
- 每次修复、删除或补充生成测试后，必须重新构建。持续执行“构建 -> 修复/删除/补充 -> 再构建”的循环，直到构建通过，或确认没有可安全生成且可构建的测试。
- 如果删除坏测试导致本次生成数量低于用户要求，必须补充新的可构建测试，并再次构建验证。只有在没有安全可测 API、接口不可链接、只能访问非公开成员或缺少可靠对比方式时，才允许少于用户要求，并在最终回复说明缺口原因。
- 构建修复只允许改本次生成的测试和 `.gme-agent` 清单，不要改生产代码、ACIS 代码、CMake、公共 helper 或无关测试。
- 遇到 unresolved external/LNK2019 时删除或替换对应测试；遇到 private/protected 访问错误时改用公开行为检查。
- 第一次生成测试时不要添加 `GTEST_SKIP`。

## 中文注释与编码保护

- 新增代码注释必须使用简洁、准确的中文。
- 修改目标 C++ 文件时，必须保持文件现有编码、BOM 状态和换行符；不得转换文件编码，不得新增或删除 BOM，不得因为添加测试而重写整个文件。
- 禁止使用 PowerShell `Get-Content`、`Set-Content`、`Out-File` 读取或重写 C++ 源文件。必须使用能够保持原始字节编码和换行符的局部补丁方式修改源码。
- 不得修改、复制或重新编码已有中文注释。新增测试不得导致目标 `TEST_F` 之外的已有注释发生变化。
- `.gme-agent` 目录中的 JSON 文件必须使用 UTF-8 无 BOM；Markdown 文件使用 UTF-8，并且不得把 BOM 要求从 C++ 源文件扩展到 JSON。
- 修改完成后必须检查 `git diff`，确认只有目标测试发生预期变化，并满足以下条件：
  - 已有中文注释没有变化；
  - 新增中文注释显示正常；
  - 不存在 `�` 或明显乱码；
  - 目标文件的 BOM 状态和换行符没有变化。
- 如果发现乱码、非预期的整文件注释变化、BOM 变化或换行符变化，必须先恢复受影响文件，再以局部补丁方式重新添加测试；不得继续构建或保留损坏文件。

## 构建命令

优先使用用户提示词中的 “Build validation commands from the GME Test Agent settings”。如果提示词没有给出任务专用命令，在当前 GME worktree 根目录使用：

```powershell
cmake -S . -B build/vscode -G "Visual Studio 17 2022" -A x64 -DBUILD_ALL_MODULE=OFF -DBUILD_DEMO=OFF -DBUILD_BENCHTEST=OFF -DBUILD_TEST=ON -DBUILD_FORMAT=OFF -DDEVELOP_<MODULE>=ON -DTEST_<MODULE>=ON
cmake --build build/vscode --config Debug --target tests --parallel
```

`<MODULE>` 是模块名大写，非字母数字替换为 `_`，例如 `laws` 使用 `-DDEVELOP_LAWS=ON -DTEST_LAWS=ON`，`base` 使用 `-DDEVELOP_BASE=ON -DTEST_BASE=ON`。

构建通过后，可以用 `.gme-agent/generated_tests.json` 里的精确 filter 运行新增测试：

```powershell
build/vscode/Debug/tests.exe --gtest_filter=<exact-generated-filter>
```

## 命名规则

使用目标文件已有 suite。

例如目标文件已有：

```cpp
TEST_F(Laws_KernapiTest, ApiMakeCubicTest1) {
}
```

则新测试也应该使用：

```cpp
TEST_F(Laws_KernapiTest, ApiMakeCubicAsymmetricEndpointSlopes) {
    // All setup, calls, checks, and cleanup stay inside this body.
}
```

测试名要描述清楚覆盖点，避免使用 `GeneratedCase1` 这类名字。

## 生成测试清单

必须写入 `.gme-agent/generated_tests.json`，格式必须是合法 JSON：

```json
{
  "tests": [
    {
      "file": "tests/gme/src/laws/kernel_kernapi_test.cpp",
      "suite": "Laws_KernapiTest",
      "name": "ApiMakeCubicAsymmetricEndpointSlopes",
      "api": "api_make_cubic",
      "anchor": "ApiMakeCubicTest3"
    }
  ]
}
```

`file` 可以写 superproject 相对路径，也可以写目标测试仓库内的 `src/...` 相对路径。推荐写完整的 `tests/gme/src/...`。

同时更新 `.gme-agent/generated_tests.md`：

```markdown
# Generated Tests: <module>

## Modified Files

## Generated Test Cases

## Suggested GTest Filter

## APIs Covered

## Notes
```

`Suggested GTest Filter` 必须使用精确测试名，例如：

```text
Laws_KernapiTest.ApiMakeCubicAsymmetricEndpointSlopes:Laws_KernapiTest.ApiMakeQuinticMixedSecondDerivatives
```
