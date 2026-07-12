from __future__ import annotations


def bug_fix_prompt(
    failure: dict,
    target_repo: str = "",
    *,
    test_repo: str = "",
    test_file: str = "",
    gtest_filter: str = "",
    before_output: str = "",
    configure_command: str = "",
    build_command: str = "",
    test_command: str = "",
) -> str:
    reproduce = failure.get("reproduce_command") or "运行该失败对应的目标 GTest filter。"
    target_rule = (
        f"- 生产代码只能修改 `{target_repo}`。可以读取 GME worktree 的其他内容作为上下文。\n"
        if target_repo
        else ""
    )
    fallback_filter = ".".join(part for part in [str(failure.get("test_suite") or ""), str(failure.get("test_name") or "")] if part)
    output_excerpt = (before_output or "").strip()
    if len(output_excerpt) > 4000:
        output_excerpt = output_excerpt[-4000:]
    return f"""你正在 GME 仓库中工作。

目标：
- 修复生产代码中这个已确认的 GME/ACIS 行为差异。
- 失败 ID：{failure.get("id")}
- 测试：{failure.get("test_suite")}.{failure.get("test_name")}
- 失败原因：{failure.get("reason")}
- GTest filter：{gtest_filter or fallback_filter}
- 已复制到当前修复 worktree 的复现测试文件：{test_file or test_repo}

复现命令：
```powershell
{reproduce}
```

当前修复 worktree 的验证命令：
```powershell
{configure_command or "# 配置命令由 GME Test Agent 管理。"}
{build_command or "# 构建命令由 GME Test Agent 管理。"}
{test_command or "# 测试命令由 GME Test Agent 管理。"}
```

修复前观察到的失败输出：
```text
{output_excerpt or "GME Test Agent 已在调用 Codex 前复现所选测试失败。"}
```

规则：
- GME superproject worktree 按模块准备；无关模块源码目录可能为空，并通过 `module_lib` 链接。
{target_rule.rstrip()}
- 不要修改 `include/` 路径下的文件。
- 不要修改 `{test_repo or "tests/gme"}` 或任何测试文件。复制过来的生成测试只作为验证输入。
- 不要添加 `GTEST_SKIP`、弱化断言、删除测试或修改期望值。
- 先根据失败测试和实现分析原因，再进行最小范围的生产代码修改。
- 修改必须尽可能小，并让该失败场景下的 GME 行为与 ACIS 一致。
- 修改代码后构建 tests 目标。
- 构建完成后，只运行给定的准确 GTest filter。
- 如果构建或所选测试仍失败，继续修复模块实现并重复构建/测试，直到通过，或能够明确说明为什么不存在安全的生产代码修复方案。

交付物：
- 只包含生产代码修改。
- 构建结果和所选测试结果摘要。
- 仍然存在的风险或后续事项。
"""
