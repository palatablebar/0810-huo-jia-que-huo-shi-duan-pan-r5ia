import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT,
    lineage TEXT, effective INTEGER NOT NULL DEFAULT 0
);"""

# 旧库增量补列，历史已签发批次视为当时的有效批次以保留可追溯基线。
# 注意：向已有行的表加 NOT NULL 列必须带 DEFAULT，否则 SQLite 报错并回滚整个事务。
MIGRATIONS = (
    "ALTER TABLE runs ADD COLUMN lineage TEXT",
    "ALTER TABLE runs ADD COLUMN effective INTEGER NOT NULL DEFAULT 0",
)


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            existing = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone()
            db.execute(SCHEMA)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            added_effective = False
            for statement in MIGRATIONS:
                column = statement.split("ADD COLUMN")[1].split()[0]
                if column not in columns:
                    db.execute(statement)
                    added_effective = added_effective or column == "effective"
            if existing and added_effective:
                # 旧库中已签发批次迁移为当时的有效批次，保留可追溯基线。
                db.execute("UPDATE runs SET effective=1 WHERE status='APPROVED'")
            yield db

    def register(self, run_id, report, lineage=None):
        payload = json.dumps(report, ensure_ascii=False)
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created,lineage,effective) "
                "VALUES (?,?,?,?,0) ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    payload,
                    report["manifest"]["created"],
                    None if lineage is None else json.dumps(lineage, ensure_ascii=False),
                ),
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        return self._hydrate(row)

    def list(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,created,status,revision,note,lineage,effective "
                "FROM runs ORDER BY created DESC,id LIMIT 50"
            )
            return [self._hydrate(row, inline=True) for row in rows]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 "
                "WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)

    def promote(self, run_id, revision, status, note, now, base_run_id):
        """原子签发：仅当乐观锁、对账与旧版存在性全部成立时才翻转有效批次。

        任一步失败整体回滚，旧有效批次保持有效，杜绝半成品版本。
        """
        with self.connect() as db:
            current = db.execute(
                "SELECT revision,report FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if current is None:
                raise DomainIssue("RUN_NOT_FOUND")
            if current["revision"] != revision:
                raise DomainIssue("STALE_REVIEW")
            report = json.loads(current["report"])
            if not report["balance"]["releasable"]:
                raise DomainIssue("UNRESOLVED_ISSUES")
            if base_run_id is not None and db.execute(
                "SELECT 1 FROM runs WHERE id=?", (base_run_id,)
            ).fetchone() is None:
                raise DomainIssue("BASE_RUN_NOT_FOUND")

            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 "
                "WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
            if base_run_id is None:
                db.execute("UPDATE runs SET effective=0 WHERE id <> ?", (run_id,))
                db.execute("UPDATE runs SET effective=1 WHERE id=?", (run_id,))
            else:
                # 仅当基线仍是当前有效批次时才允许让位；并发下落败方拿不到行，整体回滚。
                cursor = db.execute(
                    "UPDATE runs SET effective=0 WHERE id=? AND effective=1",
                    (base_run_id,),
                )
                if cursor.rowcount != 1:
                    raise DomainIssue("STALE_REVIEW")
                db.execute("UPDATE runs SET effective=1 WHERE id=?", (run_id,))
        return self.load(run_id)

    def _hydrate(self, row, inline=False):
        result = dict(row)
        result["effective"] = bool(result.get("effective"))
        lineage = result.get("lineage")
        result["lineage"] = json.loads(lineage) if lineage else None
        if not inline:
            result["report"] = json.loads(result["report"])
        return result
