from __future__ import annotations


def skip_known_failure_prompt(test_log: str, failures: list[dict], target_repo: str = "tests/gme", allowed_files: list[str] | None = None) -> str:
    failure_lines = "\n".join(
        f"- 失败ID={f.get('id')} 测试={f.get('test_suite')}.{f.get('test_name')} 文件={f.get('file')} 行号={f.get('line')} 原因={f.get('reason')}"
        for f in failures
    )
    allowed_file_lines = "\n".join(f"- `{path}`" for path in (allowed_files or [])) or "- `.gme-agent/generated_tests.json` 中列出的文件"
    return f"""新生成的 GME/ACIS 对比测试出现失败。

任务：
- 检查测试输出。
- 只为下方列出的失败生成测试添加已知失败 skip，使默认 CI 能够通过。
- 只能修改 `{target_repo}` 下的文件。可以读取 GME worktree 的其他内容作为上下文。
- 不要新增或使用 helper 头文件。
- 在每个失败测试函数体靠前位置直接使用 GoogleTest skip：
  `GTEST_SKIP() << "[gme-agent-known-failure:<id>] <简短原因>";`
- `<id>` 必须与下方对应的失败 ID 完全一致。
- 不要隐藏编译错误、测试框架错误或无效测试输入问题。
- 在注释或 skip 文本中保留失败原因和复现命令。
- 不要修改 GME 源码、测试断言、fixture 或未列出的测试。
- 不要新增 helper 函数、helper 类、helper 头文件、宏或共享工具。
- 只能给下方列出的失败生成测试添加 skip。不要新增、删除或修改通过的生成测试；选中测试 PR 的裁剪由后续流程处理。

允许修改的文件：
{allowed_file_lines}

需要标记的失败测试：
{failure_lines}

测试输出：
```text
{test_log[-12000:]}
```
"""
