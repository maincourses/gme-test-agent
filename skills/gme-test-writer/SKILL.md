---
name: gme-test-writer
description: 基于 module_test_profile.md 和 acis_interface_candidates.md 为用户选择的 GME 模块生成 GME vs ACIS GoogleTest 对比测试代码。
---

# GME 测试编写

## 任务

基于以下材料生成测试：

- `.gme-agent/module_test_profile.md`
- `.gme-agent/acis_interface_candidates.md`
- `tests/gme/src/<module>/` 下已有测试
- `tests/gme/include/tests/<module>/` 下已有 helper

所有生成测试必须写入：

```text
tests/gme/src/<module>/gme_agent_<module>_generated_test.cpp
```

如果文件已经存在，只能在这个文件里追加或更新测试。不要为同一模块创建第二个 AI 生成测试文件。

## 测试规则

- 只允许修改 `tests/gme` 测试文件和 `.gme-agent/generated_tests.md`。
- 不要修改已有人工测试，除非用户明确要求。
- 不要修改模块源码、ACIS 源码、测试外头文件、CMake 文件或子仓库指针。
- 必须复用已有 include 风格、fixture、对象生命周期包装、容差、初始化流程和比较 helper。
- 只生成确定性测试。
- 必须直接对比 GME 与 ACIS 行为。
- 优先生成小而聚焦的测试，不要写大范围随机测试。
- 第一次生成测试时不要添加 `GTEST_SKIP`。
- 如果某个 API 暂时不适合自动测试，在 `.gme-agent/generated_tests.md` 中说明原因。

## 命名契约

使用这个 suite：

```text
<ModuleCapitalized>_GmeAgentGeneratedTest
```

测试名必须描述清楚覆盖点，例如：

```cpp
TEST_F(Laws_GmeAgentGeneratedTest, StringExpressionEvaluationParity) {
}
```

建议 filter 必须是：

```text
<ModuleCapitalized>_GmeAgentGeneratedTest.*
```

## 生成测试报告

写入 `.gme-agent/generated_tests.md`，结构如下：

```markdown
# Generated Tests: <module>

## Modified Files

## Generated Suite

## Suggested GTest Filter

## Generated Test Cases

## APIs Covered

## Notes
```
