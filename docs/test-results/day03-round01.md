# Day 3 回合 1：合同风险审查实测报告

日期：2026-10-07（北京时间）。基线 `45931c6`（Commit #5，只读核实），本轮代码 Commit **待提交**。范围为核心审查 Schema、RAG + LLM 服务、API、两份演练参考数据、72 项新增测试及归档文档；完整图与语义 Critic 未实现。

## 环境与命令

所有 Python 和 pytest 命令均使用仓库 `.venv`，实际版本为 Python 3.12.13。未调用全局 Python，未安装/升级依赖，未修改 `requirements.txt`，未读取/归档真实密钥或个人信息，未执行 Git 写操作。测试配置为合成聊天 Key、空向量 Key、临时 Chroma；模拟聊天和云向量调用，未访问真实云 API。

针对性命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp tests/test_review.py
```

诊断命令（仅在首次运行阻塞后使用）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp tests/test_review.py -o faulthandler_timeout=20
```

全量命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

## 真实运行结果

| 运行 | 结果 | 退出码 | 说明 |
| --- | --- | --- | --- |
| 首次针对性，受限环境 | 无测试完成结果；手动终止 | 1 | 阻塞在第一个 TestClient fixture |
| 针对性诊断，受限环境 | 20 秒诊断超时后手动终止 | 1 | 栈定位至 asyncio `_fallback_socketpair` 的 socket `accept`，未进入服务 |
| 针对性，受控提升权限 | 71 passed in 4.28s | 0 | 同一离线测试，未改变业务代码来绕过 TestClient |
| 资源关闭容错变更后针对性复测 | 72 passed in 3.31s | 0 | 新增关闭异常不覆盖 Mock 200 的验证 |
| 最终全量，受控提升权限 | **175 passed in 15.09s** | **0** | 原 Day 1/2 的 103 项 + 本轮 72 项；无失败、跳过或警告 |

最终全量输出：

```text
........................................................................ [ 41%]
........................................................................ [ 82%]
...............................                                          [100%]
175 passed in 15.09s
```

两次受限环境运行没有完成结果，不能称为测试通过。提升权限仅用于解决 Windows 本地事件循环通信阻塞，测试仍全部离线；没有发起真实聊天/向量请求。

## 验证覆盖

| 项目 | 实际验证的行为 |
| --- | --- |
| Mock API | 无聊天 Key 时返回 200、合法 JSON，HIGH + NONE、total_risks=1，跳过客户端/Chroma；即使合成向量 Key 存在也不访问云端 |
| 输入校验 | 缺失、空、9/5001 字符、纯空白、非字符串返回 422；10/5000 字符通过；top_k 默认 4，1/4/8 传入检索，非法类型或越界返回 422 |
| Key 判定 | 空白、大小写英文占位及中文占位 Key 全部使用 Mock，不调用检索或聊天 |
| 原句定位 | Mock 多句、单句、含空白和敏感数字输入均可定位；真实模式拒绝模型伪造/改写的原句 |
| 检索证据 | 有限合法正分进入 Prompt；NaN/Infinity/零/负/超界/bool/字符串/None 过滤，0.01 保留；未知 ID、伪造正文和重复候选不进入 Prompt |
| JSON 与引用 | 拒绝代码块、非 JSON、对象/null/空数组/内容块、非法风险枚举、缺少风险解释/建议、重复条款 ID、额外字段、范围外或未召回引用 |
| 有界重写 | 第一或第二次重写可修复；始终无效时总生成恰好三次后 Mock；聊天调用异常直接降级，无 SDK 自动重试 |
| 风险统计 | HIGH/MEDIUM/LOW 计入，NONE 不计；全 NONE 时 total_risks=0，可使用空解释/建议/引用 |
| 脱敏与异常详情 | 检索及聊天只收到二次脱敏文本；模型返回敏感数字会拒绝；合成异常密钥不出现在响应或日志 |
| 配置与资源 | ChatOpenAI 使用指定 base_url/model/key、timeout=20、max_retries=0、Chat Completions；自有资源关闭一次，关闭失败不覆盖 Mock 200 |
| 缺库与故障降级 | 客户端初始化失败、未就绪、空证据、检索失败及聊天失败均 Mock；真实 Key 配置但缺库时不创建目录 |
| 本地串联 API | 临时 Chroma 入库 32 条，用真实检索配合模拟聊天调用 API，返回 success 并引用 LAW-716，关闭自有存储和聊天资源 |
| 演练参考隔离 | 两份脱敏合成文本可通过 Mock API，明确不是法律依据；权威加载器仍仅加载 32 条法条 |

上述异常输入和响应、异常分数、上游与关闭失败都是**故障注入**。服务的结构/定位/引用检查不能代替法律语义质检；未验证真实 SiliconFlow 连通性、云端向量排序、模型审查质量、完整 LangGraph/Critic、前端审查交互或三场景端到端闭环。

## 文档与边界

已按本轮明确要求使用 `success/mock`，最终完整图的 `needs_review` 留待后续；未改总 Spec。定位按总 Spec 使用脱敏文本，已脱敏输入同时满足请求原文精确子串条件。Mock 不编造引用，正常合同也返回演示 HIGH，不能用于实质风险结论。押金返还缺乏本章直接依据，需要额外材料。

## 清理与工作区检查

全量测试完成后，核验 `.runtime` 及本轮 `.runtime/pytest_tmp`、`.runtime/pytest_cache` 的绝对路径位于仓库且不是重解析点，用原生 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 在普通权限下清理成功，退出码 0。两个目标的 `ExistsAfterCleanup` 均为 False；其他 runtime 目录和旧 `.pytest_cache` 不属于本轮清理范围。

只读 `git --no-optional-locks diff --check` 退出码 0，没有空白错误；Git 提示部分现有文件未来可能 LF → CRLF，不影响测试结果，未为此更改 Git 配置。状态检查显示本轮 3 个已跟踪文件修改、8 个新增文件（共 11 个），无删除项：

```text
 M README.md
 M backend/app/main.py
 M docs/prompt-history/README.md
?? backend/app/api/review.py
?? backend/app/schemas/review.py
?? backend/app/services/review.py
?? backend/data/scenarios/sample_contracts.json
?? docs/prompt-history/chain-02-risk-review/README.md
?? docs/prompt-history/chain-02-risk-review/day03-round01-review-api.md
?? docs/test-results/day03-round01.md
?? tests/test_review.py
```

收尾使用 `git --no-optional-locks status` 和 `git --no-optional-locks status --short --untracked-files=all` 核对最终清单。本轮没有修改 `requirements.txt`、Spec、已有测试和既有业务服务，没有暂存、提交或推送。
