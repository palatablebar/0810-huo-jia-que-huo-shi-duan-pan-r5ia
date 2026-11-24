"""更正批次、逐组沿用与有效批次切换的领域规则。"""

import io
import json
from pathlib import Path

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.review.service import execute, review

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def group_correction():
    return (ROOT / "sample_data" / "correction_group.csv").read_bytes()


@pytest.fixture
def fragment_correction():
    return (ROOT / "sample_data" / "correction_fragment.csv").read_bytes()


@pytest.fixture
def approved_base(store, clean):
    run = execute(store, clean)
    review(store, run["id"], dict(revision=0, status="APPROVED", note="整批首发签发"))
    return store.load(run["id"])


def test_full_batch_is_effective_after_approval(store, clean):
    run = execute(store, clean)
    assert run["effective"] is False and run["lineage"] is None
    approved = review(
        store, run["id"], dict(revision=0, status="APPROVED", note="整批签发")
    )
    assert approved["effective"] is True


def test_correction_requires_approved_base(store, clean, group_correction):
    pending = execute(store, clean)
    with pytest.raises(DomainIssue, match="BASE_RUN_NOT_FINALIZED"):
        execute(store, group_correction, pending["id"])


def test_unknown_base_is_not_found(store, group_correction):
    with pytest.raises(DomainIssue, match="RUN_NOT_FOUND"):
        execute(store, group_correction, "missing-run")


def test_only_changed_group_is_reaudited_others_carry(
    store, approved_base, group_correction
):
    correction = execute(store, group_correction, approved_base["id"])
    report = correction["report"]
    origins = {case["case"]: case["provenance"]["origin"] for case in report["cases"]}
    assert origins == {"0001": "CARRIED", "0002": "REAUDITED"}

    carried = next(case for case in report["cases"] if case["case"] == "0001")
    # 沿用组保留原签发结论与来源依据，没有重新计算。
    assert carried["status"] == "READY"
    assert carried["provenance"]["source"]["run_id"] == approved_base["id"]
    assert (
        carried["provenance"]["source"]["source_sha256"]
        == approved_base["report"]["manifest"]["sha256"]
    )

    reaudited = next(case for case in report["cases"] if case["case"] == "0002")
    assert reaudited["status"] == "READY"
    assert reaudited["provenance"]["source"]["run_id"] is None
    assert report["lineage"]["reaudited"] == ["0002"]
    assert report["lineage"]["carried"] == ["0001"]


def test_reaudited_group_uses_correction_not_merged_rows(
    store, approved_base, group_correction
):
    correction = execute(store, group_correction, approved_base["id"])
    reaudited = next(
        case for case in correction["report"]["cases"] if case["case"] == "0002"
    )
    base_group = next(
        case for case in approved_base["report"]["cases"] if case["case"] == "0002"
    )
    # 结论完全来自更正片段独立计算，未与旧版行合并。
    assert reaudited["measure"]["value"] != base_group["measure"]["value"]
    assert reaudited["measure"]["value"] == 167
    assert sorted(reaudited["provenance"]["source"]["records"]) == [
        "100201",
        "100202",
        "100203",
        "100204",
    ]


def test_incomplete_fragment_keeps_group_result_and_records_blocker(
    store, approved_base, fragment_correction
):
    correction = execute(store, fragment_correction, approved_base["id"])
    report = correction["report"]
    target = next(case for case in report["cases"] if case["case"] == "0002")
    base_group = next(
        case for case in approved_base["report"]["cases"] if case["case"] == "0002"
    )
    # 整组保持原有效结果，没有拼出混合版本。
    assert target["status"] == base_group["status"]
    assert target["measure"] == base_group["measure"]
    assert target["provenance"]["origin"] == "CARRIED"
    assert target["provenance"]["blocked"] == {
        "case": "0002",
        "reasons": ["MISSING_TARGET"],
    }
    assert report["blocks"] == [
        {"case": "0002", "reasons": ["MISSING_TARGET"]}
    ]
    assert report["balance"]["releasable"] is False
    assert report["balance"]["blockers"] == 1


