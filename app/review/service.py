from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.compose import compose, fingerprint
from app.modules.pipeline import run


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _manifest(data, run_id, start, extra):
    manifest = dict(
        sha256=fingerprint(data),
        version=RULE_VERSION,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
    )
    manifest.update(extra)
    return manifest


def _stamp_full(report):
    for case in report["cases"]:
        case["provenance"] = {
            "origin": "FULL",
            "source": {
                "run_id": report["manifest"]["run_id"],
                "source_sha256": report["manifest"]["sha256"],
                "rule_version": report["manifest"]["version"],
            },
            "blocked": None,
        }


def execute(store, data, base_id=None):
    start = monotonic()
    if base_id is None:
        run_id = sha256(f"{RULE_VERSION}:{fingerprint(data)}".encode()).hexdigest()
        try:
            return store.load(run_id)
        except DomainIssue as error:
            if error.code != "RUN_NOT_FOUND":
                raise
        report = run(data)
        report["manifest"] = _manifest(data, run_id, start, {"mode": "FULL"})
        _stamp_full(report)
        return store.register(run_id, report)

    base = store.load(base_id)
    if base["status"] != "APPROVED" or not base["effective"]:
        # 只有当前有效（已签发且未被新版本替代）的批次才能作为沿用来源。
        raise DomainIssue("BASE_RUN_NOT_FINALIZED")

    correction_hash = fingerprint(data)
    run_id = sha256(
        f"{RULE_VERSION}:CORRECTION:{base_id}:{correction_hash}".encode()
    ).hexdigest()
    # 重跑同一更正（对同一基线、同一字节内容）不重复生成有效批次。
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise

    report = compose(data, base)
    report["manifest"] = _manifest(
        data,
        run_id,
        start,
        {"mode": "CORRECTION", "base_run_id": base_id},
    )
    lineage = {
        "mode": "CORRECTION",
        "base_run_id": base_id,
        "correction_sha256": correction_hash,
    }
    return store.register(run_id, report, lineage)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")

    cleaned = note.strip()
    if status == "HELD":
        return store.revise(run_id, revision, status, cleaned, now())

    lineage = current.get("lineage")
    base_run_id = lineage["base_run_id"] if lineage else None
    # promote 在单个事务内复核对账并翻转 effective；失败即回滚，旧版保持有效。
    return store.promote(
        run_id, revision, status, cleaned, now(), base_run_id
    )
