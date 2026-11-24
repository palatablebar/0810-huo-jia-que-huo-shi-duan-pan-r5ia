COLUMNS = ("start_min", "end_min", "limit_bp")
KINDS = ("open", "blackout", "empty", "target")
PROJECT = {
    "name": "货架缺货时段盘",
    "actor": "零售数据质量分析员",
    "stages": [
        ("intake", "样例采信"),
        ("prepare", "营业窗合并"),
        ("calculate", "缺货剪裁"),
        ("policy", "服务判定"),
        ("balance", "运行对账"),
    ],
    "chart": "可售与缺货",
}
