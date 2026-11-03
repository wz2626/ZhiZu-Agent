# HTTP条件范围与任务清理所有权收敛

附件精简（2026-11-01，开发者要求）：重复截图、中间对比图及旧机器验收附件已移出待提交目录，保存在本机忽略归档 `.runtime/evidence-tidy-20261101.zip`；下文历史实测结论保留，附件数不代表当前保留数。


2026-10-31，执行开发者确认的三个边界，不扩展前端玩法或重构共享谈判服务。保留先前工作，不进行Git写操作。

HTTP/网页仅接收场景对应的数值确认条件。api/negotiation.py在提交前的_response中检查键、类型和范围，非评分round_N返回受控422 UNSUPPORTED_HTTP_TERMS，正式状态与请求缓存不变。重放出口也检查已缓存的Python公开快照，避免其绕过HTTP限制。NegotiationService、NegotiationState及通用响应模型保持不变，public_api=True的Python调用仍能提交合法非评分安排。Spec 04明确HTTP范围及Python兼容边界。

CloudExecutor.run接收可选cleanup：未取得槽位或submit失败时由准入路径清理；submit成功即把资源交给任务，future完成回调负责关闭及释放容量，涵盖执行、排队超期、执行前失效及提交后取消。HTTP超时/取消不关闭已提交任务，未使用started标志判断所有权。审查API将service.close交给执行器，移除work内的重复清理；清理异常仅记录类型，不覆盖业务结果。Spec 00同步该所有权规则。

## 实测结果

| 检查 | 结果 |
| --- | --- |
| 相关Python回归 | 274 passed；随后修正新增测试中的Pydantic弃用写法 |
| 最终全量离线pytest | **827 passed，0 failed/skipped，22.28秒**；仅一条既有LangChain弃用提示 |
| Day10真实本机浏览器流程 | **48组通过，0失败/跳过，外部请求0** |
| diff空白检查 | 通过 |

新增tests/test_http_contract_and_cleanup.py共8项：HTTP拒绝安排且Python兼容；Python缓存公开快照的HTTP拒绝；槽位满关闭一次；submit失败关闭一次并归还容量；排队超时不执行且关闭一次；执行中HTTP超时不提前关闭；已提交排队任务HTTP超时不回收所有权；清理异常不污染结果和日志。

一次中间全量运行出现1失败/826通过：新增“排队期间HTTP超时”用例错误地假定Windows asyncio超时一定晚于操作时钟截止。改为显式推进操作时钟，仍严格断言任务未执行、清理恰好一次，没有放宽断言；最终完整重跑通过。失败记录保留在忽略目录的full-pytest.txt，不作为通过证据。

附件：最终pytest输出（附件已移至本机归档）、Day10结果（附件已移至本机归档）。本轮未重跑Day8/视觉检查、真实云模型或压力测试；审查与草稿仍使用明确离线替身，固定谈判使用真实本机HTTP及图。

实际完成命令（仓库根目录；再次运行请更换独立目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/v4-contract-lifecycle-20261031/acceptance-pytest -o cache_dir=.runtime/v4-contract-lifecycle-20261031/acceptance-cache --tb=short
node scripts/check_day10_frontend.cjs --out .runtime/v4-contract-lifecycle-20261031/day10 --runtime-dir .runtime/v4-contract-lifecycle-20261031/browser10
```
