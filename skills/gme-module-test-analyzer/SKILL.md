---
name: gme-module-test-analyzer
description: 分析用户选择的 GME 模块已有测试。用于 GME 测试 Agent 在生成新测试之前，总结测试目录、fixture、helper、已覆盖 API、命名风格、文件归属和覆盖空白。
---

# GME 模块测试分析

## 任务

分析当前模块已有测试，并写入 `.gme-agent/module_test_profile.md`。

优先读取这些位置：

- `tests/gme/src/<module>/`
- `tests/gme/include/tests/<module>/`
- `tests/gme` 下相关 `CMakeLists.txt` 或测试注册文件

本步骤只做分析，不修改测试代码或生产代码。

## 需要提取的信息

记录以下内容：

- 已有测试文件及用途
- 每个测试文件主要覆盖的 API、类或行为类型
- 常见 include 和 include 风格
- fixture、helper、对象生命周期包装、容差和比较工具
- 已有 GME vs ACIS 对比模式
- 已覆盖 API 和行为类型
- suite/test 命名习惯
- 新测试应该插入哪个已有 `.cpp` 文件
- 不需要新增 helper 即可扩展的覆盖空白

## 文件归属建议

生成测试时必须优先插入已有 `.cpp`。分析报告中要给出“API/行为 -> 推荐文件”的映射。

示例：

- `api_make_cubic`、`api_make_quintic`、`api_ndifferentiate_law` -> `tests/gme/src/laws/kernel_kernapi_test.cpp`
- `api_str_to_law` -> `tests/gme/src/laws/law_api_str_to_law_test.cpp`
- `api_nsolve_laws` -> `tests/gme/src/laws/law_api_nsolve_laws_test.cpp`
- law 类 evaluate/deriv/deep_copy -> `tests/gme/src/laws/law_main_law_test.cpp`
- par_box 行为 -> `tests/gme/src/base/par_box_test.cpp`

## Markdown 格式

写入 `.gme-agent/module_test_profile.md`，结构如下：

```markdown
# Module Test Profile: <module>

## Existing Test Files

## File Ownership Map

## Common Includes And Helpers

## Existing Comparison Patterns

## Covered APIs

## Coverage Gaps

## Recommended Insertion Points

## Recommended Exact GTest Filters
```

不要推荐 `gme_agent_<module>_generated_test.cpp`。
