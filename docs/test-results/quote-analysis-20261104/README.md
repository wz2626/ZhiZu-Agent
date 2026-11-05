# 微信破招模块实施与验收（2026-11-04）

附件精简（2026-11-06）：本历史阶段保留报告和汇总JSON，原始批次/复测JSON、浏览器结果及截图已校验SHA-256后转存本机忽略归档 `.runtime/precommit-cleanup-20261106/historical-attachments.zip`，不随本次提交分发。下文原始文件名指该归档中的条目，历史数字及失败记录不变。最新完整公开证据见[可用性复核](../quote-analysis-readiness-20261104/README.md)。

历史提示：联合CR确认本版状态约束与正常fixture存在遗漏，不能把本报告的“通过”当作修补后契约的验收。最新修复与独立验证见[联合CR补丁报告](../quote-analysis-cr-patch-20261104/README.md)；下文历史数字和失败记录保持原样。

本轮按开发者合议实施[Spec 07](../../specs/spec-07-quote-analysis.md)：无状态全文合同、一次Chat、本地词法检索、来源回填、三档微信回复。旧评分/固定策略/谈判图/API及旧后端测试保留；没有Git提交，也没有执行旧模块清理。

## 实现

- POST `/api/negotiation/analyze-quote`：只接收request_id、contract_text、landlord_quote、user_goal、context_note，不依赖审查上下文/条款选择。
- GET `/api/negotiation/quote-meta`：独立读取隐私规则和限额；新面板不调用旧meta、turn或proposal。
- 自然段来源保留原文，超800字按标点切分、无标点保底切分，保留段落/片段归属；所有片段完整发模型。
- 查询只用原话/目标/背景，`3×词典命中 + bigram Jaccard`稳定取Top 4，直接读取可信法条JSON，无Embedding。
- 模型只选来源ID及说明，服务器回填原文、标题、链接；精确quote_span、严格Schema、PII、引用、越界内容和已知数值/日程规则在本地检查。失败整卡不展示，无第二次模型调用。
- 三档体面协商/据理力争/坚定维权纵向排列；needs_context仍返回三档澄清回复并展开补充区。真实秒表、复制回退、输入保留和迟到响应/复制归属均已接线。
- 旧演练DOM隐藏并inert，旧JS暂留；右侧可展开所选合同审查解读，合同审查/导入继续可用。

## 文件级改动

以下路径相对仓库根目录。

| 文件 | 改动 |
| --- | --- |
| `backend/app/api/quote_analysis.py` | 新分析/元信息路由、四字段隐私预览、受控错误和容量映射 |
| `backend/app/schemas/quote_analysis.py` | 严格输入/草稿/公开卡片Schema及状态关联 |
| `backend/app/services/quote_analysis.py` | 请求局部模型、单调用、无重试、完整校验与来源装配 |
| `backend/app/services/quote_evidence.py` | 全文分段、无网络法库校验与确定性词法排序 |
| `backend/app/services/quote_prompt.py` | 固定System及结构化User数据，明确三档和引用规则 |
| `backend/app/services/quote_output_guard.py` | 精确片段、引用、PII、威胁语境、日程及数值角色校验 |
| `backend/data/laws/quote_lexicon.json` | 词法召回映射；不替代法律适用判断 |
| `backend/app/main.py` | 注册新路由；旧路由保留 |
| `backend/app/services/model_gateway.py` | 可选调用字符预算；旧默认48000不变，新全文段落ID预算160000 |
| `frontend-web/index.html` | 新面板、合同版本记录、请求/复制隔离、秒表、追问联动；旧UI退出正常操作 |
| `tests/test_quote_analysis.py` | 65项新增离线测试 |
| `scripts/check_quote_panel.cjs` | 当前新面板10组浏览器检查 |
| `scripts/evaluate_quote_analysis.py` | 显式真实云端合成材料检查，无自动重试 |
| `scripts/README.md`、`scripts/check_workspace.cjs` | 新入口说明、旧演练UI检查obsolete标记 |
| `docs/specs/spec-07-quote-analysis.md` | 新模块契约 |
| `docs/specs/spec-00-architecture.md`、`docs/specs/README.md`、`AGENTS.md` | 新旧契约作用范围 |
| `docs/specs/spec-03-negotiation-scoring.md`、`spec-04-negotiation-api-and-scenarios.md`、`spec-05-proposal-drafting.md` | deprecated/兼容说明，不改旧业务公式 |
| `.env.example`、`README.md`、`docs/technical-highlights.md` | 新模型配置及使用流程、历史计划/旧架构边界 |

