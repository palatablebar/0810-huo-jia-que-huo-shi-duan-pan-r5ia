"""旧版数据库（无 lineage/effective 列）的迁移与可追溯基线。"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.review.store import Store


def _legacy_db(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, report TEXT NOT NULL, "
            "created TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', "
            "revision INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', "
            "reviewed TEXT)"
        )
        report = {"manifest": {"created": "2026-01-01T00:00:00.000+00:00",
                               "sha256": "x", "version": "1.0.0", "run_id": "old1"},
                  "cases": [], "balance": {"releasable": True}, "intake": {}}
        db.execute(
            "INSERT INTO runs(id,report,created,status,revision) VALUES (?,?,?,?,?)",
            ("old1", json.dumps(report), report["manifest"]["created"], "APPROVED", 1),
        )
        db.execute(
            "INSERT INTO runs(id,report,created,status,revision) VALUES (?,?,?,?,?)",
            ("old2", json.dumps(report), report["manifest"]["created"], "HELD", 1),
        )
        db.commit()


def test_legacy_db_migrates_and_marks_approved_effective(tmp_path):
    path = tmp_path / "runs.db"
    _legacy_db(path)
    store = Store(path)
    approved = store.load("old1")
    held = store.load("old2")
    assert approved["effective"] is True and approved["lineage"] is None
    assert held["effective"] is False
    listing = {item["id"]: item["effective"] for item in store.list()}
    assert listing == {"old1": True, "old2": False}


def test_new_db_starts_without_effective_batch(tmp_path):
    store = Store(tmp_path / "fresh.db")
    with store.connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
    assert {"lineage", "effective"} <= columns
    assert store.list() == []
