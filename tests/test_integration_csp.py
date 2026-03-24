"""Integration tests for CSP transport against a live demo environment.

These tests require the demo to be running:
    satdeploy demo start

They connect over real ZMQ sockets to the zmqproxy and satdeploy-agent,
exercising the full CSP protocol stack: ZMQ PUB/SUB, CSP header encoding,
protobuf serialization, DTP file transfer, and agent-side backup/rollback.

Run with:
    pytest tests/test_integration_csp.py -m integration -v
"""

import os
import struct
import tempfile
import time

import pytest
import zmq

from satdeploy.transport.csp import CSPTransport, CSP_HEADER_SIZE, CSP_DEPLOY_PORT
from satdeploy.transport.base import TransportError, DeployResult, AppStatus, BackupInfo
from satdeploy.csp.proto import DeployCommand, DeployRequest, DeployResponse


# Demo environment defaults
AGENT_NODE = 5425
GROUND_NODE = 40
ZMQ_HOST = "localhost"
ZMQ_PUB_PORT = 9600
ZMQ_SUB_PORT = 9601
BACKUP_DIR = "/opt/satdeploy/backups"


def demo_is_running() -> bool:
    """Check if the demo environment is reachable over ZMQ."""
    try:
        transport = CSPTransport(
            zmq_endpoint=f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}",
            agent_node=AGENT_NODE,
            ground_node=GROUND_NODE,
            backup_dir=BACKUP_DIR,
            timeout_ms=3000,
            zmq_pub_port=ZMQ_PUB_PORT,
            zmq_sub_port=ZMQ_SUB_PORT,
        )
        transport.connect()
        status = transport.get_status()
        transport.disconnect()
        return isinstance(status, dict)
    except Exception:
        return False


# Skip all tests if demo isn't running
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not demo_is_running(),
        reason="Demo environment not running (start with: satdeploy demo start)",
    ),
]


@pytest.fixture
def transport():
    """Create a connected CSP transport to the live demo."""
    t = CSPTransport(
        zmq_endpoint=f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}",
        agent_node=AGENT_NODE,
        ground_node=GROUND_NODE,
        backup_dir=BACKUP_DIR,
        timeout_ms=10000,
        zmq_pub_port=ZMQ_PUB_PORT,
        zmq_sub_port=ZMQ_SUB_PORT,
    )
    t.connect()
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


# ─── ZMQ connectivity ─────────────────────────────────────────────


class TestZMQConnectivity:
    """Test raw ZMQ socket connectivity to zmqproxy."""

    def test_pub_socket_connects(self):
        """PUB socket should connect to zmqproxy subscribe port."""
        ctx = zmq.Context()
        pub = ctx.socket(zmq.PUB)
        pub.setsockopt(zmq.LINGER, 0)
        pub.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}")
        # If no exception, connection succeeded
        pub.close()
        ctx.term()

    def test_sub_socket_connects(self):
        """SUB socket should connect to zmqproxy publish port."""
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        sub.connect(f"tcp://{ZMQ_HOST}:{ZMQ_SUB_PORT}")
        sub.close()
        ctx.term()

    def test_transport_connect_disconnect(self, transport):
        """Transport should connect and disconnect without error."""
        # transport fixture already connected — just verify we can call methods
        assert transport._pub is not None
        assert transport._sub is not None
        assert transport._context is not None


# ─── CSP header encoding ──────────────────────────────────────────


class TestCSPHeader:
    """Test CSP v2 header encoding/decoding with real values."""

    def test_build_header_to_agent(self, transport):
        """Header to agent node on deploy port should encode correctly."""
        header = transport._build_csp_header(AGENT_NODE, CSP_DEPLOY_PORT)
        assert len(header) == CSP_HEADER_SIZE

        parsed = transport._parse_csp_header(header)
        assert parsed["dst"] == AGENT_NODE
        assert parsed["src"] == GROUND_NODE
        assert parsed["dport"] == CSP_DEPLOY_PORT

    def test_header_roundtrip(self, transport):
        """Build + parse should return the original values."""
        for dest in [1, 100, AGENT_NODE, 16383]:  # 14-bit max
            for port in [0, 7, 8, 20, 63]:  # 6-bit max
                header = transport._build_csp_header(dest, port, src_port=5)
                parsed = transport._parse_csp_header(header)
                assert parsed["dst"] == dest
                assert parsed["dport"] == port
                assert parsed["sport"] == 5
                assert parsed["src"] == GROUND_NODE


# ─── STATUS command ───────────────────────────────────────────────


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


# ─── DEPLOY command ───────────────────────────────────────────────


