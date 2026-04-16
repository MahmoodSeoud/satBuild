"""Integration tests for CSP transport against a live demo environment.

These tests require the demo to be running:
    satdeploy demo start

They connect over real CSP (via libcsp + zmqproxy) to the satdeploy-agent,
exercising the full CSP protocol stack: libcsp routing, protobuf
serialization, DTP file transfer, and agent-side backup/rollback.

Run with:
    pytest tests/test_integration_csp.py -m integration -v
"""

import os
import tempfile
import time

import pytest

from satdeploy.transport.csp import CSPTransport, CSP_DEPLOY_PORT
from satdeploy.transport.base import TransportError, DeployResult, AppStatus, BackupInfo
from satdeploy.csp.proto import DeployCommand, DeployRequest, DeployResponse


# Demo environment defaults
AGENT_NODE = 5425
GROUND_NODE = 40
ZMQ_HOST = "localhost"
BACKUP_DIR = "/opt/satdeploy/backups"


def _make_transport(timeout_ms=10000):
    """Create a fresh connected CSP transport."""
    t = CSPTransport(
        zmq_endpoint=f"tcp://{ZMQ_HOST}:6000",
        agent_node=AGENT_NODE,
        ground_node=GROUND_NODE,
        backup_dir=BACKUP_DIR,
        timeout_ms=timeout_ms,
    )
    t.connect()
    return t


def _wait_agent_idle(max_attempts=10, interval=0.5):
    """Poll the agent with STATUS until it responds, proving it's idle."""
    for _ in range(max_attempts):
        try:
            t = _make_transport(timeout_ms=3000)
            status = t.get_status()
            t.disconnect()
            if isinstance(status, dict):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _deploy_with_retry(transport_or_factory, app_name, local_path, remote_path,
                        retries=3, delay=2.0, **kwargs):
    """Deploy with retry to handle transient CSP/DTP timing issues."""
    for attempt in range(retries):
        if callable(transport_or_factory):
            _wait_agent_idle()
            t = transport_or_factory()
            result = t.deploy(
                app_name=app_name, local_path=local_path,
                remote_path=remote_path, **kwargs,
            )
            t.disconnect()
        else:
            result = transport_or_factory.deploy(
                app_name=app_name, local_path=local_path,
                remote_path=remote_path, **kwargs,
            )

        if result.success or attempt == retries - 1:
            return result

        time.sleep(delay)

    return result


def demo_is_running() -> bool:
    """Check if the demo environment is reachable over CSP."""
    try:
        t = _make_transport(timeout_ms=3000)
        status = t.get_status()
        t.disconnect()
        return isinstance(status, dict)
    except Exception:
        return False


