# Day 4 回合 1：LangGraph Critic 审查图实测

日期：2026-10-09（北京时间）。基线 `fe688c3`（Commit #7，只读核实），本轮 **待提交**。工作区起初干净；测试全部离线，未发起真实云端聊天或向量请求。

## 环境与依赖

所有 Python、pip、pytest 均使用仓库 `.\.venv\Scripts\python.exe`。LangGraph 已安装为 0.6.11；langchain-core 0.3.86、langchain-openai 0.3.35。按用户要求执行：

```powershell
.\.venv\Scripts\python.exe -m pip install langgraph
.\.venv\Scripts\python.exe -m pip check
```

安装显示 `Requirement already satisfied`。首次 pip 出现四个沙箱系统临时目录清理 warning；随后将当前进程 TEMP/TMP 指向 `.runtime/pip_tmp` 重跑相同安装命令，退出码 0、无清理 warning。`pip check` 输出 `No broken requirements found.`，退出码 0。

`requirements.txt` 的既有 LangGraph 条目更新为 `langgraph>=0.6.11,<0.7.0`，对应本轮 Runtime context 用法和实际测试系列；没有重复添加依赖或跨系列升级环境。

## 测试命令与结果

首个普通沙箱运行进入首个 `test_mock_api_returns_valid_json_without_storage_or_cloud` 用例后无输出阻塞；中断，退出码 1，没有得到测试结论。表现与仓库已记录的 Windows 本地 socketpair 阻塞一致，但本轮未取得底层调用栈。随后两次测试均获自动审核许可后在受控提升权限下运行相同命令。

针对性命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp tests/test_review.py
```

实测末行：

```text
113 passed, 1 warning in 4.07s
```

全量命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

实测末行：

```text
216 passed, 1 warning in 13.92s
```

两次完成运行均退出码 **0**，**0 failed、0 skipped、0 errors**。审查模块从 100 增至 113 项，全量从 203 增至 216 项。未出现代码断言失败，也未通过忽略 warning 或跳过测试达成通过。

唯一 pytest warning 来自 `.venv/Lib/site-packages/langgraph/cache/base/__init__.py:8` 导入 JsonPlusSerializer，类别 `LangChainPendingDeprecationWarning`，提示未来 `allowed_objects` 默认值将改变。本项目没有配置 checkpoint 或序列化持久化，本轮保留并如实记录依赖导入 warning。

## 覆盖与行为

| 范围 | 实际断言 |
| --- | --- |
| 服务入口 | graph.invoke 恰好一次，传入脱敏合同、过滤后的权威证据、retry_count=0；客户端通过请求独立的 Runtime context 注入 |
| 真实节点路径 | graph.stream 实际发出 drafting/critic 更新；首次成功、一次修正和两次修正均按预期退出 |
| 原句定位 | 改写原句失败，错误反馈进入下一次起草；通过后仅返回脱敏合同连续子串 |
| 有限退出 | 三次坏 JSON 后 retry_count=2、终态 needs_review、保留失败原因、清空未通过结果与草稿 |
| 引用护栏 | 延续既有召回引用交集、去重、未知及未召回 ID 过滤；无引用 HIGH 统一最多三次生成后 Mock，修正到有效 LAW-716 后可成功 |
| 反馈隐私 | Schema、原句与额外字段故障注入中的敏感输出不进入重写消息；异常日志仅包含异常类型 |
| 上游异常 | 图实际走 drafting → mock，不追加生成；终态 needs_review；服务保留原有演示响应 |
| 请求隔离 | 同一编译图连续执行失败、成功请求；错误、消息和重试数不跨请求传递 |
| API 兼容 | 对外仍只有 status/results/total_risks；内部 needs_review 或图异常转为 mock，内部原因不进入响应 |
| 既有回归 | 严格 JSON、完整围栏、重复键、非有限数、敏感数字、RAG 过滤、实际 SDK invoke 拦截、本地 Chroma、资源释放、422、健康和知识库测试继续通过 |

修改原四项 HIGH 无依据测试的生成次数断言为三次，不放松失败门槛；新增 13 项图路径及兼容测试。所有异常模型输出和服务异常为**故障注入**。实际 ChatOpenAI 客户端依然采用 temperature=0.1、max_retries=0，调用均被离线拦截。

## 契约适配与未验证项

spec-00 要求失败图终态 `needs_review`，用户本轮要求维持旧 API 的 `mock` 出口。图保留原因并阻止无效结果成为正式输出，服务适配原有 Mock 演示；Schema、路由及 Spec 未改。

本轮 Critic 验证结构、定位、引用追溯和隐私；未证明解释在法律语义上充分受引用支持。未验证真实云端连接、计费、模型质量、独立语义 Critic、前端节点回放或谈判图。

## 清理与工作区

首次清理脚本使用不兼容的 `Split-Path -LiteralPath ... -Parent`，在路径检查阶段出错，已中断；修正为 .NET 父目录解析并设置错误即停止后，确认三个目标绝对路径均在仓库内，目标与祖先不是重解析点，再以原生 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 删除。

清理成功退出码 0，以下三项 `ExistsAfterCleanup` 均为 False：`.runtime/pytest_tmp`、`.runtime/pytest_cache`、`.runtime/pip_tmp`。保留其余历史 runtime 目录。首次 pip 告警涉及的沙箱系统临时目录不属于仓库清理范围，未越界删除。

本轮改动 8 个文件：

- `backend/app/services/graph.py`（新增）
- `backend/app/services/review.py`（修改）
- `requirements.txt`（修改）
- `tests/test_review.py`（修改）
- `docs/prompt-history/README.md`（修改专项入口）
- `docs/prompt-history/chain-03-langgraph/README.md`（新增）
- `docs/prompt-history/chain-03-langgraph/day04-round01-critic-graph.md`（新增）
- `docs/test-results/day04-round01.md`（新增）

`git --no-optional-locks diff --check` 退出码 0，无空白错误；Git 对两个修改文件给出未来 LF → CRLF 的提示，与 pytest warning 分开记录。`git --no-optional-locks status` 及完整短状态核实 4 个修改、4 个新增文件，均未暂存。没有提交、推送或其他 Git 写操作；未修改 `.git/`、Spec、Schema、API、场景、法条数据及仓库外进度记录。