class TestCSPDeploy:
    """Test DEPLOY command with real file transfer via DTP."""

    def test_deploy_new_file(self, transport, test_binary):
        """Deploying a new binary should succeed and return a hash."""
        result = transport.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        assert result.success, f"Deploy failed: {result.error_message}"
        assert result.file_hash, "Deploy should return a file hash"
        assert len(result.file_hash) == 8

    def test_deploy_changes_status_hash(self, transport, test_binary):
        """After deploy, status should show the new file hash."""
        result = transport.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        assert result.success

        status = transport.get_status()
        assert "test_app" in status
        assert status["test_app"].file_hash == result.file_hash

    def test_deploy_creates_backup(self, transport, test_binary):
        """Deploy should create a backup of the previous version."""
        # Get the current hash before deploy
        status_before = transport.get_status()
        old_hash = status_before["test_app"].file_hash

        result = transport.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        assert result.success
        assert result.backup_path, "Deploy should report a backup path"

        # The backup hash should contain the old hash
        backups = transport.list_backups("test_app")
        backup_hashes = [b.file_hash for b in backups]
        assert old_hash in backup_hashes, (
            f"Old hash {old_hash} should appear in backups: {backup_hashes}"
        )

    def test_deploy_nonexistent_app_creates_it(self, transport, test_binary):
        """Deploying to a new app name should work (agent creates it)."""
        unique_name = f"inttest_{int(time.time())}"
        result = transport.deploy(
            app_name=unique_name,
            local_path=test_binary,
            remote_path=f"/opt/demo/bin/{unique_name}",
        )
        assert result.success, f"Deploy to new app failed: {result.error_message}"

        # Verify it shows up in status
        status = transport.get_status()
        assert unique_name in status


# ─── LIST_BACKUPS command ─────────────────────────────────────────


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


# ─── ROLLBACK command ─────────────────────────────────────────────


class TestCSPRollback:
    """Test ROLLBACK command against the live agent.

    Uses fresh transport connections per operation to avoid DTP timing
    issues from accumulated ZMQ state when running the full test suite.
    """

    @staticmethod
    def _fresh_transport():
        t = CSPTransport(
            zmq_endpoint=f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}",
            agent_node=AGENT_NODE,
            ground_node=GROUND_NODE,
            backup_dir=BACKUP_DIR,
            timeout_ms=10000,
            zmq_pub_port=ZMQ_PUB_PORT,
            zmq_sub_port=ZMQ_SUB_PORT,
        )
        t.connect()
        return t

    def test_rollback_to_previous(self, test_binary):
        """Rollback should restore the previous version."""
        # Deploy a known file first
        t = self._fresh_transport()
        deploy_result = t.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        t.disconnect()
        assert deploy_result.success

        new_hash = deploy_result.file_hash

        # Now rollback
        t = self._fresh_transport()
        rollback_result = t.rollback(app_name="test_app")
        t.disconnect()
        assert rollback_result.success, f"Rollback failed: {rollback_result.error_message}"

        # Status should show a different hash
        t = self._fresh_transport()
        status = t.get_status()
        t.disconnect()
        assert status["test_app"].file_hash != new_hash, "Hash should change after rollback"

    def test_rollback_to_specific_hash(self, test_binary):
        """Rollback to a specific backup hash should restore that version."""
        # Get current state
        t = self._fresh_transport()
        status_before = t.get_status()
        original_hash = status_before["test_app"].file_hash
        t.disconnect()

        # Deploy something new
        t = self._fresh_transport()
        deploy_result = t.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        t.disconnect()
        assert deploy_result.success

        # Rollback to the original hash
        t = self._fresh_transport()
        rollback_result = t.rollback(
            app_name="test_app",
            backup_hash=original_hash,
        )
        t.disconnect()
        assert rollback_result.success

        # Verify it's back
        t = self._fresh_transport()
        status_after = t.get_status()
        t.disconnect()
        assert status_after["test_app"].file_hash == original_hash


# ─── DTP file transfer ────────────────────────────────────────────