def test_failed_reaudit_falls_back_to_old_group(store, approved_base):
    # 片段构成完整但触发服务阈值：整组回退旧版并阻断，不产生混合结论。
    failing = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"200201,0002,open,0,100,0,window\n"
        b"200202,0002,empty,0,99,0,stockout\n"
        b"200203,0002,target,0,0,100,limit\n"
    )
    correction = execute(store, failing, approved_base["id"])
    report = correction["report"]
    target = next(case for case in report["cases"] if case["case"] == "0002")
    base_group = next(
        case for case in approved_base["report"]["cases"] if case["case"] == "0002"
    )
    assert target["measure"] == base_group["measure"]
    assert target["provenance"]["blocked"] == {
        "case": "0002",
        "reasons": ["SERVICE_LIMIT"],
    }
    assert report["balance"]["releasable"] is False


def test_unknown_group_correction_is_rejected(store, approved_base):
    orphan = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"300901,0009,open,0,10,0,group\n"
        b"300902,0009,target,0,0,100,limit\n"
    )
    with pytest.raises(DomainIssue, match="CORRECTION_GROUP_UNKNOWN"):
        execute(store, orphan, approved_base["id"])
    # 拒收不落任何批次。
    assert len(store.list()) == 1


def test_rerun_same_correction_does_not_duplicate_batch(
    store, approved_base, group_correction
):
    first = execute(store, group_correction, approved_base["id"])
    second = execute(store, group_correction, approved_base["id"])
    assert first["id"] == second["id"]
    assert len(store.list()) == 2  # 首发 + 一次更正


def test_distinct_correction_bytes_start_new_batch(store, approved_base, clean):
    first_data = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"400201,0002,open,0,40,0,window\n"
        b"400202,0002,empty,0,1,0,gap\n"
        b"400203,0002,target,0,0,200,limit\n"
    )
    second_data = first_data.replace(b"0,40", b"0,41")
    first = execute(store, first_data, approved_base["id"])
    second = execute(store, second_data, approved_base["id"])
    assert first["id"] != second["id"]
    assert len(store.list()) == 3


def test_approval_swaps_effective_batch_atomically(
    store, approved_base, group_correction
):
    correction = execute(store, group_correction, approved_base["id"])
    assert correction["effective"] is False
    promoted = review(
        store, correction["id"], dict(revision=0, status="APPROVED", note="更正签发")
    )
    assert promoted["effective"] is True
    old = store.load(approved_base["id"])
    # 旧版仍已签发、可追溯，但不再是有效批次。
    assert old["status"] == "APPROVED" and old["effective"] is False


def test_failed_signoff_restores_and_keeps_old_effective(
    store, approved_base, fragment_correction
):
    correction = execute(store, fragment_correction, approved_base["id"])
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(
            store,
            correction["id"],
            dict(revision=0, status="APPROVED", note="试图带阻断签发"),
        )
    # 新批次未被签发，旧有效批次保持有效，revision 未变。
    assert store.load(correction["id"])["revision"] == 0
    assert store.load(approved_base["id"])["effective"] is True


def test_hold_does_not_change_effective_batch(store, approved_base, fragment_correction):
    correction = execute(store, fragment_correction, approved_base["id"])
    held = review(
        store, correction["id"], dict(revision=0, status="HELD", note="片段不足暂缓")
    )
    assert held["status"] == "HELD" and held["effective"] is False
    assert store.load(approved_base["id"])["effective"] is True


