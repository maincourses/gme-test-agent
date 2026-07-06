from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import sqlite3
import threading
import time


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class AgentDb:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                create table if not exists jobs (
                    id text primary key,
                    type text not null,
                    status text not null,
                    title text not null,
                    module text,
                    api_name text,
                    branch text,
                    worktree_path text,
                    codex_thread_id text,
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}',
                    error text
                );

                create table if not exists events (
                    id integer primary key autoincrement,
                    job_id text not null,
                    ts text not null,
                    level text not null,
                    message text not null
                );

                create table if not exists failures (
                    id text primary key,
                    job_id text not null,
                    status text not null,
                    test_suite text,
                    test_name text,
                    file text,
                    line integer,
                    reason text,
                    reproduce_command text,
                    skip_id text,
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}'
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_job(
        self,
        *,
        job_id: str,
        job_type: str,
        title: str,
        module: str | None = None,
        api_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = now_ts()
        with self._lock, self._conn:
            self._conn.execute(
                """
                insert into jobs (
                    id, type, status, title, module, api_name, created_at,
                    updated_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    "queued",
                    title,
                    module,
                    api_name,
                    ts,
                    ts,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            return self.get_job(job_id)

        fields["updated_at"] = now_ts()
        assignments = []
        values = []
        for key, value in fields.items():
            if key == "metadata":
                assignments.append("metadata_json = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            elif key in {
                "status",
                "title",
                "module",
                "api_name",
                "branch",
                "worktree_path",
                "codex_thread_id",
                "error",
                "updated_at",
            }:
                assignments.append(f"{key} = ?")
                values.append(value)
        values.append(job_id)
        with self._lock, self._conn:
            self._conn.execute(f"update jobs set {', '.join(assignments)} where id = ?", values)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_row(row)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("select * from jobs order by created_at desc, id desc").fetchall()
        return [self._job_row(row) for row in rows]

    def delete_job(self, job_id: str) -> dict[str, int]:
        with self._lock, self._conn:
            deleted_events = self._conn.execute("delete from events where job_id = ?", (job_id,)).rowcount
            deleted_failures = self._conn.execute("delete from failures where job_id = ?", (job_id,)).rowcount
            deleted_jobs = self._conn.execute("delete from jobs where id = ?", (job_id,)).rowcount
        return {
            "jobs": deleted_jobs,
            "events": deleted_events,
            "failures": deleted_failures,
        }

    def delete_open_failures_for_job(self, job_id: str) -> int:
        with self._lock, self._conn:
            return self._conn.execute("delete from failures where job_id = ? and status = 'open'", (job_id,)).rowcount

    def delete_open_failures_for_tests(self, job_id: str, test_keys: list[tuple[str, str]]) -> int:
        if not test_keys:
            return 0
        deleted = 0
        with self._lock, self._conn:
            for suite, test in test_keys:
                deleted += self._conn.execute(
                    """
                    delete from failures
                    where job_id = ? and status = 'open' and test_suite = ? and test_name = ?
                    """,
                    (job_id, suite, test),
                ).rowcount
        return deleted

    def delete_failures_for_tests(self, job_id: str, test_keys: list[tuple[str, str]]) -> int:
        if not test_keys:
            return 0
        deleted = 0
        with self._lock, self._conn:
            for suite, test in test_keys:
                deleted += self._conn.execute(
                    """
                    delete from failures
                    where job_id = ? and test_suite = ? and test_name = ?
                    """,
                    (job_id, suite, test),
                ).rowcount
        return deleted

    def add_event(self, job_id: str, level: str, message: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "insert into events (job_id, ts, level, message) values (?, ?, ?, ?)",
                (job_id, now_ts(), level, message),
            )

    def list_events(self, job_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "select * from events where job_id = ? and id > ? order by id asc",
                (job_id, after_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_failure(
        self,
        *,
        failure_id: str,
        job_id: str,
        test_suite: str = "",
        test_name: str = "",
        file: str = "",
        line: int | None = None,
        reason: str = "",
        reproduce_command: str = "",
        skip_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = now_ts()
        with self._lock, self._conn:
            self._conn.execute(
                """
                insert or replace into failures (
                    id, job_id, status, test_suite, test_name, file, line, reason,
                    reproduce_command, skip_id, created_at, updated_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    failure_id,
                    job_id,
                    "open",
                    test_suite,
                    test_name,
                    file,
                    line,
                    reason,
                    reproduce_command,
                    skip_id,
                    ts,
                    ts,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_failure(failure_id)

    def update_failure(self, failure_id: str, **fields: Any) -> dict[str, Any]:
        fields["updated_at"] = now_ts()
        assignments = []
        values = []
        for key, value in fields.items():
            if key == "metadata":
                assignments.append("metadata_json = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            elif key in {
                "status",
                "test_suite",
                "test_name",
                "file",
                "line",
                "reason",
                "reproduce_command",
                "skip_id",
                "updated_at",
            }:
                assignments.append(f"{key} = ?")
                values.append(value)
        values.append(failure_id)
        with self._lock, self._conn:
            self._conn.execute(f"update failures set {', '.join(assignments)} where id = ?", values)
        return self.get_failure(failure_id)

    def get_failure(self, failure_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("select * from failures where id = ?", (failure_id,)).fetchone()
        if row is None:
            raise KeyError(failure_id)
        return self._failure_row(row)

    def list_failures(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("select * from failures order by created_at desc, id desc").fetchall()
        return [self._failure_row(row) for row in rows]

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    @staticmethod
    def _failure_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data
