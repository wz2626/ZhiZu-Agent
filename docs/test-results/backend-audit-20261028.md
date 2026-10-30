# 后端整体复审与修复验收（2026-10-28）

本次按开发者“整体审阅后端、发现问题直接修复”的授权，复核接口输入与异常出口、审查与知识库、协商提交与算分、草稿上下文与幂等缓存。仅针对复现问题修复；前端、业务 Spec、算分公式及 API 成功响应字段未调整。没有 Git 提交。

## 发现并修复的问题

| 问题 | 实际影响与修复 | 回归文件 |
| --- | --- | --- |
| 422 校验响应回显原始输入 | 审查／知识库接口在超长、类型错误等输入下会返回未脱敏的 `input`。保留错误类型与字段位置，移除输入、异常上下文并使用受控提示；协商／草稿原有安全提示保留。 | `tests/test_api_privacy_audit.py`（11项） |
| JSON 转义造成隐私漏检 | 在序列化后检查会把制表符变成转义文本，导致原本支持遮蔽的分隔手机号漏检。草稿、协商候选改为检查解码后的字段；嵌套条件的键值也检查。审查上下文改为先逐字段脱敏再存储。 | `tests/test_proposal_audit.py`（6项）、`tests/test_negotiation_audit.py`（5项） |
| 风险结果编号遗漏隐私检查 | 模型可把敏感号码放进合法格式的 `clause_id`。编号现与解释等字段共同进入 Critic 隐私校验，失败沿用最多两次重写与安全反馈。 | `tests/test_review_audit.py`（12项中的审查部分） |
| 向量响应 index 不完整 | 仅按 index 排序不能阻止重复或错位编号，可能把向量绑定到错误法条。现要求严格整数、唯一且完整覆盖输入位置；正常乱序响应继续还原。 | `tests/test_review_audit.py`（12项中的向量部分） |

上述缺陷均通过合成输入／模型或向量响应替身复现，不代表真实用户数据已发生泄露。API 组修前9失败、审查／向量组修前9失败、协商组修前4失败、草稿隐私组修前3失败；修复后全量包含原有728项和新增34项，未删改旧测试来绕过断言。

额外验证了草稿返回值、审查快照与缓存的副本隔离；上下文过期前已获取的请求可完成，过期后新请求拒绝；并发相同编号的失败请求只执行一次，最多三次生成，正式条件／轮次／分数保持原值。

## 最终验证

| 检查 | 实测结果 |
| --- | --- |
| 全量 Pytest | **762 passed，0 failed，0 skipped**；33.52秒 |
| 真实本机 HTTP 冒烟检查 | **9组通过**；临时 Uvicorn 进程已关闭 |
| 环境依赖一致性 | `pip check`：`No broken requirements found.` |
| 改动格式 | `git --no-optional-locks diff --check` 通过；存在仓库原有的 LF/CRLF 提示 |

Pytest 有1条既有 `LangChainPendingDeprecationWarning`，来自依赖关于未来 `allowed_objects` 默认值的提示。本轮没有升级依赖或抑制警告。

HTTP 检查使用实际 FastAPI/Uvicorn 服务，显式清空云密钥并指向不存在的独立知识库目录。覆盖启动／健康／同源页面、OpenAPI 唯一协商提交入口、缺库只读失败、缺聊天配置与旧版演示回退、422隐私和失效草稿上下文、三场景各五轮与旧快照重放／请求冲突、六个并发同编号请求只提交一次。缺库检查没有创建该目录。

完整命令（从仓库根目录执行；临时目录父目录须先存在）：

```powershell
$env:PYTHONUTF8='1'
New-Item -ItemType Directory -Force -Path .runtime/backend-audit-20261028 | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/backend-audit-20261028/full-temp -o cache_dir=.runtime/backend-audit-20261028/full-cache -o faulthandler_timeout=40
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .runtime/backend-audit-20261028/http_smoke.py
```

最后一项为本轮临时验证脚本。原始全量输出、HTTP结果及服务日志保存在本地忽略目录 `.runtime/backend-audit-20261028/`；本次仅归档这份报告，不生成截图或覆盖历史验收证据。

中断前有两次环境受阻：Windows 沙箱阻塞 TestClient 所需的回环连接；另一次临时目录父目录缺失产生11个 setup errors。这些均不计作业务断言失败或测试通过。最终运行使用已创建的新目录和本机执行权限；Pytest 的外网拦截 fixture 保持启用。

## 本次文件范围

实现：`backend/app/main.py`、`backend/app/services/embedding.py`、`backend/app/services/graph.py`、`backend/app/services/negotiation_graph.py`、`backend/app/services/proposal.py`、`backend/app/services/review_context.py`。

新增回归：`tests/test_api_privacy_audit.py`、`tests/test_review_audit.py`、`tests/test_negotiation_audit.py`、`tests/test_proposal_audit.py`。文档：本报告及结果索引。

## 结论与验证边界

本轮未发现尚未解决、阻断现有单机使用路径的后端缺陷。已验证失败不提交、会话隔离、相同请求重放、五轮上限、有限重写、证据范围和受控异常出口。

本轮云调用为0，未重新验证真实供应商可用性、余额／限流或法律语义质量；工程测试通过不能证明模型每次解释都正确。既有单进程内存会话重启清空，草稿上下文有TTL与容量限制；协商会话及请求缓存仍按既有本地演练设计保留到进程结束，不将本轮结果当作公网多用户容量验收。
