# Day 7 回合 1：确定性规则算分与状态原子提交实测报告

日期：2026-10-11（北京时间）。代码基线 `287687a`（Day 6）；Day 7 代码待提交。契约见 [Spec 00](../specs/spec-00-architecture.md) 与经用户授权新增的 [Spec 03](../specs/spec-03-negotiation-scoring.md)。

本报告在开发完成后，根据同一聊天中实际执行的命令、工具返回及现有测试断言补录。**本次仅补文档，没有重新运行 pytest，也没有修改代码。** 工具结果摘录不是独立保存的原始日志附件；开发阶段没有另存 Day 7 的 JUnit 或完整 pytest 输出文件。相关 [Prompt 转录与演进记录](../prompt-history/chain-02-graph-critic/day07-scoring.md) 待补完整原始聊天导出。

## 范围与测试结果

实现纯 Python 规则算分、离线房东明确确认模板提取、候选试算、Critic 数值及证据核验、通过后原子提交。既有审查模块保持只读；原有 291 项测试逻辑不变，在 `test_negotiation.py` 末尾追加 Day 7 测试，并新增 `test_scoring.py`，合计新增 85 项。

执行目录为 `D:\AgentDev\ZhiZu-Agent`，均使用仓库 `.\.venv\Scripts\python.exe`。下表只列已完成运行；受限环境中断的全量基线另列于后文。

| 验证阶段 | 工具返回结果 | 退出码 |
| --- | --- | --- |
| 修改前 Day 6 谈判测试 | 24 passed，1 warning，0.41 秒 | 0 |
| 首批算分及谈判边界测试 | 108 passed，1 warning，0.82 秒 | 0 |
| 首次完成的全量回归 | 375 passed，1 warning，16.78 秒 | 0 |
| 布尔权重序列化修复后的专项回归 | 109 passed，1 warning，0.81 秒 | 0 |
| 最终全量回归 | **376 passed，1 warning，16.07 秒** | **0** |

最终全量为 **291 项既有测试 + 85 项新增测试 = 376 项**，0 failed、0 errors、0 skipped。唯一警告为既有 LangGraph 依赖的 `LangChainPendingDeprecationWarning`，位置 `.venv/Lib/site-packages/langgraph/cache/base/__init__.py:8`，提示 `allowed_objects` 的默认值将改变；本轮没有屏蔽警告或修改依赖。

最终专项命令：

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_scoring.py tests/test_negotiation.py -q --basetemp=.runtime/day07/boundaries_final -o cache_dir=.runtime/day07/cache
```

实际工具结果行摘录：

```text
109 passed, 1 warning in 0.81s
```

最终全量命令（受控提升权限运行）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=.runtime/day07/full_final -o cache_dir=.runtime/day07/cache
```

实际工具结果行摘录：

```text
376 passed, 1 warning in 16.07s
```

## 算分公式与除零保护证据

规则来自 [scoring.py](../../backend/app/services/scoring.py)，断言来自实际通过的 [test_scoring.py](../../tests/test_scoring.py)。单项先计算 `p = clip((confirmed - start) / (target - start), 0, 1)`，再计算 `round(100 * p)`。多项计算 `round(100 * Σ(w_i * p_i) / Σw_i)`，仅包含有确认值、标记适用、非退化且权重为有限正数的项目。采用有理数运算和 Python 半偶舍入，不先对各项分数舍入。

