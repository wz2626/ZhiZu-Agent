# Spec 07 联合CR修复与最终验证（2026-11-04）

附件精简（2026-11-06）：本历史阶段保留报告和汇总JSON，原始批次/复测JSON、浏览器结果及截图已校验SHA-256后转存本机忽略归档 `.runtime/precommit-cleanup-20261106/historical-attachments.zip`，不随本次提交分发。下文原始文件名指该归档中的条目，历史数字及失败记录不变。最新完整公开证据见[可用性复核](../quote-analysis-readiness-20261104/README.md)。

历史阶段记录：后续复审复现了9条新增句式的误杀，已在[可用性复核补丁](../quote-analysis-readiness-20261104/README.md)中修复；当前结果以该报告为准。本页保留当时测试与失败记录，不代表所有语境均已覆盖。

本轮按开发者给出的Kimi/DeepSeek联合CR与五项拍板修复。报告指出的状态绑定、基础词表、合法转述误杀和前端状态问题成立；首版Spec示例和正常fixture也错误允许了success+unclear，本轮一并纠正。工作区保留此前未提交修改，无Git写操作、无旧评分模块清理。

## 1. 五项修复

| 要求 | 实施与证据 |
| --- | --- |
| 状态强绑定 | `schemas/quote_analysis.py`在草稿及公开响应检查；`services/quote_analysis.py`发布前独立复查；前端同样拒绝矛盾。supported/unsupported→success＋0追问；unclear→needs_context＋1～2追问。违反502，不自动改状态或补追问。正常单测/浏览器fixture改为合法状态，另设明确负例。 |
| 押金词表及精度 | 补押金/保证金/退还/返还/归还/扣款/扣减/违约金/赔偿/退租/解约。只有词典命中才入选，bigram只排序，保留稳定Top 4；不靠重合度填满。法条仍是候选，不能冒充一般押金退款或违约金标准。 |
| 正当反驳不误杀 | 只对reply.text扫描威胁/虚构行动，best_for不参与；其Schema、PII及纯文本检查保留。支持原话精确片段的有/无引号归因、明确否定、防御性条件句、引用名词结构及后置反对。只屏蔽被证实的片段，逗号、转折、租客新意图结束归因；随后威胁仍拦截。 |
| 前端 | 防抖key为记录唯一maskKey＋field，避免跨字段取消及对象统一字符串化；组合输入只延后当前字段，不阻塞其他字段遮蔽。out_of_scope清空卡片/快照/复制回退并使旧复制回调失效。原话原生maxlength=2000。 |
| 输入定界 | 新`core/model_payload.py`使用tenant_input、landlord_quote_data标签，内容仍是JSON；用户提供的尖括号和&转义，不能成为实际闭合标签。网关还原数据后照常递归检查PII，旧JSON入口不变。标签不替代输出校验，也不声称能彻底免疫语义注入。 |

额外处理：合同段首尾空白不再strip；合同条号提示保持原文中文/数字写法；结果卡片可聚焦且沿用role=status生成通知；旧Day08/Day10浏览器入口明确打印SKIP并退出，不再隐式调用失效断言。

安全内容拒绝与其他输出拒绝分别为HTTP502 `MODEL_OUTPUT_UNSAFE`、`MODEL_OUTPUT_INVALID`；前端显示不同受控提示，均不公开坏草稿，也不自动重试。

## 2. 状态契约验证

对success/needs_context × supported/unsupported/unclear × 0/1/2/3条追问执行24项矩阵，验证：

- FastAPI公开结果与上述允许组合一致，违例为502且没有card。
- 发给模型的JSON Schema（allOf条件）与运行时校验一致。
- 即使测试替身绕过输出guard，服务发布前仍拒绝success+unclear。
- 前端收到故意构造的success+unclear时拒绝接纳，不覆盖上次合法卡片。

模型曾先输出success，随后才输出unclear。Prompt和内部草稿Schema调整为先生成assessment/追问、最后决定status；这只是生成顺序指导，JSON接口字段顺序不受限制，服务硬拒绝没有放宽，也没有事后修改模型状态。

## 3. 检索实测

| 查询 | 候选LAW-ID |
| --- | --- |
| 押金全扣 | 710、711、714 |
| 押金不退 | 710、711、714 |
| 退还押金 | 710、714、711、733 |
| 维修费用 | 713、712（不再混入纯bigram命中的704） |
| 当事人应当按照约定 | 空，不凭通用措辞凑法条 |

以上为本地词法候选，不等于这些条文直接支持该纠纷结论。库范围仍为租赁合同703～734条，未扩库、未调用Embedding。

## 4. 最终离线与浏览器回归

| 检查 | 结果 |
| --- | --- |
| 修复前新模块基线 | 65通过 |
| 修复后新模块 | **141通过**；较原模块新增76项 |
| 完整pytest | **1074通过，0失败/错误**，1项已有LangChain弃用警告；保留原有后端测试 |
| 新面板浏览器 | **17组通过**；本地Edge＋明确HTTP替身，无外部请求；`browser-results.json` |
| 真实Word/PDF导入浏览器 | **17组通过**；真实本地API，不调用模型；`import-results.json` |
| 旧Day08/Day10入口 | 明确SKIP，未执行检查；不计为通过 |
| 内联JS/检查脚本语法、pip check、diff check | 通过 |

