# 当前浏览器与模型检查入口

2026-11-04：右侧改为Spec 07微信破招。下列命令均使用显式的新输出目录，不能覆盖历史证据。

```powershell
node scripts/check_quote_panel.cjs --out .runtime/quote-browser-new --runtime-dir .runtime/quote-browser-runtime-new
node scripts/check_contract_import.cjs --out .runtime/import-browser-new --runtime-dir .runtime/import-browser-runtime-new
```

- `check_quote_panel.cjs`：当前面板、无审查直发、隐私、秒表、三档复制、追问、合同版本、迟到结果及响应布局；HTTP为明确标记的替身，不调用云模型。
- `check_contract_import.cjs`：真实本地Word/PDF解析与浏览器回填，不调用审查或模型。
- `evaluate_quote_analysis.py`：显式真实云调用，只使用脚本内合成脱敏材料，每案例一次调用，无自动重试；不是pytest，也不代表真人微信或法律准确率。输出目录自行指定：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_quote_analysis.py --out .runtime/quote-live-new.json --count 20
```

## Obsolete：旧演练UI检查

`check_day08_frontend.cjs`、`check_day10_frontend.cjs`及其`check_workspace.cjs`合同依赖旧Tab、Composer、轮次、评分和固定房东，已不作为当前UI验收入口。直接运行前两个旧入口会打印`SKIP ... no checks executed`后退出，不启动浏览器、不计通过。保留源文件及旧后端pytest；不能用退出码0冒充旧检查通过。

旧工作台中的合同解析、隐私、版本隔离、文本渲染与复制行为需要继续验证：本轮由新面板检查、真实导入检查及原有后端测试覆盖，详细范围与未运行项见[验收报告](../docs/test-results/quote-analysis-20261104/README.md)。未迁移的旧视觉/装饰断言不称为通过。

2026-11-04可用性复核新增：房东/对方/他与时间词的精确归因、有界否定和双重否定反例；best_for首人称威胁/辱骂降级中性提示；已选来源的中英文数字条号等价。最新证据见[可用性复核](../docs/test-results/quote-analysis-readiness-20261104/README.md)。
