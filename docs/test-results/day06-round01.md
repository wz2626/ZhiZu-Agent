# Day 6 回合 1：沉浸道场状态图与会话隔离实测报告

日期：2026-10-11（北京时间）。代码基线 `233a473`，Day 6 四个 Python 文件尚未提交。本报告在开发完成后，根据同一聊天中实际执行的命令、工具返回和现有测试断言补录；本次文档补充没有重新运行 pytest，也没有修改任何 `.py` 文件。

## 范围与实现边界

按《大体计划_修订版》Day 6 和 [Spec 00](../specs/spec-00-architecture.md) 第 3.2、4 节，实现谈判 Schema、租客辅导 → 模拟房东 → Critic 状态图、单进程内存会话及边界测试。Day 1–5 审查业务和已有测试保持只读。关联的 [Prompt 过程记录](../prompt-history/chain-02-graph-critic/day06-negotiation-graph.md) 为本聊天可见内容的摘录与过程摘要，完整原始导出仍待归档。

默认角色节点使用明确标注的模拟回复，不调用云端模型；默认房东不确认条件。Critic 目前仅检查候选条件结构与房东确认标记，不代表法律语义校验已经完成。`trial_score=None`，规则算分留待 Day 7；本轮没有验证真实模型谈判质量、规则分值或跨进程会话共享。

## 实际命令与结果

执行目录为 `D:\AgentDev\ZhiZu-Agent`，所有 Python/pytest 均使用仓库 `.\.venv\Scripts\python.exe`。Day 5 全量为 267 项，本轮新增 24 项，最终共 291 项。

| 验证 | 实际结果 | 退出码 |
| --- | --- | --- |
| 新增谈判模块测试 | 24 passed，0 failed，0 errors，0 skipped，1 warning，0.41 秒 | 0 |
| 全量收集（不算测试通过） | 291 tests collected，2.27 秒 | 0 |
| 受控提升权限下全量离线测试 | 291 passed，0 failed，0 errors，0 skipped，1 warning，15.67 秒 | 0 |

新增模块命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_negotiation.py -o cache_dir=.runtime/day06/cache --basetemp=.runtime/day06/tmp
```

本聊天工具返回的结果行摘录：

```text
24 passed, 1 warning in 0.41s
```

全量收集命令：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o faulthandler_timeout=20 -o cache_dir=.runtime/day06/collect_cache
```

