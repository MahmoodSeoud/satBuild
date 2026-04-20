"""Tests for the `source` column migration + cli/web provenance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from satdeploy.history import DeploymentRecord, History


def test_init_db_creates_source_column(tmp_path: Path):
    db = tmp_path / "h.db"
    History(db).init_db()
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
    conn.close()
    assert "source" in cols


def test_migrate_adds_source_to_old_schema(tmp_path: Path):
    """A pre-R6 DB (no source column) gets the column added on next init_db()."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE deployments (
            id INTEGER PRIMARY KEY,
            module TEXT NOT NULL DEFAULT 'default',
            app TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            git_hash TEXT,
            file_hash TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            backup_path TEXT,
            action TEXT NOT NULL,
            success INTEGER NOT NULL,
            error_message TEXT,
            service_hash TEXT,
            vmem_cleared INTEGER NOT NULL DEFAULT 0,
            provenance_source TEXT,
            transport TEXT
        )
    """)
    conn.execute(
        "INSERT INTO deployments (module, app, timestamp, file_hash, remote_path, action, success) "
        "VALUES ('m', 'a', '2026-01-01', 'ff', '/x', 'push', 1)"
    )
    conn.commit()
    conn.close()

    History(db).init_db()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM deployments").fetchone()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(deployments)")}
    conn.close()

    assert "source" in cols
    # Existing rows keep the default 'cli' — they were CLI-triggered historically.
    assert row["source"] == "cli"


def test_record_defaults_to_cli_when_source_none(tmp_path: Path):
    db = tmp_path / "h.db"
    h = History(db)
    h.init_db()
    h.record(DeploymentRecord(
        app="a", module="m", file_hash="f", remote_path="/x",
        action="push", success=True, timestamp="2026-04-20T10:00:00",
    ))
    last = h.get_last_deployment("a")
    assert last is not None
    assert last.source == "cli"


def test_record_accepts_explicit_source_web(tmp_path: Path):
    db = tmp_path / "h.db"
    h = History(db)
    h.init_db()
    h.record(DeploymentRecord(
        app="a", module="m", file_hash="f", remote_path="/x",
        action="rollback", success=True, timestamp="2026-04-20T10:00:00",
        source="web",
    ))
    last = h.get_last_deployment("a")
    assert last is not None
    assert last.source == "web"


def test_record_no_longer_hardcodes_transport_ssh(tmp_path: Path):
    """Eng-review landmine #7 regression guard: transport field should round-trip."""
    db = tmp_path / "h.db"
    h = History(db)
    h.init_db()
    h.record(DeploymentRecord(
        app="a", module="m", file_hash="f", remote_path="/x",
        action="push", success=True, timestamp="2026-04-20T10:00:00",
        transport="csp",
    ))
    last = h.get_last_deployment("a")
    assert last is not None
    assert last.transport == "csp"
