# 字段与业务定义

输入编码 UTF-8，允许 BOM。首行必须匹配样例列顺序。记录键和业务组保留原始字符串。`kind` 允许 open, blackout, empty, target。说明列 `note` 可以跨行，限制 200 字。

业务字段按 `start_min`、`end_min`、`limit_bp` 排列。数字接受非负整数、全角数字和完整千分位。空串、短横线、N/A、NULL 与未知为缺值。无关字段用 0 占位。

分钟区间左闭右开，营业、暂停、缺货分别先取并集。缺货分子只计算可售区间，率按万分点展示，超限判断使用未舍入的分数。

`incoming.csv` 包含四个业务组，第二组提供不同边界，第三组触发业务拒收，第四组需要核对。另含重复表头、冲突记录、重复回放与错误列数。`ready.csv` 含可以签发的两个组。

`correction_group.csv` 是对 `ready.csv` 中 0002 组的完整更正（含 open 与 target，可独立判定，重审通过）；`correction_fragment.csv` 只有营业窗与缺货行、缺 target，信息不足以独立判定，整组沿用旧版并产生阻断。两者均需带 `base_run_id` 作为更正提交。
