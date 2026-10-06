# Spec 01：租赁法条知识库与幂等检索

## 范围与唯一数据源

权威法条唯一文件是 `backend/data/laws/civil_code_lease_703_734.json`。仅包含《中华人民共和国民法典》第三编合同第十四章租赁合同第 703～734 条，恰好 32 条。加载器按固定文件路径读取，不扫描目录。`backend/data/scenarios/` 的演练内容不是法律依据，不进入此集合。

## 单条法条契约

每条具有 `law_id`（`LAW-703`～`LAW-734`）、`article_number`（整数 703～734）、`article_no`（对应中文条号）、`law_name`（`中华人民共和国民法典`）、`part_chapter`（`第三编 合同 / 第十四章 租赁合同`）、完整 `content`、非空 `topic_tags` 数组、固定 `source_url`（`https://www.court.gov.cn/zixun/xiangqing/233181.html`）与固定 `verified_date`（`2026-10-05`）。条号必须连续、唯一且与 ID 对应。正文不允许省略号截断，跨段原文在同一条记录内以换行保存。

## 入库和向量模式

默认 Chroma 集合名为 `civil_code_lease_laws`，持久化目录取配置 `CHROMA_PATH`，可在测试或命令行中覆盖。每条以 `law_id` 作为固定 Chroma ID，入库前查询现有 ID，按 ID `upsert`；既有 ID 计入 `updated_count`，新增 ID 计入 `inserted_count`。专用集合出现其他 ID 时拒绝写入，避免误删或混入非权威内容。因此在专用集合内，首次入库为 32 新增，重复入库为 32 更新，总数均为 32。

`auto` 模式在有效向量密钥存在时使用 SiliconFlow 的 OpenAI 兼容 embeddings API，否则使用本地确定性 mock。`cloud` 模式无有效密钥时直接报错。集合记录向量模式与模型标识，两者不同的向量不得混用；切换模式或模型应使用新的集合或经明确管理流程重建。mock 仅供离线开发测试，1024 维确定性向量的检索分数不能视为法律相关性的可靠度。云端检索前后端再次用正则遮蔽手机号和身份证号；上层仍需处理姓名、地址等自由文本的人工预览。

## 检索与证据

`search_evidence(query, top_k=4)` 对空白查询和越界 `top_k` 报错；返回的 `EvidenceItem` 含 `evidence_id`、条号整数及中文、法名、章节、完整正文、来源 URL、核对日期和 0～1 范围的向量相似分数。返回 ID 只允许在 32 条白名单内；正文、来源和日期始终从固定 JSON 重新读取，避免被集合中的旧元数据污染。`get_laws_by_ids` 按固定 ID 精确回查并过滤无效 ID，供 Critic 核对引用。向量召回表示候选依据，不自动判定法律结论；尤其这 32 条没有直接规定押金返还，押金查询只能展示相关条文并提示直接依据不足。甲醛问题引用第 731 条时，还需核实是否实际危及安全或健康。
