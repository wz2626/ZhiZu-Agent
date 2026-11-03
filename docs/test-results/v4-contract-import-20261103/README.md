# Word/PDF 合同导入验证（2026-11-03）

本文为初版历史结果；后续核实的两个P1及三项P2已修复，当前结果与反例验收见[审阅修复报告](../v4-contract-import-fixes-20261103/README.md)。

## 实现与结果

独立`POST /api/contracts/parse`、Word/PDF按钮与拖入、本机脱敏后回填、成功后单卡替换确认、超限完整回填、扫描页防漏审已完成。采用python-docx 1.2.0 / pdfplumber 0.11.10 / pdfminer.six 20260107 / python-multipart 0.0.33，见[Spec 06](../../specs/spec-06-contract-import.md)。

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| 改动前Python基线 | 863 passed | 本次命令输出 |
| 改动前及接入后Day8 | 各41组通过 | 本机`.runtime/contract-import-baseline-evidence`、`.runtime/contract-import-regression-evidence` |
| 全量Python | 910 passed，1项既有LangChain弃用警告，0失败 | [最终输出](pytest-final.txt) |
| 新增导入Python | 47 passed，已包含在910项内 | `tests/test_contract_import.py` |
| 完整本机工作台回归 | 103组通过，0失败/跳过 | [JSON](workspace-verified/day10/browser-results.json) |
| 新增真实导入浏览器 | 11组通过 | [JSON](browser-final/results.json) |
| 依赖一致性 | pip check无冲突 | 本次命令输出 |

Python测试禁止外网；浏览器使用真实本机FastAPI及解析器，审查/草稿仍为显式模型替身，谈判为真实固定规则图。本轮未调用真实云模型，未做真人可用性或法律语义质量评估。

## 业务与工程验收

- 5001～20000字符完整返回；20001字符返回422 TEXT_TOO_LONG。浏览器6014字样本保留合同尾部并禁用分析；不足10字提供明确提示。
- Word顺序提取段落、编号和表格，合并单元格不重复；PDF通过bbox排除表格区域重复正文，金额2500元仅出现一次。
- 纯扫描返回SCANNED_DOCUMENT；混合PDF返回INCOMPLETE_EXTRACTION并标明第2页，不返回局部正文，不覆盖当前编辑内容。
- 全角、分组空格/跨行号码先脱敏再回填；通过实际textarea value setter验证没有原始号码赋值。金额日期保留。
- 上传期间编辑、单卡替换/放弃、示例切换、取消、IME、迟到响应均不错误覆盖或自动分析。
- 导入浏览器所有POST均为解析接口，proposal_model_calls=0、real_cloud_calls=0、blocked_external_calls=0。
- 1440×900、720×450、390×844及200%缩放无根页面溢出；主分析动作可在合同面板内滚动到达。原工作台103组保留Composer、版本、条款与练习隔离。
- 实际10MiB有效Word通过TestClient；真实Uvicorn HTTP接收2MiB有效Word，未被1MiB spool阈值错误拒绝。
- 文件10MiB/请求11MiB、无Content-Length分块超限、重复文件、额外字段、错误扩展名及格式伪装均有受控出口。
- 截断、断连和超限时临时文件关闭恰好一次；缺终止boundary时在解析器仍持有临时资源期间拒绝。
- 覆盖AnyIO等待者取消、原生等待者/任务取消、启动前取消、默认线程容量排队时取消、接管失败。运行中不提前关闭文件或归还槽位。
- 覆盖ZIP条目限制、DTD/实体拒绝、修订正文、Office加密容器、51页PDF、损坏PDF及AcroForm拒绝。
- Node执行实际浏览器脱敏函数，与Python报告一致；正负例包含金额日期、表格、12位串、空行、逐字空格及5000空白。

## 样本测量

[原始记录](sample-measurements.json)。当前Windows环境每例单次，tracemalloc会增加耗时；峰值只包含Python追踪分配，不是进程RSS/原生库峰值，也不是生产吞吐量结论。

| 合成样本 | 结果 | ms | Python峰值MiB |
| --- | --- | ---: | ---: |
| 号码/表格Word，约36KiB | success | 152.35 | 2.33 |
| 中文表格PDF | success | 170.51 | 11.91 |
| 2MiB有效Word | success | 92.32 | 1.20 |
| 6014字Word | success，完整返回 | 122.29 | 2.20 |
| 混合扫描PDF | INCOMPLETE_EXTRACTION | 25.54 | 0.59 |

## 截图

2026-11-03按开发者要求整理：本轮历史截图和中间附件已移入本机忽略归档`.runtime/evidence-tidy-20261103.zip`，包内保持原仓库相对路径；原始README快照在`_context/`。本文测试结论不变，最终日志、机器结果JSON及样本测量仍在本目录。当前关键截图见[审阅修复报告](../v4-contract-import-fixes-20261103/README.md#保留附件与归档)，不将后续截图冒充初版实测。整理清单见[未提交修改整理](../cleanup-20261103.md)。

## 发现并修正的问题

1. 沙箱限制Windows回环使初始pytest停滞；停止后在允许本机回环的环境执行，fixture仍禁止外网。依赖网络查询也在允许网络后完成。
2. 大字节串默认pytest用例ID使Windows路径过长，改为短ID。
3. 原Python/浏览器规则升级替身仍替换旧模式，迁移为替换共享separator_pattern并同步边界；保留兼容升级与再次确认的原业务断言。
4. 测试服务器READY打印早于listen，增加健康就绪等待；早期`browser/failure.json`已转上述本机归档。
5. 手机摘要换行裁切：元信息区不收缩，提高编辑表面最小高度后复验。`workspace-regression/`的失败诊断和中间截图已归档；最终结果仍以保留的`workspace-verified/day10/browser-results.json`为准。

## 复现

仓库根目录执行，浏览器脚本需要Node/Windows Edge；使用新的空输出目录，脚本不会覆盖非空历史证据：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
node scripts/check_contract_import.cjs --out .runtime/import-recheck-evidence --runtime-dir .runtime/import-recheck-browser
node scripts/check_day10_frontend.cjs --out .runtime/workspace-recheck-evidence --runtime-dir .runtime/workspace-recheck-browser
```

## 运维与限制

解析无需云端Key，分析仍需原配置。更新后重启后端、刷新网页，让路由和规则同时生效。原文件仅在处理期使用内存/系统临时文件，不保存至静态资源或证据目录；测试文件均为合成数据，留在本机忽略目录。

没有OCR；扫描检测是启发式，不能证明发现所有图片条款。Word修订/内容控件/文本框/未支持编号、复杂多栏、交互PDF表单保守拒绝。页眉页脚、图片文字、姓名地址和逐字分隔号码须人工核查。本轮未执行Linux净室安装、公网代理验证或真实恶意文档压力测试。

最多两个线程任务，20秒为协作期限，不能强制中断库调用，不提供硬内存隔离。两线程卡死可能需人工重启；重启清空练习会话与审查上下文，不自动重启或补线程。

未执行Git提交、分支切换或其他Git写操作，保留工作区原有修改。
