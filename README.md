# GME Test Agent

GME Test Agent 是一个本地测试工作流工具，用于选择 GME 接口、生成 GME 与 ACIS 对比测试、构建和运行测试、审查失败，并提交选中的测试 PR。工具同时提供基于失败测试的 GME 缺陷修复工作流。

## 使用方式

- [源码运行使用说明](docs/源码运行使用说明.md)
- [桌面版使用说明](docs/gme-test-agent使用说明.md)

激活任意兼容的 Python 环境后执行：

```powershell
scripts\setup_source.ps1
# 修改 config.local.json 中的 gme_repo_path
scripts\run_web.ps1
```

Python 需要 3.10 或更高版本，Node.js 需要 18 或更高版本。完整的 GME、编译工具和 GitHub CLI 要求见源码运行使用说明。
