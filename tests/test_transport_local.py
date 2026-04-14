"""Tests for LocalTransport — the filesystem-backed transport used by
`satdeploy demo` and by users deploying to chroots / mounted rootfs.
"""

from pathlib import Path

import pytest

from satdeploy.transport.base import Transport
from satdeploy.transport.local import LocalTransport


def _make_transport(tmp_path: Path, app_name: str = "myapp", remote: str = "/opt/myapp"):
    target = tmp_path / "target"
    backups = tmp_path / "backups"
    transport = LocalTransport(
        target_dir=str(target),
        backup_dir=str(backups),
        apps={app_name: {"remote": remote, "service": None}},
    )
    transport.connect()
    return transport, target, backups


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestLocalTransportInterface:
    def test_is_transport_subclass(self):
        assert issubclass(LocalTransport, Transport)


class TestLocalTransportDeploy:
    def test_fresh_deploy_writes_file_and_no_backup(self, tmp_path):
        """First push to an empty target: file lands, no backup to create."""
        transport, target, backups = _make_transport(tmp_path)
        source = _write(tmp_path / "v1", "v1-content")

        result = transport.deploy(
            app_name="myapp", local_path=str(source), remote_path="/opt/myapp",
        )

        assert result.success is True
        assert result.skipped is False
        assert result.backup_path is None
        assert (target / "opt/myapp").read_text() == "v1-content"

    def test_second_deploy_backs_up_previous(self, tmp_path):
        """Second push with different content backs up the first."""
        transport, target, backups = _make_transport(tmp_path)
        v1 = _write(tmp_path / "v1", "v1-content")
        v2 = _write(tmp_path / "v2", "v2-content-different")

        transport.deploy("myapp", str(v1), "/opt/myapp")
        result = transport.deploy("myapp", str(v2), "/opt/myapp")

        assert result.success is True
        assert result.skipped is False
        assert result.backup_path is not None
        assert Path(result.backup_path).read_text() == "v1-content"

    def test_hash_skip_on_identical_content(self, tmp_path):
        """Pushing the same file twice without --force sets skipped=True."""
        transport, target, backups = _make_transport(tmp_path)
        v1 = _write(tmp_path / "v1", "stable-content")

        transport.deploy("myapp", str(v1), "/opt/myapp")
        result = transport.deploy("myapp", str(v1), "/opt/myapp")

        assert result.success is True
        assert result.skipped is True
        assert result.backup_path is None

    def test_force_of_identical_file_does_not_create_redundant_backup(self, tmp_path):
        """Regression for BUG #10 (QA 2026-04-14):

        `push --force` of a file that's already on the target with identical
        content used to create a backup of the current file anyway (because
        force skips the hash-skip branch). That polluted the backup chain —
        the newest backup became the same hash as the deployed file — and
        the subsequent `rollback` became a silent no-op, returning the
        "current" state to the "previous" state which were identical.

        After the fix, `_make_backup` must not run when current_hash ==
        incoming_hash, so the backup chain stays honest and rollback goes
        to the real previous version.
        """
        transport, target, backups = _make_transport(tmp_path)
        v1 = _write(tmp_path / "v1", "v1-content")
        v2 = _write(tmp_path / "v2", "v2-content")

        transport.deploy("myapp", str(v1), "/opt/myapp")    # target: v1
        transport.deploy("myapp", str(v2), "/opt/myapp")    # target: v2, backup: v1
        backups_before = transport.list_backups("myapp")
        assert len(backups_before) == 1
        v1_backup_hash = backups_before[0].file_hash

        transport.deploy("myapp", str(v2), "/opt/myapp", force=True)
        backups_after = transport.list_backups("myapp")
        assert len(backups_after) == 1
        assert backups_after[0].file_hash == v1_backup_hash

        rollback_result = transport.rollback("myapp")
        assert rollback_result.success is True
        assert (target / "opt/myapp").read_text() == "v1-content"


class TestLocalTransportStatus:
    def test_status_excludes_apps_that_have_never_been_pushed(self, tmp_path):
        """get_status returns only apps whose file is actually on disk.

        Regression for the display bug where a fresh config showed
        `myapp deployed` for an app that had never been pushed, because
        get_status returned an entry with file_hash=None and running=False
        for every configured app.
        """
        transport, target, backups = _make_transport(tmp_path)

        assert transport.get_status() == {}

        source = _write(tmp_path / "v1", "v1")
        transport.deploy("myapp", str(source), "/opt/myapp")

        status = transport.get_status()
        assert "myapp" in status
        assert status["myapp"].running is True
        assert status["myapp"].file_hash is not None


class TestLocalTransportRollback:
    def test_rollback_with_no_backups_fails_cleanly(self, tmp_path):
        transport, target, backups = _make_transport(tmp_path)
        result = transport.rollback("myapp")
        assert result.success is False
        assert "No backups found" in (result.error_message or "")

    def test_rollback_with_explicit_hash(self, tmp_path):
        transport, target, backups = _make_transport(tmp_path)
        v1 = _write(tmp_path / "v1", "v1-content")
        v2 = _write(tmp_path / "v2", "v2-content")
        v3 = _write(tmp_path / "v3", "v3-content")

        transport.deploy("myapp", str(v1), "/opt/myapp")
        transport.deploy("myapp", str(v2), "/opt/myapp")
        transport.deploy("myapp", str(v3), "/opt/myapp")

        v1_backup = next(
            b for b in transport.list_backups("myapp")
            if b.file_hash == _hash_of("v1-content")
        )
        result = transport.rollback("myapp", backup_hash=v1_backup.file_hash)
        assert result.success is True
        assert (target / "opt/myapp").read_text() == "v1-content"

    def test_rollback_to_unknown_hash_fails_cleanly(self, tmp_path):
        transport, target, backups = _make_transport(tmp_path)
        v1 = _write(tmp_path / "v1", "v1")
        v2 = _write(tmp_path / "v2", "v2")
        transport.deploy("myapp", str(v1), "/opt/myapp")
        transport.deploy("myapp", str(v2), "/opt/myapp")

        result = transport.rollback("myapp", backup_hash="deadbeef")
        assert result.success is False
        assert "deadbeef" in (result.error_message or "")


def _hash_of(content: str) -> str:
    """First 8 chars of SHA256, matching compute_file_hash."""
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:8]
