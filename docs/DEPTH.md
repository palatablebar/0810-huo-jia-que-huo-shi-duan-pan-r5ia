# 货架缺货时段盘规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 营业窗合并 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 缺货剪裁 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 服务判定 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 单组更正 | 逐组重审/沿用与有效批次切换 | `POST /api/runs?base_run_id=` | `app/modules/compose.py`、`app/review/store.py` | `tests/test_corrections.py`、`tests/test_store_migration.py` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

分钟区间左闭右开，营业、暂停、缺货分别先取并集。缺货分子只计算可售区间，率按万分点展示，超限判断使用未舍入的分数。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`。

## 更正批次不变量

- 组合只在业务组边界发生：片段行绝不与旧版同组行拼接，避免两个来源的混合版本。
- 组内含 `open` 与 `target` 且独立判定为 READY 才重审（REAUDITED）；缺任一来源记 `MISSING_*`，重审失败记原判定码，整组沿用旧版（CARRIED）并进入 `blocks`。
- 沿用组保留来源 `run_id`、来源 `sha256` 与规则版本；片段中出现基线没有的业务组直接 `CORRECTION_GROUP_UNKNOWN`。
- 更正批次幂等：`run_id = HASH(规则版本: CORRECTION: 基线: 更正指纹)`，同基线同字节重跑不新增批次。
- 签发在单事务内复核对账并翻转 `effective`，失败整体回滚；任意时刻至多一个有效批次，旧版保留 APPROVED 状态与证据。
- 只有当前有效且已签发的批次可作更正基线，已失效批次返回 `BASE_RUN_NOT_FINALIZED`。