最终全量命令（自动审核许可后的受控提升权限运行）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o cache_dir=.runtime/day06/verified_cache --basetemp=.runtime/day06/verified_tmp
```

本聊天工具返回的结果行摘录：

```text
291 passed, 1 warning in 15.67s
```

唯一 warning 来自 `.venv/Lib/site-packages/langgraph/cache/base/__init__.py:8`，类别为 `LangChainPendingDeprecationWarning`，提示 `allowed_objects` 的默认值将改变。本轮没有隐藏该警告、修改依赖或配置持久化 checkpoint。

上述结果是上一轮实际执行记录的摘录，不是本次文档补充的新测试结果；上一轮未另外保存 Day 6 的 JUnit 或原始 pytest 输出文件。本报告不把摘录冒充原始日志附件，也不补造逐用例耗时。

## 并发防串线证据

下表的断言来自实际通过的 [test_negotiation.py](../../tests/test_negotiation.py)。双会话测试使用合成房东节点，明确提供确认标记与嵌套候选条件，执行真实编译图及服务提交路径；不将测试替身当成真实模型响应。

| 用例 | 输入与执行方式 | 实际通过的断言 |
| --- | --- | --- |
| `test_two_sessions_two_rounds_never_cross[False]` | A、B 交替各谈两轮；输入分别为 `A安排1/2`、`B安排1/2` | 每个结果的 `session_id`、轮次、用户历史和嵌套确认条件都只属于本会话；A 继续第三轮后 B 仍为第二轮 |
| `test_two_sessions_two_rounds_never_cross[True]` | 每轮用两个工作线程并发执行 A、B，共两轮 | 与交替版本相同的隔离断言全部通过 |
| `test_different_sessions_can_execute_graph_at_same_time` | A、B 的房东节点通过 `Barrier(2)` 会合，超时为 5 秒 | 两个会话都能进入图执行并返回各自 ID；该用例验证没有用一把全局锁串行包住所有会话图调用 |
| `test_returned_snapshots_and_cached_responses_cannot_modify_sessions` | 修改返回结果中的嵌套列表与历史，再清空读取快照 | 正式会话与重复请求缓存仍保留原内容，另一个会话历史仍为空 |
| `test_duplicate_requests_commit_once_and_keys_are_session_local` | 四线程对 A 重复使用同一请求 ID；B 也使用该 ID | A 只提交一轮，B 独立提交一轮；同 ID 换输入被拒绝，回取旧响应不会回退当前轮次 |

这些证据覆盖当前单进程、同一个 `NegotiationService` 实例中的隔离与并发边界，不表示已经完成多进程或分布式隔离验证。

## 5 轮上限与失败提交证据

| 用例 | 实际通过的断言 |
| --- | --- |
| `test_fifth_round_completes_and_sixth_never_runs_nodes` | 前四轮为 `success`，第 5 轮为 `completed`；第 6 次输入返回相同状态，轮次仍为 5，历史仍为 15 条；B 的首轮正常执行 |
| `test_graph_also_guards_round_limit` | 直接将 `round_count=5` 传入编译图，并把租客辅导节点替换成一旦调用就失败的函数；图绕过角色节点，保持 5 轮并返回 `completed` |
| `test_same_session_concurrent_requests_stop_at_five` | 八线程向同一会话提交请求，最终只有 5 轮、15 条历史、5 个确认条件；所有响应的轮次都不超过 5 |
| `test_schema_rejects_invalid_round_count`（4 个参数） | `-1`、`6`、`True`、`"2"` 均被 Schema 拒绝；默认值测试另断言赋值为 6 也被拒绝 |
| `test_critic_retries_at_most_twice_and_failed_round_is_not_committed`（3 个参数） | 故障注入 1/2/3 次未确认候选；最多生成 3 次、重写 2 次；持续失败返回 `needs_review`，正式轮次、条件、历史不变；失败请求可重新尝试，下一轮重试计数归零 |
| `test_exception_cannot_mutate_existing_session` | 注入图异常并尝试修改已有嵌套条件和历史；异常被测试预期捕获，已有正式会话保持原样 |

其余新增测试覆盖默认容器独立、三角色历史顺序、租客单方诉求不被确认为条件、空输入与非法会话/请求标识。参数化展开后总计 24 项。预期的校验异常与故障注入是通过用例的一部分，不是测试执行错误。

## 执行障碍与真实性说明

开发阶段两次普通受限环境全量运行长时间无输出，均已中断，退出码 1，没有获得通过或失败的测试结论：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q -o cache_dir=.runtime/day06/full_cache --basetemp=.runtime/day06/full_tmp
```

现象与仓库历史记录中的 Windows 受限环境 `TestClient` 阻塞一致，但本轮没有取得底层调用栈，不能写成已确认 socketpair 根因。随后受控提升权限的全量命令完成并通过。完成的窄范围和全量测试均未出现断言失败或 setup/执行错误；“0 报错通过”仅指这些已完成测试，不代表前述中断命令退出码为 0，也不代表没有依赖警告。

用户在补档请求中转述 Kimi 已完成事后审计并认可隔离与并发实现；本次未收到审计原件、未重新执行该审计，因此不以该转述替代上述实测证据。

## 文件与清理

Day 6 开发仅新增以下 Python 文件，既有审查模块、已有测试、Spec 与依赖均未修改：

- `backend/app/schemas/negotiation.py`
- `backend/app/services/negotiation_graph.py`
- `backend/app/services/negotiation_service.py`
- `tests/test_negotiation.py`

开发收尾先验证目标绝对路径在仓库内、路径及目录内容不含重解析点，再删除本轮 `.runtime/day06` 及上述新模块/测试对应的四个 `.pyc` 文件。工具返回 `Day06TemporaryDirectoryExists: False`。未清理其他历史 runtime 内容、云端向量库或 `.env`。

上一轮最终执行 `git --no-optional-locks diff --check`、`diff --stat` 和 `status`：已有跟踪文件无差异，仅四个新 Python 文件未跟踪，无暂存或提交。本次补档只新增本报告、谈判过程记录，并更新该链 README；四个 Python 文件属于开始时已有的工作区内容。完整原始聊天导出及 Kimi 审计原件仍待提供，关联 Day 6 代码 Commit 为“待提交”。

本次文档补充前后，对 `rg --files -g '*.py'` 列出的 29 个工作区 Python 源文件逐一计算 SHA-256，文件集合与哈希全部一致；三份文档的 10 处本地链接均可解析到现存文件。没有重新运行 pytest、生成新测试缓存或创建临时目录；复核 `.runtime/day06` 仍不存在。本次新增变更仅限三项文档，最终 Git 状态中的四个未跟踪 Python 文件是此前已存在的 Day 6 交付物。
