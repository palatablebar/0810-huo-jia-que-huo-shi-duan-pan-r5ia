"""更正片段与原有效批次的组合逻辑。

组合只能发生在"业务组"边界上：
- 更正片段里能独立完成营业窗、缺货率、阈值判定的组 → 重新审核；
- 其余组整组沿用原签发结论，并保留来源依据（run_id、来源指纹、规则版本）；
- 组内信息不足以独立判定（缺营业窗或阈值来源）或重审未通过时，
  整组保持原有效结果，另列阻断，绝不把片段拼进旧版形成混合版本；
- 更正只允许针对已签发批次中存在的业务组，新组无法追溯，直接拒收。
"""

from hashlib import sha256

from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.grouping import case_groups
from app.modules.pipeline import evaluate

# 一个业务组独立判定所需的最小构成：营业窗来源 + 阈值来源。
REQUIRED_KINDS = ("open", "target")


def fingerprint(data):
    return sha256(data).hexdigest()


def _source(run_id, manifest):
    return {
        "run_id": run_id,
        "source_sha256": manifest["sha256"],
        "rule_version": manifest["version"],
        "created": manifest["created"],
    }


def _block(case, reasons):
    return {"case": case, "reasons": sorted(reasons)}


def _carry(base_item, source, block):
    item = dict(base_item)
    item["provenance"] = {"origin": "CARRIED", "source": source, "blocked": block}
    return item


def compose(correction_data, base):
    """把更正片段组合到一个已签发批次之上，返回新批次报告。"""
    base_report = base["report"]
    base_by_case = {item["case"]: item for item in base_report["cases"]}
    base_source = _source(base["id"], base_report["manifest"])
    correction_hash = fingerprint(correction_data)

    intake = inspect(correction_data)
    correction_groups = dict(case_groups(intake["rows"]))

    unknown = sorted(set(correction_groups) - set(base_by_case))
    if unknown:
        # 无法追溯来源的业务组不能进入有效批次。
        raise DomainIssue("CORRECTION_GROUP_UNKNOWN")

    carried, reaudited, blocks = [], [], []
    for case, rows in sorted(correction_groups.items()):
        kinds = {row["kind"] for row in rows}
        missing = [f"MISSING_{kind.upper()}" for kind in REQUIRED_KINDS if kind not in kinds]
        if missing:
            block = _block(case, missing)
            blocks.append(block)
            carried.append(_carry(base_by_case[case], base_source, block))
            continue

        candidate = evaluate(rows, 5)
        if candidate["status"] != "READY":
            block = _block(case, [candidate["status"]])
            blocks.append(block)
            carried.append(_carry(base_by_case[case], base_source, block))
            continue

        candidate["provenance"] = {
            "origin": "REAUDITED",
            "source": {
                "run_id": None,
                "source_sha256": correction_hash,
                "rule_version": base_report["manifest"]["version"],
                "records": [row["record"] for row in rows],
            },
            "blocked": None,
        }
        reaudited.append(candidate)

    for case, item in sorted(base_by_case.items()):
        if case not in correction_groups:
            carried.append(_carry(item, base_source, None))

    cases = sorted(carried + reaudited, key=lambda item: item["case"])
    ready = sum(1 for case in cases if case["status"] == "READY")
    report = {
        "intake": {k: v for k, v in intake.items() if k != "rows"},
        "cases": cases,
        "blocks": blocks,
        "lineage": {
            "mode": "CORRECTION",
            "base_run_id": base["id"],
            "base_source": base_source,
            "correction_sha256": correction_hash,
            "reaudited": [item["case"] for item in reaudited],
            "carried": [item["case"] for item in carried],
        },
        "balance": {
            # 更正片段自身的采信对账（证据页只呈现该片段的隔离/忽略行）。
            "correction_input": intake["input"],
            "correction_accepted": intake["accepted"],
            "correction_isolated": intake["rejected"],
            "correction_ignored": intake["blank"] + intake["repeated"],
            "correction_balanced": (
                intake["accepted"] + intake["rejected"]
                + intake["blank"] + intake["repeated"]
            )
            == intake["input"],
            # 组合后有效批次的业务对账。
            "groups": len(cases),
            "ready": ready,
            "pending": len(cases) - ready,
            "blockers": len(blocks) + intake["rejected"],
            "releasable": bool(cases)
            and ready == len(cases)
            and not blocks
            and not intake["rejected"],
        },
    }
    return report
