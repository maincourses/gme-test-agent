---
name: gme-module-test-analyzer
description: 分析用户选择的 GME 模块已有测试。用于 GME 测试 Agent 在生成新测试之前，总结测试目录、fixture、helper、已覆盖 API、命名风格和覆盖空白。
---

# GME 模块测试分析

## 任务

分析当前模块已有测试，并写入 `.gme-agent/module_test_profile.md`。

优先读取这些位置，如果存在：

- `tests/gme/src/<module>/`
- `tests/gme/include/tests/<module>/`
- `tests/gme` 下相关 `CMakeLists.txt` 或测试注册文件

本步骤只做分析，不修改测试代码或生产代码。

## 需要提取的信息

记录以下内容：

- 已有测试文件及用途
- 常见 include 和 include 风格
- fixture、helper、对象生命周期包装、容差和比较工具
- 已有 GME vs ACIS 对比模式
- 已覆盖的 API 和行为类型
- suite/test 命名习惯
- 不需要新增基础设施即可扩展的覆盖空白

## Markdown 格式

写入 `.gme-agent/module_test_profile.md`，结构如下：

```markdown
# Module Test Profile: <module>

## Existing Test Files

## Common Includes And Helpers

## Existing Comparison Patterns

## Covered APIs

## Coverage Gaps

## Recommended Generated Test File

## Recommended Suite And Filter
```

推荐生成文件必须是：

```text
tests/gme/src/<module>/gme_agent_<module>_generated_test.cpp
```

推荐 suite 必须是：

```text
<ModuleCapitalized>_GmeAgentGeneratedTest
```
