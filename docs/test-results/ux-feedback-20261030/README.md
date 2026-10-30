# 表单反馈与视觉修复（2026-10-30）

本次在统一工作区上增量修复，不改变后端接口字段、算分、五轮上限、幂等与条款所有权。

## 修改与诊断

- 发送门禁集中到 `sendState`，按钮与发送函数共用判断；发送区显示未选场景、服务不可用、空消息、超长、未确认、在途或五轮上限的具体原因。未选场景可直接定位，服务不可用可重新检查。首次选择场景会带入已填写消息和其确认，后续切换仍各自保留记录。
- 未发现消息确认误绑草稿确认；确认了原界面允许未选场景先填消息、却不说明禁用原因的路径。本次浏览器实际验证该路径及恢复；不能把它断言为用户此前截图的唯一原因。
- 草稿原报错把模型输出的格式、隐私、引用失败混为一句。现在后端给出受控分类反馈，并将该分类用于有界重写；终止仍为 `VALIDATION_FAILED`，同请求缓存返回一致，不输出失败草稿或原始异常。
- 正常金额、日期、比例在现有正则下不会被遮蔽，新增测试覆盖输入及生成结果。没有盲目放宽全局号码规则；手机号形状的长数字仍保守处理，不能宣称所有可能误报均已消灭。本次没有用户原始失败响应，也未重跑真实云模型语义检查。
- 待补问题下方增加完整行动指引与“返回目标补充”按钮，定位并聚焦当前目标；改目标后旧稿和问题继续保留。
- 恢复真实等待状态的扫描线、骨架流光和脉冲灯；纯装饰不拦截操作，不表示模型正在读某句或真实节点进度。触屏与减少动态效果静态降级。
- 风险导航恢复渐变卡片、等级描边、选中归属光与节点轨道；精细鼠标 hover 仅上浮1px，不改宽高、原句锚点或滚动测量算法。

## 验收

| 检查 | 最终结果 |
| --- | --- |
| 全量离线 Pytest | 769 passed，0 failed，0 skipped；1条既有 LangChainPendingDeprecationWarning，31.33秒 |
| Day 8 | 13组通过，0失败／跳过 |
| Day 10 | 33组通过，0失败／跳过 |
| 视觉与空间 | 4组通过，15张截图，六档窗口／重排尺寸 |

浏览器用真实本机服务与明确离线模型替身，禁止外部请求。等待动效检查实际运行的 Web Animation；减少动态设置后检查动画停止；实际点击补充按钮验证焦点并核对旧稿不变。原有精确定位、防双击、隐私门禁、五轮、丢响应同编号重试、导出归属等检查保持通过。截图已人工查看联系表及等待、风险列表、草稿原尺寸图片；并未做新用户可用性盲测。

单独草稿测试在受限执行环境的本机连接阶段停滞，已中断；最终全量在获准本机环境运行，包含这组测试。未用中断结果宣称通过。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest --basetemp=.runtime/ux-repair/pytest-full -o cache_dir=.runtime/ux-repair/cache-full -o faulthandler_timeout=40
node scripts/check_day08_frontend.cjs --out .runtime/ux-repair/day8 --runtime-dir .runtime/ux-repair/browser8
node scripts/check_day10_frontend.cjs --out .runtime/ux-repair/day10 --runtime-dir .runtime/ux-repair/browser10
node scripts/check_layout_visual.cjs --out .runtime/ux-repair/visual --runtime-dir .runtime/ux-repair/browser-visual
```

再次执行需换新输出目录。附件仅保留 `acceptance.json`、`pytest.txt`、`contact-sheet.png`，其余截图在忽略目录 `.runtime/ux-repair`。不覆盖旧验收，不提交Git。

## 修改文件

- `frontend-web/index.html`：门禁反馈、首次场景选择保留、补充入口、等待装饰与风险卡样式。
- `backend/app/services/proposal.py`：受控草稿输出错误分类及重写反馈。
- `tests/test_proposal.py`：新增7项正常业务数据／错误分类与缓存验证。
- `scripts/check_workspace.cjs`：发送禁用原因、恢复、首次场景选择保留。
- `scripts/check_layout_visual.cjs`：等待动效、静态降级、补充焦点与旧稿保留。
- 本报告及验收索引。

体验新版前需重启后端（本次修改了草稿服务）并刷新网页；先复制需保存的清单，因为记录仍只存在当前页面。
