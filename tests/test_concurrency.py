from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.business import DomainIssue
from app.review.service import execute, review


def _approved(store, data):
    run = execute(store, data)
    review(store, run["id"], dict(revision=0, status="APPROVED", note="首发批次签发"))
    return run["id"]


def test_parallel_rerun_commits_single_row(store, clean):
    start = Barrier(4)

    def load():
        start.wait(3)
        return execute(store, clean)

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(lambda _: load(), range(4)))
    assert all(result == results[0] for result in results)
    assert len(store.list()) == 1


def test_parallel_correction_commits_single_row(store, clean):
    base_id = _approved(store, clean)
    correction = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"600201,0002,open,0,40,0,window\n"
        b"600202,0002,empty,0,1,0,gap\n"
        b"600203,0002,target,0,0,200,limit\n"
    )
    start = Barrier(4)

    def load():
        start.wait(3)
        return execute(store, correction, base_id)

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(lambda _: load(), range(4)))
    assert all(result["id"] == results[0]["id"] for result in results)
    assert len(store.list()) == 2


def test_parallel_promotion_has_one_winner(store, clean):
    base_id = _approved(store, clean)
    correction = (
        b"record,case,kind,start_min,end_min,limit_bp,note\n"
        b"610201,0002,open,0,60,0,window\n"
        b"610202,0002,empty,0,1,0,gap\n"
        b"610203,0002,target,0,0,200,limit\n"
    )
    run = execute(store, correction, base_id)
    start = Barrier(2)

    def attempt(note):
        start.wait(3)
        try:
            return review(
                store, run["id"], dict(revision=0, status="APPROVED", note=note)
            )["status"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(attempt, ["更正签发甲", "更正签发乙"]))
    assert sorted(results) == ["APPROVED", "STALE_REVIEW"]
    promoted = store.load(run["id"])
    assert promoted["revision"] == 1 and promoted["effective"] is True
    # 有效批次唯一，旧版被原子替换。
    effective = [item for item in store.list() if item["effective"]]
    assert [item["id"] for item in effective] == [run["id"]]


def test_parallel_distinct_corrections_keep_single_effective(store, clean):
    base_id = _approved(store, clean)

    def correction(open_end):
        # 缺货固定 1 分钟，营业窗不同导致字节不同且均低于 200bp 阈值。
        return (
            b"record,case,kind,start_min,end_min,limit_bp,note\n"
            + f"620201,0002,open,0,{open_end},0,window\n".encode()
            + b"620202,0002,empty,0,1,0,gap\n"
            + b"620203,0002,target,0,0,200,limit\n"
        )

    first = execute(store, correction(60), base_id)
    second = execute(store, correction(90), base_id)
    assert first["id"] != second["id"]
    start = Barrier(2)

    def attempt(run):
        start.wait(3)
        try:
            return review(
                store, run["id"], dict(revision=0, status="APPROVED", note="并行更正")
            )["status"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(attempt, [first, second]))
    assert sorted(results) == ["APPROVED", "STALE_REVIEW"]
    effective = [item for item in store.list() if item["effective"]]
    assert len(effective) == 1
    # 落败的新批次仍可暂缓，未污染有效版本。
    loser = second if effective[0]["id"] == first["id"] else first
    assert store.load(loser["id"])["status"] == "PENDING"


def test_parallel_review_has_one_winner(store, dirty):
    run = execute(store, dirty)
    start = Barrier(2)

    def attempt(note):
        start.wait(3)
        try:
            return review(store, run["id"], dict(revision=0, status="HELD", note=note))[
                "status"
            ]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(attempt, ["来源待检查", "分组待处理"]))
    assert sorted(results) == ["HELD", "STALE_REVIEW"]
    assert store.load(run["id"])["revision"] == 1
