# Day 5 回合 2：详细失败出口、Trace 与契约更新

日期：2026-10-11（北京时间）。代码基线 `d6f814c`，开始时 `git --no-optional-locks status --short` 无输出，工作区干净。本轮待提交。

开发者明确授权后半段：修正双平台部署模板、追踪语义问题、新增详细接口、更新架构/模块 Spec 与测试，并清理临时目录。开发者转述 Kimi 的事后审计结论；本报告不冒充重新执行了 Kimi 审计。本轮只做离线验证，没有发起真实云端聊天或向量调用。

## 完成内容

- `.env.example` 与 README 使用前半段真实验证的组合：DeepSeek 官方 `deepseek-flash` 聊天 + 硅基流动 `BAAI/bge-m3` 1024维向量，分别填写两家 Key；模板60秒超时、独立 `.runtime/chroma_cloud` 路径，显式 `--mode cloud` 入库。代码缺省超时20秒不变，本地 `.env` 未改。
- [已知问题](../known-issues.md) 记录转租授权语义及正常合同 MEDIUM/LOW 疑似误报，留待 Day 11 集中复核和 Prompt 调优。本轮没有更改风险 Prompt 或原始联调证据。
- `POST /api/review/analyze-detailed` 返回 `success/needs_review`，失败时 `results=[]`、`total_risks=0`，附 `failure_code`、安全 `reason`、`errors`、`retry_count` 和真实 Trace；不会返回 Mock 演示。失败的0分计数不代表合同没有风险。
- 详细版区分缺配置、初始化失败、缺库、向量异常、无证据、聊天超时/其他调用失败、最终校验失败及编排异常。业务失败HTTP 200，输入错误422。
- 配置/检索由服务记录，起草/Critic/失败终止由实际 LangGraph 节点记录。请求局部收集器保留编排异常前的已完成记录，未执行节点不补造。`mock` 沿用历史节点名，在详细版中仅表示终止为 `needs_review`。
- 每项 Trace 为 `sequence/node/attempt/status/duration_ms/evidence_ids/feedback`；耗时取单调时钟差。Trace 不含合同、消息、草稿、模型隐藏思维或原始异常。反馈经过固定文案/字段名白名单过滤，未知反馈安全收敛。
- 新增 [Spec 02](../specs/spec-02-risk-review.md)，同步 [Spec 00](../specs/spec-00-architecture.md) 的顶层状态、兼容出口和 Trace 契约。风险项不重复嵌套 `status`，详细版顶层显式表达审查状态。

## 兼容与隔离核对

[兼容核对记录](day05/legacy-compatibility.json) 通过只读 `git show HEAD:...` 与 AST/文件对比得到，四项均为 true：

- 旧 `analyze_contract` 方法语法树未变。
- 旧 `_mock_response` 方法语法树未变。
- `ReviewResponse` Schema 语法树未变，仍只含 `status/results/total_risks`。
- `tests/test_review.py` 与基线一致，原 fixture 和云端拦截未改。

新测试使用单独 autouse fixture，设置合成聊天配置、临时库路径和空向量凭据，并拦截 `ChatOpenAI.invoke`、向量 `httpx.post` 与底层 `httpx.HTTPTransport.handle_request`。成功、故障和并发均用合成依赖；测试不会因本地真实 `.env` 发起云调用。服务清理仍沿用前半段的请求级客户端归属规则。

## 测试命令与实际结果

Python/pytest 使用仓库 `.venv`。Windows 受限环境此前有 TestClient 阻塞记录，本轮测试直接通过自动审核后的受控提升执行，没有将权限问题伪写成测试通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_review.py -q --basetemp=.runtime/pytest_day05b_initial
# 116 passed, 1 warning in 7.40s

.\.venv\Scripts\python.exe -m pytest tests/test_review.py tests/test_review_detailed.py -q --basetemp=.runtime/pytest_day05b_review
# 157 passed, 1 warning in 5.45s

.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_day05b_full --junitxml=.runtime/day05b_validation/pytest.xml
# 267 passed, 1 warning in 16.71s