class TestDTPTransfer:
    """Test DTP (Data Transfer Protocol) over CSP."""

    def test_small_file_transfer(self, transport):
        """Small file (<1KB) should transfer successfully."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"small payload")
            f.flush()
            path = f.name

        try:
            result = transport.deploy(
                app_name="test_app",
                local_path=path,
                remote_path="/opt/demo/bin/test_app",
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
            result = transport.deploy(
                app_name="test_app",
                local_path=path,
                remote_path="/opt/demo/bin/test_app",
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
            # Fresh transport to avoid DTP congestion from prior tests
            t = CSPTransport(
                zmq_endpoint=f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}",
                agent_node=AGENT_NODE,
                ground_node=GROUND_NODE,
                backup_dir=BACKUP_DIR,
                timeout_ms=15000,
                zmq_pub_port=ZMQ_PUB_PORT,
                zmq_sub_port=ZMQ_SUB_PORT,
            )
            t.connect()
            result = t.deploy(
                app_name="test_app",
                local_path=path,
                remote_path="/opt/demo/bin/test_app",
            )
            t.disconnect()
            assert result.success, f"Large file deploy failed: {result.error_message}"
        finally:
            os.unlink(path)

    def test_deploy_verifies_checksum(self, transport, test_binary):
        """Agent should verify the SHA256 checksum after DTP transfer."""
        from satdeploy.hash import compute_file_hash

        expected_hash = compute_file_hash(test_binary)[:8]
        result = transport.deploy(
            app_name="test_app",
            local_path=test_binary,
            remote_path="/opt/demo/bin/test_app",
        )
        assert result.success
        assert result.file_hash == expected_hash, (
            f"Agent hash {result.file_hash} != local hash {expected_hash}"
        )


# ─── Error handling ───────────────────────────────────────────────


class TestCSPErrorHandling:
    """Test error handling with real ZMQ connections."""

    def test_connect_to_wrong_port_still_connects(self):
        """ZMQ PUB/SUB connect() is non-blocking — it won't fail immediately."""
        t = CSPTransport(
            zmq_endpoint="tcp://localhost:19999",
            agent_node=AGENT_NODE,
            ground_node=GROUND_NODE,
            backup_dir=BACKUP_DIR,
            timeout_ms=1000,
            zmq_pub_port=19999,
            zmq_sub_port=19998,
        )
        # connect() succeeds because ZMQ connect is lazy
        t.connect()
        # But operations should timeout
        status = t.get_status()
        assert status == {}, "Should return empty dict on timeout"
        t.disconnect()

    def test_double_disconnect_is_safe(self, transport):
        """Calling disconnect() twice should not raise."""
        transport.disconnect()
        transport.disconnect()  # Should not raise


# ─── Full round-trip ──────────────────────────────────────────────


class TestCSPFullRoundTrip:
    """End-to-end: deploy → status → list → rollback → verify."""

    def test_full_lifecycle(self):
        """Complete deploy lifecycle through real ZMQ/CSP/DTP stack.

        Uses a fresh transport per operation to avoid DTP timing issues
        from rapid-fire requests on a single connection.
        """
        def make_transport():
            t = CSPTransport(
                zmq_endpoint=f"tcp://{ZMQ_HOST}:{ZMQ_PUB_PORT}",
                agent_node=AGENT_NODE,
                ground_node=GROUND_NODE,
                backup_dir=BACKUP_DIR,
                timeout_ms=10000,
                zmq_pub_port=ZMQ_PUB_PORT,
                zmq_sub_port=ZMQ_SUB_PORT,
            )
            t.connect()
            return t

        # 1. Record initial state
        t = make_transport()
        status_before = t.get_status()
        assert "test_app" in status_before
        original_hash = status_before["test_app"].file_hash
        t.disconnect()

        # 2. Deploy a unique file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            payload = f"lifecycle test {time.time()}".encode()
            f.write(payload)
            f.flush()
            test_file = f.name

        try:
            t = make_transport()
            result = t.deploy(
                app_name="test_app",
                local_path=test_file,
                remote_path="/opt/demo/bin/test_app",
            )
            t.disconnect()
            assert result.success, f"Deploy failed: {result.error_message}"
            new_hash = result.file_hash
            assert new_hash != original_hash, "New file should have different hash"
        finally:
            os.unlink(test_file)

        # 3. Verify status reflects the deploy
        t = make_transport()
        status_after = t.get_status()
        assert status_after["test_app"].file_hash == new_hash

        # 4. List backups — original should be there
        backups = t.list_backups("test_app")
        t.disconnect()
        backup_hashes = [b.file_hash for b in backups]
        assert original_hash in backup_hashes, (
            f"Original {original_hash} not in backups {backup_hashes}"
        )

        # 5. Rollback to original
        t = make_transport()
        rollback_result = t.rollback(
            app_name="test_app",
            backup_hash=original_hash,
        )
        t.disconnect()
        assert rollback_result.success

        # 6. Verify status is back to original
        t = make_transport()
        status_final = t.get_status()
        t.disconnect()
        assert status_final["test_app"].file_hash == original_hash