def _restart_agent():
    """Restart the agent container to get a clean CSP buffer pool."""
    import subprocess as _sp
    try:
        result = _sp.run(
            ["docker", "restart", "satdeploy-agent-1"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            _sp.run(
                ["docker", "compose", "restart", "agent"],
                capture_output=True, text=True, timeout=15,
            )
        _wait_agent_idle(max_attempts=20, interval=1.0)
    except Exception:
        pass


# Skip all tests if demo isn't running
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not demo_is_running(),
        reason="Demo environment not running (start with: satdeploy demo start)",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _fresh_agent():
    """Restart the agent once at the start of the module for a clean state."""
    _restart_agent()


@pytest.fixture
def transport():
    """Create a connected CSP transport to the live demo."""
    _wait_agent_idle()
    t = _make_transport()
    yield t
    t.disconnect()


@pytest.fixture
def test_binary():
    """Create a temporary binary file for deployment."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(b"integration test payload " + str(time.time()).encode())
        f.flush()
        yield f.name
    os.unlink(f.name)


# --- CSP connectivity ---


class TestCSPConnectivity:
    """Test CSP connectivity to the live agent via libcsp."""

    def test_transport_connect_disconnect(self, transport):
        """Transport should connect and disconnect without error."""
        assert transport._connected is True

    def test_transport_reconnect(self):
        """Transport should handle reconnect (libcsp init is idempotent)."""
        t = _make_transport()
        t.disconnect()
        t.connect()
        assert t._connected is True
        t.disconnect()


# --- STATUS command ---


class TestCSPStatus:
    """Test STATUS command against the live agent."""

    def test_get_status_returns_dict(self, transport):
        """get_status() should return a dict of app statuses."""
        status = transport.get_status()
        assert isinstance(status, dict)
        assert len(status) > 0, "Agent should have at least one app"

    def test_status_contains_test_app(self, transport):
        """Demo agent should have test_app."""
        status = transport.get_status()
        assert "test_app" in status, f"Expected test_app in {list(status.keys())}"

    def test_status_app_has_hash(self, transport):
        """Each app in status should have a file hash."""
        status = transport.get_status()
        for app_name, app_status in status.items():
            assert isinstance(app_status, AppStatus)
            assert app_status.file_hash, f"{app_name} missing file_hash"
            assert len(app_status.file_hash) == 8, (
                f"{app_name} hash should be 8 chars, got {app_status.file_hash!r}"
            )

    def test_status_app_has_remote_path(self, transport):
        """Each app should report its remote installation path."""
        status = transport.get_status()
        for app_name, app_status in status.items():
            assert app_status.remote_path, f"{app_name} missing remote_path"
            assert app_status.remote_path.startswith("/"), (
                f"{app_name} remote_path should be absolute: {app_status.remote_path}"
            )

    def test_status_is_idempotent(self, transport):
        """Calling status twice should return the same result."""
        s1 = transport.get_status()
        s2 = transport.get_status()
        assert list(s1.keys()) == list(s2.keys())
        for app in s1:
            assert s1[app].file_hash == s2[app].file_hash


# --- DEPLOY command ---


class TestCSPDeploy:
    """Test DEPLOY command with real file transfer via DTP."""

    def test_deploy_new_file(self, transport, test_binary):
        """Deploying a new binary should succeed and return a hash."""
        result = _deploy_with_retry(
            transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert result.success, f"Deploy failed: {result.error_message}"
        assert result.file_hash, "Deploy should return a file hash"
        assert len(result.file_hash) == 8

    def test_deploy_changes_status_hash(self, transport, test_binary):
        """After deploy, status should show the new file hash."""
        result = _deploy_with_retry(
            transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert result.success

        status = transport.get_status()
        assert "test_app" in status
        assert status["test_app"].file_hash == result.file_hash

    def test_deploy_creates_backup(self, transport, test_binary):
        """Deploy should create a backup of the previous version."""
        status_before = transport.get_status()
        old_hash = status_before["test_app"].file_hash

        result = _deploy_with_retry(
            transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert result.success
        assert result.backup_path, "Deploy should report a backup path"

        backups = transport.list_backups("test_app")
        backup_hashes = [b.file_hash for b in backups]
        assert old_hash in backup_hashes, (
            f"Old hash {old_hash} should appear in backups: {backup_hashes}"
        )

    def test_deploy_nonexistent_app_creates_it(self, transport, test_binary):
        """Deploying to a new app name should work (agent creates it)."""
        unique_name = f"inttest_{int(time.time())}"
        result = _deploy_with_retry(
            transport, unique_name, test_binary, f"/opt/demo/bin/{unique_name}",
        )
        assert result.success, f"Deploy to new app failed: {result.error_message}"

        status = transport.get_status()
        assert unique_name in status


# --- LIST_BACKUPS command ---


class TestCSPListBackups:
    """Test LIST_VERSIONS command against the live agent."""

    def test_list_backups_returns_list(self, transport):
        """list_backups should return a list of BackupInfo."""
        backups = transport.list_backups("test_app")
        assert isinstance(backups, list)

    def test_list_backups_has_entries(self, transport):
        """test_app should have at least one backup after deploys."""
        backups = transport.list_backups("test_app")
        assert len(backups) > 0, "Expected at least one backup"

    def test_backup_info_has_hash_and_timestamp(self, transport):
        """Each backup should have a hash and timestamp."""
        backups = transport.list_backups("test_app")
        for b in backups:
            assert isinstance(b, BackupInfo)
            assert b.file_hash, f"Backup missing file_hash: {b}"
            assert b.timestamp, f"Backup missing timestamp: {b}"


# --- ROLLBACK command ---


class TestCSPRollback:
    """Test ROLLBACK command against the live agent."""

    def test_rollback_to_previous(self, test_binary):
        """Rollback should restore the previous version."""
        _wait_agent_idle()
        deploy_result = _deploy_with_retry(
            _make_transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert deploy_result.success

        new_hash = deploy_result.file_hash

        t = _make_transport()
        rollback_result = t.rollback(app_name="test_app")
        t.disconnect()
        assert rollback_result.success, f"Rollback failed: {rollback_result.error_message}"

        t = _make_transport()
        status = t.get_status()
        t.disconnect()
        assert status["test_app"].file_hash != new_hash, "Hash should change after rollback"

    def test_rollback_to_specific_hash(self, test_binary):
        """Rollback to a specific backup hash should restore that version."""
        _wait_agent_idle()
        t = _make_transport()
        status_before = t.get_status()
        original_hash = status_before["test_app"].file_hash
        t.disconnect()

        deploy_result = _deploy_with_retry(
            _make_transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert deploy_result.success

        t = _make_transport()
        rollback_result = t.rollback(
            app_name="test_app",
            backup_hash=original_hash,
        )
        t.disconnect()
        assert rollback_result.success

        t = _make_transport()
        status_after = t.get_status()
        t.disconnect()
        assert status_after["test_app"].file_hash == original_hash


# --- DTP file transfer ---


class TestDTPTransfer:
    """Test DTP (Data Transfer Protocol) over CSP."""

    def test_small_file_transfer(self, transport):
        """Small file (<1KB) should transfer successfully."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"small payload")
            f.flush()
            path = f.name

        try:
            result = _deploy_with_retry(
                transport, "test_app", path, "/opt/demo/bin/test_app",
            )
            assert result.success
        finally:
            os.unlink(path)

    def test_medium_file_transfer(self, transport):
        """Medium file (~10KB) should transfer with multiple DTP chunks."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"x" * 10_000)
            f.flush()
            path = f.name

        try:
            result = _deploy_with_retry(
                transport, "test_app", path, "/opt/demo/bin/test_app",
            )
            assert result.success
        finally:
            os.unlink(path)

    def test_large_file_transfer(self):
        """Larger file (~100KB) should transfer correctly."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(os.urandom(100_000))
            f.flush()
            path = f.name

        try:
            result = _deploy_with_retry(
                lambda: _make_transport(timeout_ms=15000),
                "test_app", path, "/opt/demo/bin/test_app",
            )
            assert result.success, f"Large file deploy failed: {result.error_message}"
        finally:
            os.unlink(path)

    def test_deploy_verifies_checksum(self, transport, test_binary):
        """Agent should verify the SHA256 checksum after DTP transfer."""
        from satdeploy.hash import compute_file_hash

        expected_hash = compute_file_hash(test_binary)[:8]
        result = _deploy_with_retry(
            transport, "test_app", test_binary, "/opt/demo/bin/test_app",
        )
        assert result.success
        assert result.file_hash == expected_hash, (
            f"Agent hash {result.file_hash} != local hash {expected_hash}"
        )


# --- CLI push with provenance sources ---


class TestCLIPushProvenanceSources:
    """Test `satdeploy push` end-to-end via the CLI."""

    def test_push_from_git_repo(self):
        """Push a file tracked in the git repo."""
        from click.testing import CliRunner
        from satdeploy.cli import main

        _wait_agent_idle()
        runner = CliRunner()

        demo_binary = os.path.expanduser("~/.satdeploy-demo/binaries/test_app")
        if not os.path.exists(demo_binary):
            demo_binary = os.path.expanduser("~/.satdeploy/demo/binaries/test_app")
        if not os.path.exists(demo_binary):
            pytest.skip("Demo binary not found")

        result = runner.invoke(
            main,
            ["push", "test_app", "--local", "pyproject.toml",
             "--config", os.path.expanduser("~/.satdeploy/demo/config.yaml")],
        )

        assert result.exit_code == 0, f"Push failed: {result.output}"
        assert "Deployed" in result.output
        assert "@" in result.output

    def test_push_from_github_actions(self):
        """Push with GitHub Actions env vars."""
        from click.testing import CliRunner
        from satdeploy.cli import main

        _wait_agent_idle()
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin", dir="/tmp") as f:
            f.write(b"github actions payload " + str(time.time()).encode())
            f.flush()
            tmp_path = f.name

        try:
            env = os.environ.copy()
            env["GITHUB_SHA"] = "abc123def456789012345678901234567890abcd"
            env["GITHUB_REF_NAME"] = "main"
            env["GITHUB_RUN_ID"] = "99999"

            result = runner.invoke(
                main,
                ["push", "test_app", "--local", tmp_path,
                 "--config", os.path.expanduser("~/.satdeploy/demo/config.yaml")],
                env=env,
            )

            assert result.exit_code == 0, f"Push failed: {result.output}"
            assert "Deployed" in result.output
            assert "ci:github" in result.output
        finally:
            os.unlink(tmp_path)

    def test_push_non_git_file(self):
        """Push a file from outside any git repo."""
        from click.testing import CliRunner
        from satdeploy.cli import main

        _wait_agent_idle()
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin", dir="/tmp") as f:
            f.write(b"non-git payload " + str(time.time()).encode())
            f.flush()
            tmp_path = f.name

        try:
            env = os.environ.copy()
            env.pop("GITHUB_SHA", None)
            env.pop("GITHUB_REF_NAME", None)
            env.pop("GITHUB_RUN_ID", None)

            result = runner.invoke(
                main,
                ["push", "test_app", "--local", tmp_path,
                 "--config", os.path.expanduser("~/.satdeploy/demo/config.yaml")],
                env=env,
            )

            assert result.exit_code == 0, f"Push failed: {result.output}"
            assert "Deployed" in result.output
            assert "ci:github" not in result.output
        finally:
            os.unlink(tmp_path)

    def test_push_sources_produce_different_status(self):
        """Each push source should result in correct status hash on the agent."""
        from click.testing import CliRunner
        from satdeploy.cli import main

        _wait_agent_idle()
        runner = CliRunner()
        config_flag = ["--config", os.path.expanduser("~/.satdeploy/demo/config.yaml")]

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin", dir="/tmp") as f:
            f.write(b"source-test-nongit")
            f.flush()
            tmp1 = f.name

        env_clean = os.environ.copy()
        env_clean.pop("GITHUB_SHA", None)
        env_clean.pop("GITHUB_REF_NAME", None)
        env_clean.pop("GITHUB_RUN_ID", None)

        try:
            result = runner.invoke(
                main, ["push", "test_app", "--local", tmp1] + config_flag,
                env=env_clean,
            )
            assert result.exit_code == 0

            t = _make_transport()
            status1 = t.get_status()
            t.disconnect()
            hash_nongit = status1["test_app"].file_hash
        finally:
            os.unlink(tmp1)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin", dir="/tmp") as f:
            f.write(b"source-test-ci")
            f.flush()
            tmp2 = f.name

        env_ci = os.environ.copy()
        env_ci["GITHUB_SHA"] = "deadbeef12345678901234567890123456789012"
        env_ci["GITHUB_REF_NAME"] = "release/v2"
        env_ci["GITHUB_RUN_ID"] = "42"

        try:
            result = runner.invoke(
                main, ["push", "test_app", "--local", tmp2] + config_flag,
                env=env_ci,
            )
            assert result.exit_code == 0

            t = _make_transport()
            status2 = t.get_status()
            t.disconnect()
            hash_ci = status2["test_app"].file_hash
        finally:
            os.unlink(tmp2)

        assert hash_nongit != hash_ci


# --- Error handling ---


class TestCSPErrorHandling:
    """Test error handling."""

    def test_double_disconnect_is_safe(self, transport):
        """Calling disconnect() twice should not raise."""
        transport.disconnect()
        transport.disconnect()


# --- Full round-trip ---


class TestCSPFullRoundTrip:
    """End-to-end: deploy -> status -> list -> rollback -> verify."""

    def test_full_lifecycle(self):
        """Complete deploy lifecycle through real CSP/DTP stack."""
        _wait_agent_idle()

        t = _make_transport()
        status_before = t.get_status()
        assert "test_app" in status_before
        original_hash = status_before["test_app"].file_hash
        t.disconnect()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            payload = f"lifecycle test {time.time()}".encode()
            f.write(payload)
            f.flush()
            test_file = f.name

        try:
            result = _deploy_with_retry(
                _make_transport, "test_app", test_file, "/opt/demo/bin/test_app",
            )
            assert result.success, f"Deploy failed: {result.error_message}"
            new_hash = result.file_hash
            assert new_hash != original_hash
        finally:
            os.unlink(test_file)

        t = _make_transport()
        status_after = t.get_status()
        assert status_after["test_app"].file_hash == new_hash

        backups = t.list_backups("test_app")
        t.disconnect()
        backup_hashes = [b.file_hash for b in backups]
        assert original_hash in backup_hashes

        t = _make_transport()
        rollback_result = t.rollback(
            app_name="test_app",
            backup_hash=original_hash,
        )
        t.disconnect()
        assert rollback_result.success

        t = _make_transport()
        status_final = t.get_status()
        t.disconnect()
        assert status_final["test_app"].file_hash == original_hash
