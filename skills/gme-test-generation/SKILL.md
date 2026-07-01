---
name: gme-test-generation
description: 协调 GME 模块测试生成流程。用于 GME 测试 Agent 要求 Codex 分析已有模块测试、分析 GME/ACIS 可对比接口，并在 tests/gme 下生成 GoogleTest 对比测试时。
---

# GME 测试生成协调器

## 目标

为用户选择的 GME 模块生成聚焦的 GoogleTest 测试，用来对比 GME 和 ACIS 的行为。你工作在已经准备好的 GME superproject worktree 中。后端会准备 `tests/gme`、`module/<module>` 和 `_deps/acis`；其他无关模块源码可能不存在。

## 必须按顺序使用的技能

严格按用户提示词要求的顺序执行：

1. 使用 `gme-module-test-analyzer` 分析已有测试，写入 `.gme-agent/module_test_profile.md`。
2. 使用 `gme-acis-interface-analyzer` 分析 GME 和 ACIS 可对比接口，写入 `.gme-agent/acis_interface_candidates.md`。
3. 使用 `gme-test-writer` 生成测试代码，并写入 `.gme-agent/generated_tests.md`。

如果 `.gme-agent/` 不存在，先创建它。这些 Markdown 文件只是本次任务的工作笔记，不是要提交到 PR 的源码。

## 硬性边界

- 只允许修改配置的测试仓库，通常是 `tests/gme`，以及 `.gme-agent/*.md` 工作笔记。
- 不要修改 `module/<module>`、`_deps/acis`、`include`、`module_lib`、`.gitmodules`、构建文件或子仓库指针。
- 不要修改已有人工测试 `.cpp`，除非用户明确要求。
- 同一模块的 AI 生成测试只能放在一个文件中：`tests/gme/src/<module>/gme_agent_<module>_generated_test.cpp`。
- 必须复用 `tests/gme/src/<module>/` 和 `tests/gme/include/tests/<module>/` 中已有 helper、fixture、include 风格和比较方式。
- 第一次生成测试时不要添加 `GTEST_SKIP`。runner 执行测试并提供失败日志后，才进入 skip 标记步骤。

## 输出要求

最终回复必须简洁列出：

- 修改的文件
- 生成的测试 suite
- 生成的测试名
- 建议的 `--gtest_filter`
- 有哪些假设，以及哪些 API 暂时没有测试

