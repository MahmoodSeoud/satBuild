"""Smoke + integration tests for the dashboard home page and ticker endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satdeploy.dashboard.app import create_app
from satdeploy.history import DeploymentRecord, History


@pytest.fixture
def seeded_app(tmp_path: Path):
    db = tmp_path / "history.db"
    h = History(db)
    h.init_db()
    h.record(DeploymentRecord(
        app="controller", module="som1", file_hash="aaaa1111bbbb2222",
        remote_path="/opt/controller", action="push", success=True,
        timestamp="2026-04-01T09:00:00", git_hash="deadbeefcafe",
        provenance_source="local", transport="ssh",
    ))
    h.record(DeploymentRecord(
        app="libparam", module="som2", file_hash="cccc3333dddd4444",
        remote_path="/usr/lib/libparam.so", action="rollback", success=True,
        timestamp="2026-04-10T14:00:00", source="web",
    ))
    h.record(DeploymentRecord(
        app="boom", module="som1", file_hash="eeee5555ffff6666",
        remote_path="/opt/boom", action="push", success=False,
        error_message="bind failed", timestamp="2026-04-15T11:00:00",
    ))
    return create_app(db, "testsecret")


def test_healthz_returns_ok(seeded_app):
    client = TestClient(seeded_app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_home_renders_one_tile_per_app(seeded_app):
    client = TestClient(seeded_app)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "controller" in body
    assert "libparam" in body
    assert "boom" in body


def test_home_tile_state_classes_reflect_record(seeded_app):
    client = TestClient(seeded_app)
    body = client.get("/").text
    # controller: push + success = deployed (green)
    assert 'tile--deployed' in body
    # libparam: rollback = yellow
    assert 'tile--rolled-back' in body
    # boom: push + failed = red
    assert 'tile--failed' in body


def test_home_empty_db_shows_empty_state(tmp_path: Path):
    db = tmp_path / "empty.db"
    History(db).init_db()
    client = TestClient(create_app(db, "testsecret"))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No deployments yet." in resp.text


def test_ticker_endpoint_returns_recent_events(seeded_app):
    client = TestClient(seeded_app)
    resp = client.get("/api/ticker")
    assert resp.status_code == 200
    body = resp.text
    # Most-recent event first (boom, 2026-04-15) is in the top-5 slice.
    assert "boom" in body
    assert "push" in body


def test_ticker_empty_state(tmp_path: Path):
    db = tmp_path / "empty.db"
    History(db).init_db()
    client = TestClient(create_app(db, "testsecret"))
    body = client.get("/api/ticker").text
    assert "No activity yet" in body


def test_home_links_to_iteration_page(seeded_app):
    client = TestClient(seeded_app)
    body = client.get("/").text
    # Each tile with a record should link to /iterations/<file_hash>.
    assert '/iterations/aaaa1111bbbb2222' in body
    assert '/iterations/cccc3333dddd4444' in body


def test_home_escapes_app_name_in_html(tmp_path: Path):
    db = tmp_path / "h.db"
    h = History(db); h.init_db()
    h.record(DeploymentRecord(
        app="<script>alert(1)</script>", module="m", file_hash="ff",
        remote_path="/x", action="push", success=True,
        timestamp="2026-04-20T10:00:00",
    ))
    client = TestClient(create_app(db, "testsecret"))
    body = client.get("/").text
    # Jinja auto-escape must prevent raw <script> from appearing in HTML output.
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