| 通过的测试 | 实际输入与断言 |
| --- | --- |
| `test_deposit_formula_and_clipping`（6 个参数） | 起点 0、目标 2000；确认值 -100/0/1000/1500/2000/3000 分别得 0/0/50/75/100/100，单项与汇总函数结果一致 |
| `test_equal_target_and_start_is_inapplicable`（4 个参数） | 起点与目标均为 0，确认值 -1/0/1/2000；`progress`、单项分数和仅含该项的总分均为 `None`，不执行零分母除法 |
| `test_missing_disabled_and_degenerate_rules_do_not_enter_denominator` | 正常项确认 50、目标 100，其余项分别缺失、禁用或目标等于起点，权重为 99；总分仍为 50，证明这些项未进入分母 |
| `test_no_applicable_items_is_unscorable`（3 个参数） | 空规则、空确认状态或只有未知项，均返回 `None`，不伪造零分 |
| `test_weight_normalization_is_scale_invariant`（4 个参数） | 两项进度分别为 1 和 0；共同权重缩放为 0.001/1/100/1e308，总分均为 50，无权重求和溢出 |
| `test_unequal_weights_and_decreasing_goal` | 权重 1:3、进度 1:0 得 25；两项进度均为 0.5 得 50，其中一项目标低于起点 |
| `test_aggregate_unrounded_progress_before_rounding` | 两项起点 0、目标 1000，确认值 4 和 8，原始进度均值对应 0.6 分，统一舍入得 1 |
| `test_invalid_weights_do_not_enter_denominator`（6 个参数） | 0、负数、NaN、正无穷、布尔值和字符串权重均被排除；仅剩无效权重项时返回 `None` |
| `test_same_state_same_score_and_inputs_are_not_mutated` | 同一确认状态重复计算 10 次均为 50；附带重复法条不参与公式，输入字典保持不变 |
| `test_fractional_amount_and_large_numbers_do_not_overflow` | 小数 0.3、起点 0.1、目标 0.5 得 50；确认值 `10**400`、目标 `2 * 10**400` 也得 50 |

算分函数的裁剪与 Critic 的底线是不同边界：纯公式对超范围进度裁剪，谈判提交则按可信规则的 `minimum/maximum` 拒绝越界候选。布尔值、字符串、NaN 和无穷不能充当有效确认金额。

## 提取、Critic 与原子提交证据

下表来自实际通过的 [test_negotiation.py](../../tests/test_negotiation.py)。响应器、伪造候选和错误引用均为明确的离线测试替身或故障注入，不是云端模型实测。

| 通过的测试 | 实际通过的断言 |
| --- | --- |
| `test_day07_deposit_demo_recomputes_50_then_75` | 房东先明确确认返还 1000，再确认 1500；确认状态与正式分数分别为 1000/50、1500/75，两轮后候选已清空 |
| `test_day07_unilateral_ambiguous_or_duplicate_statements_are_not_terms`（7 个参数） | 未确认、否定、条件句、转述、待审批、冲突金额或重复金额均不能成为确认条件；租客要求 2000 并重复引用法条仍不获得分数 |
| `test_day07_invalid_amount_or_bottom_line_never_commits`（6 个参数）、`test_day07_custom_bottom_line_rejects_otherwise_valid_offer` | 非法金额与越界候选最多尝试 3 次后返回 `needs_review`，正式条件、轮次和分数不变；自定义最低返还 1200 时拒绝 1000 |
| `test_day07_invalid_duplicate_or_unretrieved_evidence_rejects_entire_round`（5 个参数） | 同轮重复引用、越界法条或不属于本次可信集合的引用导致整轮拒绝，不能只保留金额提交 |
| `test_day07_fabricated_terms_confirmation_or_evidence_cannot_commit`（5 个参数） | 候选金额与房东回复不一致、缺确认、未知数值项、伪造引用或遗漏回复中的确认值均被拒绝 |
| `test_day07_failed_trial_preserves_previously_committed_score_and_state` | 已提交 1000/50 后试算 1500/75；重复证据使 Critic 失败，响应中的候选分为 75，但正式分仍为 50，条件、历史、轮次及正式会话快照保持原样 |
| `test_day07_internal_retries_score_only_final_valid_candidate`（3 个参数） | 失败 1/2 次后只提交最终有效的 1000/50；失败 3 次不提交。重试计数最多为 2，失败候选的证据不会带入成功结果 |
| `test_day07_repeated_confirmation_and_cached_request_never_add_points`、`test_day07_repeated_evidence_across_rounds_is_deduplicated_without_points` | 同请求 ID 回取缓存不再执行响应器；不同请求重复确认同金额仍为 50。跨轮法条去重，引用次数不产生分数 |
| `test_day07_critic_recomputes_score_instead_of_trusting_trial` | 故障注入候选试算分 99，Critic 仍根据确认值重新计算正式分为 50 |
| `test_day07_equal_target_or_no_rules_produces_unscorable_confirmed_state` | 可信规则起点与目标均为 1000 时，允许确认 1000，但正式分为 `None`；无规则的数值候选被拒绝 |
| `test_day07_scored_sessions_and_concurrent_repeated_requests_remain_isolated` | A、B 两会话各有四个并发重复请求；A 为 1000/50，B 为 1500/75，各自只提交一轮 |
| `test_day07_response_adapter_receives_detached_state` | 响应器尝试修改确认状态和清空规则，不能影响图内正式工作状态 |
| `test_day07_graph_roundtrip_never_coerces_invalid_weights_into_points` | 布尔权重经图状态序列化后仍为布尔值；两次确认 1000 都返回不可评分，不会被转换成有效数字权重 |