## 离线与浏览器验证

| 检查 | 结果与范围 |
| --- | --- |
| 改动前pytest基线 | 933通过 |
| 改动前工作台浏览器基线 | 41组通过；仅代表改动前 |
| 最终完整pytest | **998通过**＝933原有＋65新增；1项已有LangChain弃用警告 |
| 新面板浏览器 | **10组通过**，本地Edge＋明确HTTP替身，外部请求0；`browser-results.json` |
| 合同导入浏览器 | **17组通过**，真实本地Uvicorn及Word/PDF解析；无审查/谈判/模型调用 |
| Node语法 | 新检查脚本及页面内联JavaScript通过 |
| Python依赖 | `pip check`通过 |
| 差异检查 | `git diff --check`通过 |

最终pytest命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/quote-complete-pytest -o cache_dir=.runtime/quote-complete-cache
```

新面板覆盖：无审查直发、原话脱敏、IME和双击保护、三档复制/拒绝回退、秒表、needs_context展开、502保留旧结果、428二次确认、在途编辑、历史/编辑合同隔离、跨版本迟到响应/剪贴板，以及1440×900、720×450、390×844、200% reflow。

旧`check_day08_frontend.cjs`/`check_day10_frontend.cjs`经`check_workspace.cjs`运行的演练UI断言不再作为改版后验收。未运行、未迁移的旧装饰/评分/页签检查不称通过；没有删除旧后端测试来换取全绿。早期沙箱不允许回环连接及临时目录，改为有权限的本地离线运行后取得上述结果。

## 真实模型：合成脱敏案例

实际使用当前DeepSeek官方配置，关闭新链路思考模式，每个独立请求一次Chat。不是用户真实微信记录，也不是法律准确率或真人可用性评估。

最后一批20例：**12 success、4 needs_context、2 out_of_scope、2 MODEL_OUTPUT_INVALID**，即18例返回有效结果，2例安全拦截。必须保留这两个失败，不能写成“首轮20/20”。见`live-batch.json`。

两个失败分别涉及：

1. 把同一事实的“押金总额/扣款差额/拟退还”不同详略当成数值矛盾。改为比较明确数值角色，保留真正冲突的拦截。
2. 出现本次所选来源未授权的条号，被正确拦截。Prompt补充C-xxx不是合同第几条的约束，条号校验未放宽；没有将未保存的坏草稿推断为某种已证实的错误成因。

修复后仅单独手动复测这2例，均成功，每例仍一次调用。见`live-retests.json`。将18例原成功输出及2例复测输出统一通过最终校验器和原文回填复验：**20个不同案例均通过最终本地检查**（14 success、4 needs_context、2 out_of_scope）。这是一批加定向复测的结果，不是新的单批20/20。详见[汇总](acceptance-summary.json)。

最后20例整批的观察值：中位3.8475秒，p95 5.144秒；输入39245、输出10281 tokens（含两次受控失败）。这些是该合成小样本/网络/缓存条件下的结果，不是服务时延承诺。

开发中还修复了：默认思考模式耗时/Token开销、内部来源ID泄漏到微信正文、needs_context不完整结构、对房东诉讼说法的客观转述误伤、威胁引述与best_for跨字段误判，以及编造“工作日晚上/周末白天方便”“这两天落实”等可用时间。相应边界已加入离线用例。

开发调试合计92次独立合成云请求，包含多轮手动评估/修复后复测；每个请求调用计数均为1，不是接口内部自动重试。中间结果保留在本机`.runtime`，这里只收录最终批次、定向复测和统计，不发布坏草稿原文。

确定性检查能验证结构、来源身份和已编码的冲突/风险，不能证明法律实质支持、战术标签或所有事实语义正确。姓名/详细地址仍需人工检查；中文数词和复杂事实保持不由正则保证。真实微信材料和更广泛用户评估未进行。

## 演进状态

新模块及界面已实施。旧后端、旧服务、旧测试、单进程限制均保留；未做账号/持久化、部署或Git写入。后续删除旧模块必须作为单独步骤执行。