.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
```

所有完成命令退出码0，0 failed、0 skipped、0 errors。全量终端输出实际通过 `Tee-Object` 同步保存，见[原始 pytest 输出](day05-round02-pytest.txt)。唯一警告仍是 LangGraph 导入 JsonPlusSerializer 的 `LangChainPendingDeprecationWarning`，没有隐藏或跳过它。

新增41项测试覆盖：

- 新接口成功与 OpenAPI Schema、1/2次重写成功、3次错误JSON/无引用HIGH/原句无效终止；旧接口仍回退Mock。
- 缺聊天密钥、初始化失败、无证据、缺库只读、向量/存储/其他检索异常，确认未进入聊天或虚构图节点。
- Python/httpx/SDK 超时、其他聊天异常直接终止，不运行 Critic，不额外重试。
- 编排异常保留1次或2次生成前后的部分 Trace；成功重写清空顶层 errors，保留历史节点反馈。
- 时钟注入确认记录由真实计时差生成；共用编译图的并发请求隔离、重复调用同一服务的 Trace/错误重置。
- 敏感输入脱敏、无效模型输出与原始异常不进入公共反馈、Trace 无原文/消息/草稿；错误时长与不连续序号拒绝。
- 非法输入422、不执行图；强制云端向量路径也被离线 guard 拦截。

## 实际 Trace 证据

[离线执行样例](day05/trace-examples-offline.json) 由 FastAPI TestClient 调用详细版接口和真实 LangGraph 节点采集，明确标 `offline_fault_injection`。依赖是合成 LLM/Store，三处云调用入口均阻断。它们是这次故障注入的实际执行记录，不是历史云端回放，也不证明真实模型输出质量。

| 样例 | 终态与结果 | 实际节点 |
| --- | --- | --- |
| rewrite_success | success，retry_count=1 | configuration → retrieval → drafting → critic(retry) → drafting → critic(completed) |
| invalid_json_exhausted | needs_review / VALIDATION_FAILED，retry_count=2，无结果 | configuration → retrieval → drafting/critic 共3次 → mock |
| chat_timeout | needs_review / CHAT_TIMEOUT，retry_count=0，无结果 | configuration → retrieval → drafting(failed) → mock |
| no_evidence | needs_review / NO_EVIDENCE，无结果 | configuration → retrieval(failed) |

其中一条实际校验反馈（摘自 rewrite_success）：

```json
{
  "sequence": 4,
  "node": "critic",
  "attempt": 1,
  "status": "retry",
  "duration_ms": 0.098,
  "evidence_ids": ["LAW-716"],
  "feedback": ["JSON 解析失败：必须输出一个完整的 JSON 数组。"]
}
```

数值来自本次离线执行，后续重跑耗时会变化。直接图测试另用固定时钟验证125/250毫秒的差值计算，不能将该注入数值当成性能测量。`duration_ms` 是节点耗时，`graph` 异常项是编排范围耗时，两者不可简单相加冒充总体耗时。

## 收尾与剩余范围

原始 pytest 输出、兼容核对 JSON 和受控 Trace JSON 归档后，只清理本轮创建的 `.runtime/pytest_day05b_initial`、`.runtime/pytest_day05b_review`、`.runtime/pytest_day05b_full` 与 `.runtime/day05b_validation`；删除前验证绝对路径均在本仓库 `.runtime` 下，不含重解析链接。保留 `.env`、前半段探针/证据、云端向量库、Python 运行时及用户其他临时内容。最终执行 `git --no-optional-locks diff --check` 和 `git --no-optional-locks status --short`，未执行 Git 写操作。

清理实测删除4个本轮临时目录，退出码0。对16个改动/新增文件做本地实际凭据精确比对，未发现聊天或向量 Key 泄露；受控 JSON 均可解析。检查过程不输出密钥。最终 `git --no-optional-locks status` 列出8个已跟踪修改和8个新增文件，无暂存或提交。

本轮完成 Day 5 后半段的后端与契约交付。前端“本次执行回放”界面、独立语义 Critic、20例效果评估和 Prompt 调优仍按后续计划开展；真实模型语义问题不因这267项离线测试而消失。完整原始聊天记录仍待开发者保存，本报告不替代原始对话链。
