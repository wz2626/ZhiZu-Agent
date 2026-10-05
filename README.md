# 智租博弈（ZhiZu-Agent）

面向青年租房押金扣留、维修责任和提前退租问题的 AI 辅助演练项目。目标流程是合同风险审查、模拟协商、导出协商清单。目前仅完成 Day 1 的工程目录与总体规格初始化，功能尚未实现。

## 核心特性（规划）

- **前置脱敏**：浏览器遮蔽手机号和身份证号，提供可编辑预览；后端调用云 API 前复查。
- **契光排雷**：基于《民法典》租赁合同第 703～734 条审查条款，联动脱敏原文并显示依据和协商建议。
- **沉浸道场**：租客辅导、模拟房东回应和最多 5 轮谈判。
- **Critic 有界回环**：失败最多重写 2 次，仍不合格返回 `needs_review`。
- **混合算分**：模型识别与解释，程序按已确认条件确定性算分。
- **真实 trace 回放**：返回完整 JSON 后回放实际执行节点，并导出协商清单。

## 目录

| 路径 | 用途 |
| --- | --- |
| `backend/app/api/` | FastAPI 接口 |
| `backend/app/core/` | 配置与公共能力 |
| `backend/app/graph/` | 风险审查图与谈判图 |
| `backend/app/schemas/` | 输入、输出与状态 Schema |
| `backend/app/services/` | 检索、模型适配与业务服务 |
| `backend/data/laws/` | 权威租赁法条数据 |
| `backend/data/scenarios/` | 独立标记的演练场景 |
| `frontend-web/` | 单文件 Vue 3 网页 |
| `scripts/` | 入库、启动和辅助脚本 |
| `tests/` | 自动化与场景测试 |
| `docs/specs/` | 模块规格；[总规格](docs/specs/spec-00-architecture.md) |
| `docs/prompt-history/` | 三条真实 AI 协作过程链 |
| `docs/test-results/` | 实际测试输出与结果 |

## Windows PowerShell：10 分钟极速复现指南（命令占位）

目标是从克隆开始计时，在 10 分钟内完成依赖安装、配置、法条入库、启动及三场景复现；尚未实测该时长。前置条件：Python 3.12、Git、联网及有效的聊天/向量 API 凭据。

```powershell
# 进入仓库（若已经在仓库中，可跳过）
Set-Location ZhiZu-Agent

# 创建环境与安装依赖
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 复制模板并在 .env 中填写自己的密钥
Copy-Item .env.example .env

# TODO（Day 2）：法条入库命令，待脚本落地后填写
# TODO（后续回合）：一键启动命令、浏览器地址与三场景操作步骤
```

当前没有启动脚本、后端业务代码或网页，以上命令仅用于环境准备。后续按真实运行结果补充入库、启动、访问地址、常见错误排查与复现耗时。

## 规格与过程证据

后续实现以 [总规格](docs/specs/spec-00-architecture.md) 为基准。三条 Prompt 链分别记录法条检索与审查、图与 Critic、网页看板的真实 AI 交互和修复过程；空目录中的 `.gitkeep` 只用于 Git 追踪，不表示这些证据已生成。
