"""SQLite persistence (ARCHITECTURE.md §D). SQLAlchemy Core; schema created at start (no Alembic in MVP).

Deviation from the blueprint (documented in PROGRESS-TRACKER): `users` is omitted (single local user) and
tables use JSON columns liberally. Rows are plain dicts to keep the layers thin.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    select,
)
from sqlalchemy.engine import Engine

md = MetaData()


def _t(name: str, *cols: Column) -> Table:
    return Table(name, md, *cols)


def S(name: str, **kw: Any) -> Column:
    return Column(name, String, **kw)


def J(name: str) -> Column:
    return Column(name, JSON)


def I(name: str, **kw: Any) -> Column:  # noqa: E743
    return Column(name, Integer, **kw)


repositories = _t(
    "repositories", S("id", primary_key=True), S("name"), S("source_type"), S("source_ref"), S("local_path"),
    S("default_branch"), J("language_hints"), S("head_commit"), J("detected_commands"), J("exclusions"),
    S("github_owner"), S("github_name"), S("created_at"),
)
missions = _t(
    "missions", S("id", primary_key=True), S("repository_id"), S("title"), Column("request", Text), S("status"),
    S("status_before_pause"), S("status_reason"), J("config"), I("criteria_version"), S("current_patch_sha256"),
    I("state_version"), I("repair_cycles"), I("replans"), I("steps"), I("tokens_used"), Column("cost_used_usd", Float),
    S("workspace_path"), S("base_commit"), S("baseline_run_id"), S("mode"), J("outcome"), J("plan_summary"),
    S("created_at"), S("updated_at"), S("finished_at"),
)
tasks = _t(
    "tasks", S("id", primary_key=True), S("mission_id", index=True), S("key"), S("kind"), S("title"),
    Column("description", Text), S("status"), S("assignee_agent"), I("retries"), I("max_retries"), J("files_hint"),
    J("criteria_refs"), J("failure_fingerprints"), J("failure_context"), S("superseded_by"), I("plan_version"),
    S("created_at"), S("updated_at"), S("started_at"), S("finished_at"),
)
task_dependencies = _t("task_dependencies", S("task_id", primary_key=True), S("depends_on_task_id", primary_key=True))
acceptance_criteria = _t(
    "acceptance_criteria", S("id", primary_key=True), S("mission_id", index=True), S("ac_key"), Column("text", Text),
    J("verification"), S("status"), J("evidence_refs"), I("criteria_version"),
)
agent_executions = _t(
    "agent_executions", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("agent_id"), I("attempt"),
    S("status"), J("result"), Column("error", Text), S("started_at"), S("ended_at"), I("tokens_in"), I("tokens_out"),
    Column("cost_usd", Float),
)
agent_messages = _t(
    "agent_messages", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("correlation_id"),
    S("in_reply_to"), S("sender"), S("recipient"), S("type"), S("severity"), J("payload"), J("evidence_refs"),
    I("retry_attempt"), S("idempotency_key"), S("ack_status"), S("duplicate_of"), S("created_at"),
)
decisions = _t(
    "decisions", S("id", primary_key=True), S("mission_id", index=True), I("step"), S("action"), S("target_task_id"),
    S("target_agent"), Column("rationale", Text), J("evidence_refs"), S("forced_by"), S("created_at"),
)
tool_calls = _t(
    "tool_calls", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("execution_id"),
    S("agent_id"), S("tool"), J("args"), S("status"), I("exit_code"), I("duration_ms"), Column("output_excerpt", Text),
    S("output_ref"), S("output_sha256"), I("redactions"), Column("policy_reason", Text), S("started_at"), S("ended_at"),
)
test_runs = _t(
    "test_runs", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("tool_call_id"), S("kind"),
    S("runner"), Column("command", Text), S("patch_sha256"), I("total"), I("passed"), I("failed"), I("errored"),
    I("skipped"), Column("duration_s", Float), J("failures"), S("outcome"), S("created_at"),
)
security_findings = _t(
    "security_findings", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("raised_by"),
    S("severity"), S("category"), S("cwe"), S("file"), I("line_start"), I("line_end"), Column("evidence", Text),
    J("evidence_ref"), Column("recommendation", Text), Column("confidence", Float), S("status"), S("fingerprint"),
    S("first_patch_sha256"), S("resolved_patch_sha256"), Column("waive_reason", Text), S("source"), S("created_at"),
    S("updated_at"),
)
code_changes = _t(
    "code_changes", S("id", primary_key=True), S("mission_id", index=True), S("task_id"), S("tool_call_id"), S("path"),
    S("change_type"), S("patch_sha256_after"), I("additions"), I("deletions"), Column("is_test_file", Boolean),
    J("tamper_flags"), S("created_at"),
)
verification_reports = _t(
    "verification_reports", S("id", primary_key=True), S("mission_id", index=True), S("patch_sha256"),
    I("criteria_version"), S("overall"), J("results"), J("regression_check"), J("tamper_check"), S("started_at"),
    S("ended_at"),
)
approvals = _t(
    "approvals", S("id", primary_key=True), S("mission_id", index=True), S("patch_sha256"), S("decision"),
    Column("comment", Text), J("acknowledged_criteria"), J("publish"), S("requested_at"), S("decided_at"),
    Column("superseded", Boolean),
)
human_requests = _t(
    "human_requests", S("id", primary_key=True), S("mission_id", index=True), S("kind"), Column("question", Text),
    J("options"), J("evidence_refs"), S("status"), J("answer"), S("created_at"), S("answered_at"),
)
audit_events = _t(
    "audit_events", S("id", primary_key=True), S("mission_id", index=True), S("type"), S("actor"), S("task_id"),
    J("payload"), S("created_at"),
)
checkpoints = _t(
    "checkpoints", S("id", primary_key=True), S("mission_id", index=True), S("kind"), S("status"), I("state_version"),
    S("patch_sha256"), S("git_ref"), S("created_at"),
)
model_calls = _t(
    "model_calls", S("id", primary_key=True), S("mission_id", index=True), S("execution_id"), S("provider"), S("model"),
    S("purpose"), I("tokens_in"), I("tokens_out"), Column("cost_usd", Float), I("latency_ms"), S("status"),
    S("created_at"),
)


memory_entries = _t(
    "memory_entries", S("id", primary_key=True), S("repository_id", index=True), S("kind"), Column("text", Text), J("files"), S("source_mission_id"), S("created_at"),
)


class Database:
    def __init__(self, path: Path | str):
        url = "sqlite:///:memory:" if str(path) == ":memory:" else f"sqlite:///{path}"
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False, "timeout": 30}}
        if str(path) == ":memory:":
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **kwargs)

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        md.create_all(self.engine)

    def insert(self, table: Table, **values: Any) -> dict[str, Any]:
        with self.engine.begin() as c:
            c.execute(table.insert().values(**values))
        return values

    def update(self, table: Table, id_: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(table.update().where(table.c.id == id_).values(**values))

    def get(self, table: Table, id_: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(table).where(table.c.id == id_)).first()
        return dict(row._mapping) if row else None

    def select(self, table: Table, order_by: str | None = None, desc: bool = False, limit: int | None = None,
               where_cols: dict[str, Any] | None = None, extra: Any = None) -> list[dict[str, Any]]:
        q = select(table)
        for k, v in (where_cols or {}).items():
            q = q.where(table.c[k] == v)
        if extra is not None:
            q = q.where(extra)
        if order_by:
            col = table.c[order_by]
            q = q.order_by(col.desc() if desc else col)
        if limit:
            q = q.limit(limit)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]

    def delete_where(self, table: Table, **where: Any) -> None:
        with self.engine.begin() as c:
            q = table.delete()
            for k, v in where.items():
                q = q.where(table.c[k] == v)
            c.execute(q)

    def close(self) -> None:
        self.engine.dispose()
