import json


def artifact(run):
    report = run["report"]
    packet = {
        "schema": "review-evidence/2",
        "manifest": report["manifest"],
        "lineage": report.get("lineage"),
        "blocks": report.get("blocks", []),
        "balance": report["balance"],
        "cases": report["cases"],
        "intake": report["intake"],
        "effective": run["effective"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
