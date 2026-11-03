# 规格索引

模块契约以总Spec与对应模块Spec为准；实际完成度和验证以测试报告为准。

| 文档 | 契约 |
| --- | --- |
| [Spec 00](spec-00-architecture.md) | 系统边界、双图、双重脱敏、V4统一工作区、动作确认与快照恢复 |
| [Spec 01](spec-01-rag-kb.md) | 32条法条库、幂等入库与检索 |
| [Spec 02](spec-02-risk-review.md) | 合同审查、详细失败出口与实际Trace |
| [Spec 03](spec-03-negotiation-scoring.md) | 纯Python确定性算分、候选核验与原子提交 |
| [Spec 04](spec-04-negotiation-api-and-scenarios.md) | 谈判HTTP、三场景、V4实例/轮次保护、幂等及真实Trace |
| [Spec 05](spec-05-proposal-drafting.md) | 短时审查上下文、独立草稿、校验与幂等；V4稳定问题ID、结构化回答、2000字预算与旧稿保留 |
| [Spec 06](spec-06-contract-import.md) | Word/PDF离线提取、流式限额、ParseJob所有权、扫描件防漏审及人工确认回填 |
