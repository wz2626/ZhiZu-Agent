# Day 3 回合 2：真实客户端路径与防幻觉校验实测

日期：2026-10-07（北京时间）。基线 `a774f2b`（Commit #6，本地只读核实），本轮 Commit **待提交**。本报告记录本地离线实测，未发起真实云端 LLM 请求。

## 环境、命令与实际结果

所有 Python/pytest 命令均使用仓库 `.\.venv\Scripts\python.exe`，固定临时目录为 `.runtime/pytest_tmp`。未改 `requirements.txt`，未安装/升级依赖，未使用全局 Python，未执行 Git 写操作。新增测试构造真实 `ChatOpenAI` 客户端并以 `unittest.mock.patch` 拦截 `langchain_openai.ChatOpenAI.invoke`，返回 `AIMessage`；环境使用合成 Key、`.invalid` 地址和模拟检索，不消耗云端 Token。原有本地 Chroma 测试保持离线运行。

鉴于回合 1 已定位受限 Windows 环境中 `TestClient` 本地 `socketpair` 阻塞，两次测试均直接使用受控提升权限运行。本轮未出现该阻塞或代码测试失败，没有将历史问题写成本轮故障。

针对性命令与输出：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp tests/test_review.py
```

```text
........................................................................ [ 72%]
............................                                             [100%]
100 passed in 5.59s
```

全量命令与输出：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

```text
........................................................................ [ 35%]
........................................................................ [ 70%]
...........................................................              [100%]
203 passed in 13.31s
```

两次运行均退出码 **0**，**0 failed、0 skipped、0 warnings、0 errors**。全量为回合 1 的 175 项加本轮新增 28 项；审查模块为原有 72 项加本轮新增 28 项。没有设置忽略 warning 的过滤参数。

## 针对性覆盖

| 项目 | 实测行为 |
| --- | --- |
| 实际 SDK 调用路径 | 使用真实 ChatOpenAI 对象、temperature=0.1、max_retries=0；invoke 被 patch，合法 JSON 首次成功 |
| Prompt 与脱敏 | 系统包含中国合同法务角色、No-Markdown 和押金依据边界；人类消息仅含脱敏文本、当前 law_id 及法条正文；top_k=8 传递给检索 |
| 完整围栏清洗 | 普通首尾空白、json 围栏、无语言围栏均首次通过；原句内部的 json 和反引号字符保持精确不变 |
| 三次乱码 | 三个 AIMessage 均引发 JSON 解析失败；invoke 恰好三次、检索一次、最后消息含两次重写指令；结果为 Mock |
| 防篡改 | 改写原句被拒绝，下一次修正可成功；连续三次篡改后 Mock；成功原句仍为脱敏文本精确子串 |
| 引用交集 | LAW-999、场景 ID 和合法但未召回的 LAW-712 被剔除；混合引用仅保留 LAW-716，并保序去重，无额外生成 |
| HIGH 无依据 | 空引用、仅 LAW-999、仅未召回 LAW-712、仅场景 ID 均一次生成后直接 Mock，响应中没有伪造引用 |
| 较低风险 | MEDIUM/LOW/NONE 也移除未知引用，总风险数保持按等级计算；过滤不改写模型原定等级，语义充分性未由此验证 |
| 清洗边界 | 字符伪前缀、缺尾围栏、其他语言围栏、开场白、结束语、多个数组、单反引号不被宽松清洗“修复”，三次后 Mock |
| 严格 JSON | NaN、Infinity、-Infinity 及重复 risk_level 键全部拒绝，最多三次后 Mock |
| 既有回归 | 无 Key Mock、输入 422、分数过滤、真实本地 Chroma 串联、资源释放、API、健康及知识库测试继续通过 |

原有三个“未知引用触发重写”的参数化断言依据本轮明确要求调整为引用类型错误测试；其原问题由新增的引用过滤及 HIGH 兜底用例继续覆盖。所有异常模型输出均为**故障注入**，不是实际云端返回。

## 实现口径与未验证项

保留用户指定的 ``.strip().strip('`').strip('json').strip()``，但只在识别到完整外层数组围栏后执行，防止 `strip('json')` 的字符集合语义误收损坏文本。普通 JSON 只去首尾空白。Prompt 要求无围栏，解析容错接受完整围栏；不抽取含前后说明的局部 JSON。

结果经 Pydantic、脱敏原句精确定位、引用交集及敏感数字检查；无引用 HIGH 直接 Mock，JSON/结构/定位失败保持最多重写两次。最终 Mock 出口按用户本轮显式要求沿用；完整图 `needs_review` 契约未改。引用属于召回列表不等于已验证法律语义支持，完整语义 Critic 仍待后续实现。

本轮未验证真实 SiliconFlow 连接、有效 Key、计费、模型输出质量、Prompt 云端对照效果或完整 LangGraph。没有运行真实线上演练，也没有把拦截测试称为已接通云端算力。

## 清理与工作区

收尾先核验 `.runtime` 及两个目标目录不是重解析点，确认目标绝对路径位于本仓库，再使用原生 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 清理 `.runtime/pytest_tmp` 和 `.runtime/pytest_cache`。普通权限清理成功，退出码 0，两项 `ExistsAfterCleanup` 均为 False；未处理其他 runtime 目录或旧 `.pytest_cache`。

`git --no-optional-locks diff --check` 退出码 0，无空白错误。Git 对已修改文件给出未来 LF → CRLF 的换行提示，这不是 pytest warning；未因此修改 Git 配置。

最终使用 `git --no-optional-locks status` 和 `git --no-optional-locks status --short --untracked-files=all` 核对，共 **5 个变更文件**（3 个修改、2 个新增）：

```text
 M backend/app/services/review.py
 M docs/prompt-history/chain-02-risk-review/README.md
 M tests/test_review.py
?? docs/prompt-history/chain-02-risk-review/day03-round02-real-llm.md
?? docs/test-results/day03-round02.md
```

`requirements.txt`、Spec、API 路由、Schema、场景文件及《进度记录》均未改动；未暂存、提交或推送。
