# GME Test Agent 使用流程

本文档面向拿到 `GME Test Agent-0.1.0-x64.exe` 的使用者。

## 1. 使用前准备

使用者电脑上需要已有以下环境：

- Windows x64
- 本地 GME 仓库，例如 `D:\GME`
- Codex App 或 Codex CLI 已登录，并且当前 Windows 用户下 Codex 可正常使用
- Git
- CMake
- Visual Studio 2022 C++ Build Tools
- `clang-format`
- GitHub CLI `gh`
- 已执行 `gh auth login`，并且账号有目标测试仓库的 push/PR 权限


## 2. 获取工具

```text
GME Test Agent-0.1.0-x64.exe
```

使用者双击 exe 即可启动。

## 3. 第一次启动会自动创建什么

第一次打开时，工具会在当前 Windows 用户的应用数据目录下创建自己的本地数据。

典型路径类似：

```text
C:\Users\<用户名>\AppData\Roaming\GME Test Agent\
```

其中会自动生成：

```text
config.local.json
gme_agent.db
worktrees\
artifacts\
logs\
```

说明：

- `config.local.json`：本机配置文件。
- `gme_agent.db`：本地 SQLite 数据库，保存任务、日志、失败用例记录。
- `worktrees\`：每个任务独立创建的 GME worktree。
- `artifacts\`：prompt、运行日志、gtest xml、patch 等产物。
- `logs\`：桌面程序和后端日志。

使用者不需要提前准备数据库。`gme_agent.db` 不存在时，后端会自动创建。

## 4. 首次配置

启动后进入“设置”页，重点检查这些配置：

- `gme_repo_path`：本机 GME 仓库路径，例如 `D:/GME`
- `worktree_root`：任务 worktree 存放目录
- `artifact_root`：任务产物存放目录
- `database_path`：本地数据库路径，首次启动会自动指向本机应用数据目录
- `base_branch`：创建任务 worktree 的基础分支，通常是 `main`
- `github_remote`：远端名，通常是 `origin`
- `model`：Codex 使用的模型

配置完成后，点击“环境检查”。

环境检查通过后再开始生成测试。

## 5. 生成测试流程

进入“测试 Agent”页：

1. 选择模块，例如 `laws`、`base`。
2. 在“测试目标 / 提示词”里填写想扩展的测试方向。
3. 点击“新建任务并生成”。
4. 等待任务完成。

工具会为该任务创建独立 worktree，不会直接修改原始 `D:\GME` 工作目录。

生成完成后，可以在页面中查看：

- 当前任务
- 生成文件路径
- 构建日志
- 测试结果

## 6. 构建和运行测试

如果任务生成后还没有构建或运行，可以手动点击：

- “构建”
- “运行测试”

运行测试后，如果存在 GME vs ACIS 差异，失败会进入 failure 表。

失败记录会包含：

- failure id
- suite
- test name
- 文件路径
- 行号
- 失败原因

## 7. 加 skip 并创建 PR

如果确认当前失败是 GME 和 ACIS 的真实差异，可以点击：

```text
加 skip 并创建 PR
```

该流程会：

1. 读取当前选中任务的最新 open failures。
2. 只给这些失败测试加：

```cpp
GTEST_SKIP() << "[gme-agent-known-failure:gmefail-xxx] reason";
```

3. 使用当前 worktree 的 `.clang-format` 格式化 generated test 文件。
4. 重新运行这些失败测试对应的 GTest filter。
5. 确认 skip 后 failure 清零。
6. 创建新的 skip 专用分支。
7. 只提交测试仓库中相关 generated test 文件。
8. 创建普通 PR。

注意：

- PR 不会提交无关文件。
- PR 中 generated test 文件会被裁剪为只包含本次失败并加 skip 的测试。
- 本地任务 worktree 会保留完整 generated 文件，方便继续扩展。

## 8. 继续扩展已有任务

如果想在已有任务基础上继续生成测试：

1. 选中任务。
2. 修改“测试目标 / 提示词”。
3. 点击“继续扩展选中任务”。
4. 重新构建和运行测试。

如果又出现新的真实失败，可以再次点击“加 skip 并创建 PR”。

每次 skip PR 都会创建新的独立 skip 分支。

## 9. 数据和日志位置

如果需要排查问题，可以查看：

```text
C:\Users\<用户名>\AppData\Roaming\GME Test Agent\logs\
```

常用文件：

```text
backend.out.log
backend.err.log
```

任务产物在：

```text
C:\Users\<用户名>\AppData\Roaming\GME Test Agent\artifacts\
```

任务 worktree 在：

```text
C:\Users\<用户名>\AppData\Roaming\GME Test Agent\worktrees\
```

具体路径也可以在“设置”页查看。

## 10. 常见问题

### 环境检查提示 Codex auth 失败

说明当前 Windows 用户下没有可用 Codex 登录态。

处理方式：

1. 打开 Codex App 或 Codex CLI。
2. 使用自己的 OpenAI/ChatGPT 账号登录。
3. 确认 Codex 能正常运行。
4. 重新打开 GME Test Agent 并执行环境检查。

### 环境检查提示 gh 不存在

安装 GitHub CLI，并登录：

```powershell
gh auth login
```

登录账号需要有目标仓库的 push/PR 权限。

### 构建失败

检查：

- Visual Studio 2022 C++ Build Tools 是否安装
- CMake 是否在 PATH 中
- GME 仓库和子模块是否完整

### PR 创建失败

检查：

- `gh auth status`
- `git remote -v`
- 当前账号是否有目标仓库写权限
- 网络是否能访问 GitHub

### clang-format 失败

检查：

- `clang-format` 是否在 PATH 中
- 当前 GME worktree 根目录是否有 `.clang-format`

