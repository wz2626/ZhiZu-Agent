# 合同导入审阅修复（2026-11-03）

## 结果

修复确认卡后再编辑被覆盖、大图误报扫描、清洗名单、当次遮蔽提示、任务接管异常五项。提取策略升级为`doc-extract-v2`，[Spec 06](../../specs/spec-06-contract-import.md)已同步。原[初版910项/11组报告](../v4-contract-import-20261103/README.md)保留为历史，不用旧通过记录替代本轮反例验收。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 最终全量Python | **933 passed**，0失败，1项既有LangChain弃用警告 | [原始输出](pytest-final-verified.txt) |
| 定向Python三组 | **90 passed**（包含在933项中） | `test_contract_import`、`test_http_contract_and_cleanup`、`test_v4_interaction`本次输出 |
| 真实导入浏览器 | **17组通过** | [结果](browser-final/results.json) |
| 完整工作台回归 | **103组通过**，0失败/跳过 | [结果](workspace/day10/browser-results.json) |
| 依赖、语法、空白检查 | pip check无冲突，Node语法及diff --check无错误 | 本次命令输出 |

导入通过真实本机FastAPI/解析器；工作台审查与草稿使用显式模型替身，谈判为真实固定规则图。导入测试POST只有`/api/contracts/parse`，真实云调用、草稿模型调用、被阻止的外网尝试均为0。没有运行真实云模型评估或真人可用性评估。

## 五项修复与对应证据

### 1. 确认卡修订保护

新增`confirmRevision`，表示当前确认卡展示时的正文修订，与上传起始revision分开。卡片出现后再编辑，点击替换只更新同一卡片的说明及确认基线，原文和候选都保留；下一次明确点击才替换。重复编辑仍重复保护，不会因为第一次点过就绕过检查。上传期间编辑已纳入首次卡片基线，卡片出现后未再改动时只需确认一次。

真实浏览器覆盖：出现卡片→编辑→替换不覆盖→再次编辑→替换仍不覆盖→不再编辑并确认→成功；另覆盖上传期间编辑、一次确认成功，以及原有放弃/IME/迟到响应流程。

[正文保留与再次确认截图](browser-final/confirmation-revision-preserved.png)。

### 2. PDF大图分层判定

不再把“大图内部缺少文字”直接当作扫描。结合正文/图片相对位置、可读文字层及有界栅格信号检查。可读取正文配大装饰图可成功，并始终提示图片文字未提取；短正文配可检查图形也不直接判扫描。页眉文字不计为可读正文，扫描页仍整份拒绝。

新增`pdf_images.py`，使用已有Pillow依赖作本机小图排布检查：源图最多400万像素、编码数据10MiB、256×256灰度采样；Flate有界解压，不能调用无界get_data解压。疑似多行文字的大图、未知编码、超预算、透明/蒙版/显式Decode等未支持图像均不因为外部字多就放行。已有可读文字层覆盖图片时正常提取。

测试矩阵：JPEG/Flate的220字正文+500×500大图成功；短正文+大图成功；只有边缘字的扫描图拒绝；约18%页面面积的扫描正文也不能被页眉字掩盖；220字正文+图片补充协议拒绝并给页码；未知滤镜/超像素预算/未支持合成标志不误放；已有文字层的图文PDF成功。JPEG/Flate均使用真实文件读取，未模拟解析器结果。

[大图成功及图片提示](browser-final/large-logo-accepted.png)。检查是启发式而非OCR，不能证明图片没有条款，倾斜/低对比/少行文字仍可能无法可靠分类；用户须核对图片，未知大图保守拒绝。

### 3. 清洗名单

明确去除U+FEFF BOM、U+200B零宽空格、U+2060 WORD JOINER、U+00AD软连字符及原Cc控制规则；保留LF/TAB。不删除整个Cf类别，保留ZWNJ/ZWJ等有语义字符，测试姓名连接和emoji不受损。验证清洗幂等、金额不改、前端回填无BOM/ZWSP。

### 4. 本次遮蔽提示

成功提示使用本次候选计数加应用时终扫新增计数，分别报告手机号/身份证号；不使用历史累计maskCounts。Word隐藏1处手机号和1处身份证后，再导入无号码PDF，明确显示本次未发现规则可识别号码。新上传开始清除上一导入的提示；不把“无匹配”等同没有个人信息。

[本次计数截图](browser-final/01-word-redacted.png)。

### 5. 接管异常

先登记job，使用关闭的启动门阻止执行，再创建任务和完成回调，最后开门返回。任一步失败均禁止工作、撤销注册、取消已创建任务；文件和槽位保持由路由唯一清理。不能把取消的Task当成实际线程结束。

故障注入覆盖集合已add后抛错、create_task抛错、回调登记前抛错、回调已登记后抛错，验证工作0次、文件关闭1次、槽位恰好恢复、jobs无残留。另验证eager任务工厂也不能在接管前启动，以及原生/AnyIO取消、启动前/排队取消等旧用例。

## 保留附件与归档

2026-11-03按开发者要求精简待提交附件，保留本报告、最终933项日志、17组导入与103组工作台JSON，以及以下12张代表截图。其他重复截图和中间输出移至本机忽略归档`.runtime/evidence-tidy-20261103.zip`，保留原路径、SHA-256清单和原README快照；没有改写历史验收结论。见[整理记录与恢复方法](../cleanup-20261103.md)。

| 范围 | 保留截图 |
| --- | --- |
| Word/PDF及隐私 | [Word脱敏与本次计数](browser-final/01-word-redacted.png)、[PDF表格](browser-final/02-pdf-table.png) |
| 防漏审与超限 | [混合扫描拒绝](browser-final/03-mixed-scan-rejected.png)、[保留超限全文](browser-final/04-full-over-limit.png) |
| 本轮P1修复 | [确认后编辑保护](browser-final/confirmation-revision-preserved.png)、[大装饰图](browser-final/large-logo-accepted.png) |
| 导入与布局 | [拖拽](browser-final/05-drop-hover.png)、[手机](browser-final/layout-390-1.png)、[200%重排](browser-final/layout-1440-2.png) |
| 工作台闭环 | [桌面结果](workspace/day10/clarity-final-result-1440.png)、[手机结果](workspace/day10/clarity-final-result-390.png)、[处理详情抽屉](workspace/day10/app-shell-trace-drawer.png) |

## 复现

在仓库根目录执行；浏览器脚本需要Windows Edge/Node，并使用新的空输出/运行目录：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_contract_import.py tests/test_http_contract_and_cleanup.py tests/test_v4_interaction.py
node scripts/check_contract_import.cjs --out .runtime/import-fixes-recheck --runtime-dir .runtime/import-fixes-browser-recheck
node scripts/check_day10_frontend.cjs --out .runtime/workspace-fixes-recheck --runtime-dir .runtime/workspace-fixes-browser-recheck
```

## 边界

无需新增OCR服务或云解析，不自动分析、不截断超限合同、不回填已知残缺正文，保留100vh工作台与原业务状态隔离。Pillow固定为当前已安装的13.0.0，无额外模型安装。线程仍为协作超时，无法强制终止卡死调用；重启会清空单进程会话和审查上下文，不自动重启或补线程。

本轮没有Linux净室部署、真实恶意样本压力测试或图片检测准确率评估。所有样本为合成内容。保留原工作区修改，未执行Git写操作或提交。