def test_chained_corrections_follow_latest_effective(
    store, approved_base, group_correction
):
    first = execute(store, group_correction, approved_base["id"])
    review(store, first["id"], dict(revision=0, status="APPROVED", note="第一次更正"))
    next_correction = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"500101,0001,open,10,110,0,window\n"
        b"500102,0001,blackout,40,70,0,blackout\n"
        b"500103,0001,empty,0,50,0,gap\n"
        b"500104,0001,empty,70,85,0,gap\n"
        b"500105,0001,target,0,0,6500,limit\n"
    )
    # 不能再挂到已失效的首发批次。
    with pytest.raises(DomainIssue, match="BASE_RUN_NOT_FINALIZED"):
        execute(store, next_correction, approved_base["id"])
    chained = execute(store, next_correction, first["id"])
    review(store, chained["id"], dict(revision=0, status="APPROVED", note="第二次更正"))
    effective = [item for item in store.list() if item["effective"]]
    assert len(effective) == 1 and effective[0]["id"] == chained["id"]
    lineage = chained["report"]["lineage"]
    assert lineage["base_run_id"] == first["id"]
    # 第二次更正里 0002 未出现，沿用上一有效批次的重审结论。
    carried = next(case for case in chained["report"]["cases"] if case["case"] == "0002")
    assert carried["provenance"]["source"]["run_id"] == first["id"]


def test_evidence_matches_effective_batch_conclusion(
    store, approved_base, group_correction
):
    correction = execute(store, group_correction, approved_base["id"])
    review(store, correction["id"], dict(revision=0, status="APPROVED", note="更正签发"))
    packet = json.loads(artifact(store.load(correction["id"])))
    assert packet["schema"] == "review-evidence/2"
    assert packet["effective"] is True
    assert packet["lineage"]["base_run_id"] == approved_base["id"]
    # 页面/证据里每组都能看到来源依据，且与有效结论一致。
    for case in packet["cases"]:
        assert case["provenance"]["source"]["run_id"] in (
            None,
            approved_base["id"],
        )
        assert "status" in case
    blockers = [c["case"] for c in packet["blocks"]]
    assert blockers == []
    # 已失效旧版的证据仍保留其当时的结论。
    old_packet = json.loads(artifact(store.load(approved_base["id"])))
    assert old_packet["effective"] is False
    assert old_packet["review"]["status"] == "APPROVED"


def test_evidence_of_blocked_batch_lists_blocker(store, approved_base, fragment_correction):
    correction = execute(store, fragment_correction, approved_base["id"])
    packet = json.loads(artifact(correction))
    assert packet["blocks"][0]["case"] == "0002"
    assert packet["balance"]["releasable"] is False
    carried = next(case for case in packet["cases"] if case["case"] == "0002")
    assert carried["provenance"]["blocked"] is not None


# ---- HTTP 层 ----------------------------------------------------------------

def test_http_correction_flow(client, clean, group_correction, fragment_correction):
    base = client.post("/api/runs", data={"sample": "clean"}).json
    client.patch(
        f"/api/runs/{base['id']}",
        json=dict(revision=0, status="APPROVED", note="首发签发"),
    )
    response = client.post(
        "/api/runs",
        data={
            "base_run_id": base["id"],
            "file": (io.BytesIO(group_correction), "correction.csv"),
        },
    )
    assert response.status_code == 200
    correction = response.json
    assert correction["report"]["lineage"]["base_run_id"] == base["id"]

    promoted = client.patch(
        f"/api/runs/{correction['id']}",
        json=dict(revision=0, status="APPROVED", note="更正签发"),
    )
    assert promoted.status_code == 200 and promoted.json["effective"] is True

    blocked = client.post(
        "/api/runs",
        data={
            "base_run_id": base["id"],
            "file": (io.BytesIO(fragment_correction), "fragment.csv"),
        },
    )
    # 基线已失效：挂旧批次的新更正被拒绝。
    assert blocked.status_code == 409
    assert blocked.json["code"] == "BASE_RUN_NOT_FINALIZED"


def test_http_unknown_group_returns_422(client, clean):
    base = client.post("/api/runs", data={"sample": "clean"}).json
    client.patch(
        f"/api/runs/{base['id']}",
        json=dict(revision=0, status="APPROVED", note="首发签发"),
    )
    orphan = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"900901,0009,open,0,10,0,group\n"
        b"900902,0009,target,0,0,100,limit\n"
    )
    response = client.post(
        "/api/runs",
        data={"base_run_id": base["id"], "file": (io.BytesIO(orphan), "x.csv")},
    )
    assert response.status_code == 422
    assert response.json["code"] == "CORRECTION_GROUP_UNKNOWN"