## 实际发现与修复

首次全量 375 项通过后，开发自查发现纯评分函数排除布尔权重，但 Pydantic 在图状态反序列化时可能将 `True` 转成 `1`。同聊天只读复现命令构造 `ScoringRule(0, 100, weight=True)`，先读取直接状态，再读取 `NegotiationState.model_validate(s.model_dump())`，实际输出为：

```text
bool True
int 1
```

这是真实发现的类型转换缺陷，不是用户报错，也不是人为制造的测试失败；当时已完成的 pytest 没有断言失败。随后在 Schema 中先重建规则对象，保留原始值及规则边界，并追加上述图往返回归测试。专项增至 109 项、最终全量增至 376 项并全部通过。本次补档未进行代码修复。

## 执行障碍、边界与收尾

受限环境中的全量基线命令长时间没有输出，已中断，退出码 1；该次没有测试结论，不计入通过数字：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=.runtime/day07/baseline -o cache_dir=.runtime/day07/cache
```

随后受控提升权限的两次全量运行完成。阻塞现象与 Day 6 记录相似，但本轮没有取得根因调用栈，不将其写成已确定的底层原因。

本轮没有调用真实云端模型；房东条件提取只覆盖离线明确确认模板。证据校验覆盖引用身份、本次可信集合和回复一致性，不表示法条实质支持已经完成语义验收。分数标为“模拟协商进展分”，不代表现实房东接受概率或法律结论。会话隔离仍限于单进程内存服务。

开发收尾已用只读 Git 和原测试前缀比较确认既有测试逻辑、审查模块未改变，`git --no-optional-locks diff --check` 通过。校验清理路径后删除本轮 `.runtime/day07`，实际输出 `Day07TemporaryDirectoryExists: False`，并执行 `git --no-optional-locks status`；当时仅有 7 个 Day 7 交付文件变更，未暂存、未提交。

用户在本次补档请求中转述 Kimi 审计认可算分、376 项测试及隔离边界；未收到审计原件，不将转述冒充独立复核材料。[Day 6 实测报告](day06-round01.md) 已存在，本次无需补建。此次新增变更仅为本报告、Day 7 Prompt 记录和该链 README；此前 Day 7 代码与 Spec 的未提交状态予以保留。

本次补档前后，对 `rg --files -g '*.py'` 列出的 31 个 Python 源文件逐一比较 SHA-256，文件集合与哈希全部一致。三份文档的 18 处本地链接均可解析，`.runtime/day07` 仍不存在；本次没有生成新测试缓存。只读核实 Day 6 提交 `287687a` 后，仅在本链 README 回填，历史 Day 6 报告不作改写。
