# Spec 01：租赁法条知识库与幂等检索

## 范围与唯一数据源

权威法条唯一文件是 `backend/data/laws/civil_code_lease_703_734.json`。仅包含《中华人民共和国民法典》第三编合同第十四章租赁合同第 703～734 条，恰好 32 条。加载器按固定文件路径读取，不扫描目录。`backend/data/scenarios/` 的演练内容不是法律依据，不进入此集合。

## 单条法条契约

每条具有 `law_id`（`LAW-703`～`LAW-734`）、`article_number`（整数 703～734）、`article_no`（对应中文条号）、`law_name`（`中华人民共和国民法典`）、`part_chapter`（`第三编 合同 / 第十四章 租赁合同`）、完整 `content`、非空 `topic_tags` 数组、固定 `source_url`（`https://www.court.gov.cn/zixun/xiangqing/233181.html`）与固定 `verified_date`（`2026-10-05`）。条号必须连续、唯一且与 ID 对应。正文不允许省略号截断，跨段原文在同一条记录内以换行保存。

## 入库和向量模式

默认 Chroma 集合名为 `civil_code_lease_laws`，持久化目录取配置 `CHROMA_PATH`，可在测试或命令行中覆盖。每条以 `law_id` 作为固定 Chroma ID，入库前查询现有 ID，按 ID `upsert`；既有 ID 计入 `updated_count`，新增 ID 计入 `inserted_count`。专用集合出现其他 ID 时拒绝写入，避免误删或混入非权威内容。因此在专用集合内，首次入库为 32 新增，重复入库为 32 更新，总数均为 32。

`auto` 模式在有效向量密钥存在时使用 SiliconFlow 的 OpenAI 兼容 embeddings API，否则使用本地确定性 mock。`cloud` 模式无有效密钥时直接报错。云端适配器逐条校验返回向量维度，默认必须为 1024；空向量或 512、1536 等错误维度在写入 Chroma 前抛出包含期望值和实际值的 `ValueError`，不泄露密钥。入库和查询也验证向量维度。集合 metadata 记录 `embedding_mode`、`embedding_identity` 与 `embedding_dimension`（默认 1024），三者不一致时拒绝混用。Day 2 回合 1 创建的旧集合缺少维度元数据时，状态会显示未就绪；重新运行 `scripts/init_kb.py` 可在核对现有向量维度后幂等补录。

云端向量元素仅接受有限的 `int` 或 `float`，显式排除 `bool`；字符串数字、`None`、NaN 和正负 Infinity 均抛出不含原始值或密钥的 `ValueError`。请求/响应解析失败由适配器抛出脱敏的 `RuntimeError`。`core/config.py` 中的 `has_real_key` 供配置完整性检查与向量模式选择共用：去除首尾空白、忽略大小写，并排除包含 `your_`、`placeholder`、`replace_me`、`填入`、`示例` 的占位值；不会联网验证密钥。

mock 仅供离线开发测试，1024 维确定性向量的检索分数不能视为法律相关性的可靠度。云端检索前后端再次用正则遮蔽手机号和身份证号；上层仍需处理姓名、地址等自由文本的人工预览。

后端手机号脱敏支持可选 `+86`/`86` 前缀、连续 11 位及 3-4-4 空格或短横线分隔；身份证支持具有出生日期结构的 18 位（尾号数字或 `X/x`）及 15 位号码，不做 MOD11-2 校验码验证。匹配保留前后数字环视，不从连续的长数字串中截取号码；普通日期、法条号及常见银行卡号应保留。前端脱敏预览按后续模块实现，后端遮蔽不代替姓名、地址等人工检查。

## 检索与证据

`search_evidence(query, top_k=4)` 对空白查询和越界 `top_k` 报错；返回的 `EvidenceItem` 含 `evidence_id`、条号整数及中文、法名、章节、完整正文、来源 URL、核对日期和 0～1 范围的向量相似分数。返回 ID 只允许在 32 条白名单内；正文、来源和日期始终从固定 JSON 重新读取，避免被集合中的旧元数据污染。`get_laws_by_ids` 按固定 ID 精确回查并过滤无效 ID，供 Critic 核对引用。向量召回表示候选依据，不自动判定法律结论；尤其这 32 条没有直接规定押金返还，押金查询只能展示相关条文并提示直接依据不足。甲醛问题引用第 731 条时，还需核实是否实际危及安全或健康。

查询向量范数为零时直接返回 `[]`，不执行 Chroma 查询；mock 下纯标点、Emoji 或零宽字符属于此类。查询范数及返回距离必须有限；非有限距离在计算 `1 - distance` 前抛出 `ValueError`，证据构造也拒绝非有限分数。检索仅保留 `score > 0.0` 的候选，不设 0.05 等更高阈值；返回结果可以少于 `top_k` 或为空。按 ID 精确回查的分数仍为 1.0。

## 只读核验 API

`GET /api/kb/status` 不创建目录、集合或法条记录。`KBStatusResponse` 返回集合名、持久化目录、固定权威条数 32、实际索引条数、就绪状态、向量模式、固定来源 URL 和核对日期。集合不存在或未入库时条数为 0、`is_ready=false`。就绪要求恰好 32 个合法 ID，且集合向量模式、模型标识和维度与当前配置一致；旧集合可通过幂等入库补录维度元数据。

状态与搜索路径都在构造 `PersistentClient` 前检查 `chroma.sqlite3` 是否存在；缺库或空目录不构造客户端。已有文件先通过 SQLite `mode=ro` 连接执行 `PRAGMA quick_check`，避免损坏库使 Chroma 留下部分初始化状态。客户端构造、获取集合、读取元数据/ID 的数据库、Chroma、文件访问异常及 Chroma 包装的 `ValueError` 均受控处理；状态接口返回 HTTP 200、`is_ready=false`、`indexed_count=0`。此时 0 是计数不可读时的兼容回退值，不代表确认库内没有记录。客户端按请求关闭；单次搜索复用同一个客户端与集合完成状态核验和检索。

`POST /api/kb/search` 接收 `KBSearchRequest`：去除首尾空白后的 `query` 长度 1～500，`top_k` 默认 4、范围 1～8。后端先用正则遮蔽手机号和身份证号，再打开已存在的集合检索；此路径不创建目录、集合或法条记录。未就绪返回 HTTP 503，错误体 `detail` 包含 `code=KB_NOT_READY`、`indexed_count` 和运行 `scripts/init_kb.py` 的提示。成功时 `KBSearchResponse` 返回脱敏 `query`、`top_k`、`results`（`EvidenceItem` 列表）、`direct_basis_sufficient` 和 `boundary_notice`。押金返还、提前退租费用或具体通知天数等本章无直接规定的细则标记依据不足，提示补充合同约定及其他适用依据。该标记只反映本库范围，不能代替法律判断。

搜索期间的集合未就绪、非法 ID 污染、数据库/Chroma 异常、向量数值/维度或距离校验异常均返回 HTTP 503 `KB_NOT_READY`；若尚未成功读取条数，`indexed_count` 回退为 0。云端向量调用失败的 `RuntimeError` 返回 HTTP 503，`detail.code=UPSTREAM_EMBEDDING_ERROR`、`detail.message=云端向量服务异常，请稍后重试。`，不混用知识库错误码或泄露底层异常。请求模型校验错误仍返回 HTTP 422。
