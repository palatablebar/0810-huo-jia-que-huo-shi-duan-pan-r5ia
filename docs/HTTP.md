# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。可带 `base_run_id` 提交更正片段：系统只重新审核能独立完成营业窗、缺货率与阈值判定的业务组，其余组沿用 `base_run_id` 对应有效批次的原签发结论；组内信息不足或重审未通过时整组回退旧版并在 `blocks` 列阻断。基线必须是当前有效且已签发的批次，否则返回 409 `BASE_RUN_NOT_FINALIZED`。更正含基线中不存在的业务组时返回 422 `CORRECTION_GROUP_UNKNOWN`。同一基线下字节相同的更正重跑返回同一批次，不会重复生成。

`GET /api/runs` 返回最近 50 批，含 `effective`（是否当前有效批次）与 `lineage`。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。签发（APPROVED）在单个事务内复核对账并翻转 `effective`：更正批次签发后旧版自动失效但保留全部证据；对账不通过（`releasable=false`，含阻断或隔离行）时整体回滚，旧有效批次保持有效。暂缓（HELD）不改变有效批次。

`GET /api/runs/<id>/evidence` 下载 `review-evidence/2` JSON，内含运行清单、行号隔离、业务证据、逐组来源（`cases[].provenance`：FULL/CARRIED/REAUDITED、来源批次与指纹、阻断原因）、批次血缘（`lineage`）、阻断清单（`blocks`）、有效标记（`effective`）和复核信息。证据与该批次结论一致，已失效旧版的证据仍保留其当时结论。
