---
name: gme-acis-interface-analyzer
description: 分析用户选择的 GME 模块与 _deps/acis/R35 中 ACIS 接口的对应关系，找出适合生成 GME vs ACIS GoogleTest 对比测试的接口候选。
---

# GME/ACIS 接口候选分析

## 任务

分析当前模块中哪些 GME 接口适合和 ACIS 接口做对比测试，并写入 `.gme-agent/acis_interface_candidates.md`。

优先读取这些位置，如果存在：

- `module/<module>/`
- `include/`
- `_deps/acis/R35/`
- `.gme-agent/module_test_profile.md`

本步骤只做分析，不修改代码。

## 候选接口选择规则

优先选择：

- GME 和 ACIS 名称相近或行为相近的 API
- `tests/gme` 中已有 helper 或示例可复用的 API
- 输入输出确定、可重复验证的 API
- 可以比较返回值、对象属性、求值结果或状态码的 API
- 不依赖无关模块源码的 API

暂时避免：

- 依赖不可用 license、UI、demo、网络或随机数据的接口
- 依赖无关模块源码目录的接口
- 需要大量新几何构造基础设施的接口
- ACIS 期望行为不清楚的接口
- 需要修改生产代码才能测试的接口

## Markdown 格式

写入 `.gme-agent/acis_interface_candidates.md`，结构如下：

```markdown
# ACIS Interface Candidates: <module>

## High Confidence Candidates

## Medium Confidence Candidates

## Avoid For Now

## Recommended Cases For This Run
```

每个候选接口需要说明：

- GME API 或类
- ACIS API 或类
- 依据的文件
- 可复用的 helper 或 fixture
- 建议测试场景
- 置信度和原因