最终完整回归使用项目内独立可写目录，避免CR环境中的默认tmp_path权限错误：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/quote-cr-closed-schema-pytest -o cache_dir=.runtime/quote-cr-report-cache
```

浏览器新增覆盖：不触发blur快速改背景/目标的双字段号码遮蔽；另一个字段处于中文组合期仍遮蔽原字段；不同合同记录防抖不冲突；原生输入2001字被限制在2000；拒绝矛盾状态；范围外清卡及复制回退；安全错误单独提示。保留原请求恢复/隐私预览、秒表、追问、复制、迟到响应与四种尺寸检查。

安全正反例包括：

- 可通过：您说否则就断水断电，这一点我不能接受；您刚才说后果自负，我不能接受。
- 可通过：如果对方找人堵门，我会立即报警并保留证据；不能保证胜诉；不能认定一定违法。
- 可通过：best_for为“对方声称已起诉时”或包含威胁词（不作为拟发送正文扫描）；PII和Markdown仍被拒绝。
- 拦截：先归因引用，随后“我会找人堵门”；“我不同意，否则就断水断电”；双重否定保证；把对方原话作为自己的威胁采用。
- 注入对照：用户输入闭合标签、system标签及转义文字不能形成新的真实边界；解码保留原文，标签内号码在出云前被拦截，伪造来源仍为502。

## 5. 真实模型验证与保留失败

本轮没有收到联合CR所称的原始20条真实微信数据文件。因此独立云端复验使用脚本内20条**合成脱敏案例**，不能称为复跑了对方的真实语料。每个独立请求一次模型调用，无Embedding、无自动重写/重试。

最新整批：`live-batch.json`，**4 success、13 needs_context、2 out_of_scope、1受控安全拦截**。19例有效输出的状态/立场/追问全部一致，未发布success+unclear。整批中位4.477秒、p95 5.404秒，仅为本次小样本条件下的观察值。

剩余安全拦截涉及对原话中“我就堵门/后果自负”的合法回述。定向复测第一次仍遇到“您以堵门和后果自负要求我交钱”的并列归因形式，被拦截；据此补充精确片段的并列归因规则，并加入逗号后租客新威胁不能被豁免的反例。最后一次定向复测成功，为needs_context＋unclear＋2追问，三档回复完整。见`live-retest.json`。

将最新批次19例有效输出与最后定向复测统一通过最终校验器和原文映射复验，**20个不同案例均符合最终输出契约**。这是整批＋修复后复测的结果，不能写成“单批20/20”。逐例状态及检查见[summary.json](summary.json)。不据此宣称法律准确率、真人实用性或正则能覆盖所有语境。

开发过程中共65次独立合成云请求（包含两批探索、三个状态生成顺序探针、一批最终20例和两次定向复测），每个请求调用计数均为1。中间失败保留在本机.runtime；公开归档剔除了失败输出的诊断原文片段，只保留受控类别/状态/计数。没有通过隐藏失败或增加接口内部调用次数取得结果。

## 6. 文件级范围与兼容

路径相对仓库根目录：

| 文件 | 本轮改动 |
| --- | --- |
| `backend/app/schemas/quote_analysis.py` | 状态绑定、公开响应复查、模型条件Schema及生成顺序 |
| `backend/app/services/quote_analysis.py` | 发布前硬复查、区分安全拒绝错误 |
| `backend/app/services/quote_output_guard.py` | 精确归因/否定/防御上下文及攻击性对照，best_for排除 |
| `backend/app/services/quote_evidence.py`、`backend/data/laws/quote_lexicon.json` | 命中门槛、高频词及原文空白保留 |
| `backend/app/core/model_payload.py` | 新标签编码/解码与用户闭合标签转义 |
| `backend/app/services/quote_prompt.py`、`model_gateway.py` | 定界数据、状态条件指导、兼容隐私预检 |
| `frontend-web/index.html` | 分字段/记录/组合输入遮蔽、清卡、长度、状态拒绝及错误提示 |
| `tests/test_quote_analysis.py` | 141项新模块回归 |
| `scripts/check_quote_panel.cjs`、`evaluate_quote_analysis.py` | 合法正常fixture、负例、前端时序、模型状态/召回诊断 |
| `scripts/check_day08_frontend.cjs`、`check_day10_frontend.cjs`、`scripts/README.md` | 旧入口明确跳过 |
| `docs/specs/spec-07-quote-analysis.md`、README与测试索引 | 修复契约及本报告 |

旧scoring/practice_policy/谈判图/旧API保留；本轮没有新改AGENTS.md或实际.env，已有未提交修改不回滚，不进行Git提交。合同条号仍要求原文写法，不宣称中文/阿拉伯数字已经互通。后续清理旧模块和扩大真实语料评估属于独立步骤。
