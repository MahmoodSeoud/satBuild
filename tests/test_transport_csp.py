"""Tests for the CSP transport implementation using libcsp."""

from unittest.mock import MagicMock, patch
import struct
import pytest

from satdeploy.transport.base import (
    Transport,
    TransportError,
    DeployResult,
    AppStatus,
    BackupInfo,
)
from satdeploy.transport.csp import CSPTransport, CSP_DEPLOY_PORT
from satdeploy.csp.proto import DeployCommand, DeployRequest, DeployResponse


@pytest.fixture
def mock_libcsp():
    """Mock libcsp_py3 module."""
    with patch("satdeploy.transport.csp.libcsp") as mock:
        # Provide constants
        mock.CSP_PRIO_NORM = 2
        mock.CSP_O_NONE = 0
        mock.CSP_O_RDP = 1
        mock.CSP_SO_RDPREQ = 0x04
        mock.CSP_SO_CONN_LESS = 0x40

        # Error exception class
        mock.Error = type("Error", (Exception,), {})

        yield mock


@pytest.fixture
def mock_dtp():
    """Create DTPServer mock."""
    with patch("satdeploy.transport.csp.DTPServer") as mock:
        yield mock


def make_transaction_response(mock_libcsp, response: DeployResponse):
    """Configure mock_libcsp.transaction to return the serialized response.

    The transaction() mock fills the inbuf (arg index 5) with serialized
    protobuf data and returns the length.
    """
    serialized = response.SerializeToString()

    def transaction_side_effect(prio, dest, port, timeout, outbuf, inbuf, *args):
        inbuf[:len(serialized)] = serialized
        return len(serialized)

    mock_libcsp.transaction.side_effect = transaction_side_effect


class TestCSPTransportInterface:
    """Test that CSPTransport implements Transport interface."""

    def test_csp_transport_is_transport(self):
        """CSPTransport is a Transport subclass."""
        assert issubclass(CSPTransport, Transport)

    def test_csp_transport_instantiation(self):
        """CSPTransport can be instantiated with required params."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/opt/satdeploy/backups",
        )
        assert transport.zmq_endpoint == "tcp://localhost:6000"
        assert transport.zmq_host == "localhost"
        assert transport.agent_node == 5424
        assert transport.ground_node == 40

    def test_zmq_host_parsing(self):
        """Host is extracted from various zmq_endpoint formats."""
        t1 = CSPTransport(zmq_endpoint="tcp://192.168.1.5:6000",
                          agent_node=1, ground_node=2, backup_dir="/b")
        assert t1.zmq_host == "192.168.1.5"

        t2 = CSPTransport(zmq_endpoint="tcp://satcom:4040",
                          agent_node=1, ground_node=2, backup_dir="/b")
        assert t2.zmq_host == "satcom"

        t3 = CSPTransport(zmq_endpoint="localhost",
                          agent_node=1, ground_node=2, backup_dir="/b")
        assert t3.zmq_host == "localhost"


class TestCSPTransportConnection:
    """Test CSP connection handling via libcsp."""

    @patch("satdeploy.transport.csp._csp_initialized", False)
    def test_connect_initializes_libcsp(self, mock_libcsp):
        """connect() calls libcsp.init(), zmqhub_init(), rtable_load(), route_start_task()."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        mock_libcsp.init.assert_called_once_with("satdeploy", "ground", "0.1")
        mock_libcsp.zmqhub_init.assert_called_once_with(40, "localhost", True)
        mock_libcsp.rtable_load.assert_called_once_with("0/0 ZMQHUB")
        mock_libcsp.route_start_task.assert_called_once()

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_connect_skips_reinit(self, mock_libcsp):
        """connect() skips init when already initialized."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        mock_libcsp.init.assert_not_called()
        assert transport._connected is True

    def test_disconnect_stops_dtp_server(self, mock_libcsp):
        """disconnect() stops DTP server and resets connected state."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        mock_dtp_server = MagicMock()
        transport._dtp_server = mock_dtp_server
        transport._connected = True

        transport.disconnect()

        mock_dtp_server.stop.assert_called_once()
        assert transport._connected is False
        assert transport._dtp_server is None

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_context_manager(self, mock_libcsp):
        """CSPTransport works as context manager."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )

        with transport:
            assert transport._connected is True

        assert transport._connected is False


class TestCSPTransportDeploy:
    """Test CSP deployment operations."""

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_deploy_sends_command(self, mock_libcsp, mock_dtp, tmp_path):
        """deploy() sends CMD_DEPLOY via libcsp.transaction()."""
        binary = tmp_path / "test_app"
        binary.write_bytes(b"test binary content")

        response = DeployResponse()
        response.success = True
        response.backup_path = "/backups/app/123.bak"
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        result = transport.deploy(
            app_name="dipp",
            local_path=str(binary),
            remote_path="/usr/bin/dipp",
            param_name="mng_dipp",
            appsys_node=5421,
            run_node=5423,
        )

        assert result.success is True
        assert result.backup_path == "/backups/app/123.bak"
        mock_libcsp.transaction.assert_called_once()
        mock_dtp.return_value.start.assert_called_once()
        mock_dtp.return_value.stop.assert_called_once()

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_deploy_sets_file_mode(self, mock_libcsp, mock_dtp, tmp_path):
        """deploy() sets file_mode from source file in the CSP request."""
        binary = tmp_path / "test_app"
        binary.write_bytes(b"test binary content")
        binary.chmod(0o644)

        response = DeployResponse()
        response.success = True
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        result = transport.deploy(
            app_name="dipp",
            local_path=str(binary),
            remote_path="/usr/bin/dipp",
        )

        assert result.success is True
        # Verify the sent request contains file_mode by inspecting the
        # outbuf that was passed to transaction()
        call_args = mock_libcsp.transaction.call_args
        outbuf = call_args[0][4]  # positional arg index 4 is outbuf
        request = DeployRequest()
        request.ParseFromString(bytes(outbuf))
        import os, stat
        assert request.file_mode == stat.S_IMODE(os.stat(str(binary)).st_mode)

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_deploy_handles_failure(self, mock_libcsp, mock_dtp, tmp_path):
        """deploy() handles agent failure response."""
        binary = tmp_path / "test_app"
        binary.write_bytes(b"test binary content")

        response = DeployResponse()
        response.success = False
        response.error_code = 6
        response.error_message = "Checksum verification failed"
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        result = transport.deploy(
            app_name="dipp",
            local_path=str(binary),
            remote_path="/usr/bin/dipp",
        )

        assert result.success is False
        assert result.error_code == 6
        assert "Checksum" in result.error_message


class TestCSPTransportRollback:
    """Test CSP rollback operations."""

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_rollback_sends_command(self, mock_libcsp):
        """rollback() sends CMD_ROLLBACK via libcsp.transaction()."""
        response = DeployResponse()
        response.success = True
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        result = transport.rollback(app_name="dipp")

        assert result.success is True
        mock_libcsp.transaction.assert_called_once()


class TestCSPTransportStatus:
    """Test CSP status queries."""

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_get_status_queries_agent(self, mock_libcsp):
        """get_status() sends CMD_STATUS and parses response."""
        response = DeployResponse()
        response.success = True
        app_status = response.apps.add()
        app_status.app_name = "dipp"
        app_status.running = True
        app_status.file_hash = "abc12345"
        app_status.remote_path = "/usr/bin/dipp"
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        status = transport.get_status()

        assert "dipp" in status
        assert status["dipp"].running is True
        assert status["dipp"].file_hash == "abc12345"


class TestCSPTransportListBackups:
    """Test CSP backup listing."""

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_list_backups_queries_agent(self, mock_libcsp):
        """list_backups() sends CMD_LIST_VERSIONS and parses response."""
        response = DeployResponse()
        response.success = True
        backup = response.backups.add()
        backup.version = "20250115-143022-abc12345"
        backup.timestamp = "2025-01-15 14:30:22"
        backup.hash = "abc12345"
        backup.path = "/backups/dipp/20250115-143022-abc12345.bak"
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        backups = transport.list_backups("dipp")

        assert len(backups) == 1
        assert isinstance(backups[0], BackupInfo)
        assert backups[0].file_hash == "abc12345"


class TestCSPTransportLogs:
    """Test CSP log fetching."""

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_get_logs(self, mock_libcsp):
        """get_logs() sends CMD_LOGS and returns log output."""
        response = DeployResponse()
        response.success = True
        response.log_output = "Mar 22 service started"
        make_transaction_response(mock_libcsp, response)

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport.connect()

        log_output = transport.get_logs("dipp", "dipp.service", lines=50)

        assert log_output == "Mar 22 service started"


class TestCSPTransportErrorPaths:
    """Test error and edge case paths."""

    def test_connect_raises_when_libcsp_none(self):
        """connect() raises TransportError when libcsp is not installed."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        with patch("satdeploy.transport.csp.libcsp", None):
            with pytest.raises(TransportError, match="requires libcsp_py3"):
                transport.connect()

    def test_send_request_retries_on_error(self, mock_libcsp):
        """_send_request retries and raises TransportError after exhausting retries."""
        mock_libcsp.Error = type("Error", (Exception,), {})
        mock_libcsp.transaction.side_effect = mock_libcsp.Error("timeout")

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport._connected = True

        request = DeployRequest()
        request.command = DeployCommand.CMD_STATUS

        with pytest.raises(TransportError, match="CSP transaction failed"):
            transport._send_request(request, retries=2)

        # Should have tried 3 times (1 + 2 retries)
        assert mock_libcsp.transaction.call_count == 3

    def test_send_request_succeeds_on_retry(self, mock_libcsp):
        """_send_request succeeds if a retry works after initial failure."""
        mock_libcsp.Error = type("Error", (Exception,), {})

        response = DeployResponse()
        response.success = True
        serialized = response.SerializeToString()

        call_count = [0]
        def side_effect(prio, dest, port, timeout, outbuf, inbuf, *args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise mock_libcsp.Error("transient")
            inbuf[:len(serialized)] = serialized
            return len(serialized)

        mock_libcsp.transaction.side_effect = side_effect

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        transport._connected = True

        request = DeployRequest()
        request.command = DeployCommand.CMD_STATUS

        result = transport._send_request(request, retries=1)
        assert result.success is True
        assert call_count[0] == 2

    def test_not_connected_guards(self, mock_libcsp):
        """Methods return safe defaults when not connected."""
        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        # Not connected — _connected is False by default

        assert transport.get_status() == {}
        assert transport.list_backups("app") == []
        assert transport.get_logs("app", "svc") is None

        result = transport.rollback(app_name="app")
        assert result.success is False
        assert "Not connected" in result.error_message

    @patch("satdeploy.transport.csp._csp_initialized", True)
    def test_deploy_not_connected(self, mock_libcsp, tmp_path):
        """deploy() returns failure when not connected."""
        binary = tmp_path / "test_app"
        binary.write_bytes(b"content")

        transport = CSPTransport(
            zmq_endpoint="tcp://localhost:6000",
            agent_node=5424,
            ground_node=40,
            backup_dir="/backups",
        )
        # Don't call connect()

        result = transport.deploy(
            app_name="app",
            local_path=str(binary),
            remote_path="/usr/bin/app",
        )
        assert result.success is False
        assert "Not connected" in result.error_message


class TestDTPServer:
    """Test DTP server functionality."""

    def test_dtp_meta_response_format(self):
        """dtp_meta_resp_t is 8 bytes: two little-endian uint32s."""
        from satdeploy.csp.dtp_server import DTPServer
        with patch("satdeploy.csp.dtp_server.libcsp"):
            server = DTPServer(
                local_path="/tmp/test",
                payload_id=1,
                node_address=40,
                mtu=256,
            )
            server._file_size = 1024
            resp = server._build_dtp_meta_response(512)

            size_in_bytes, total_size = struct.unpack("<II", resp)
            assert size_in_bytes == 512
            assert total_size == 1024

    def test_start_stop_lifecycle(self):
        """DTP server can be started and stopped."""
        from satdeploy.csp.dtp_server import DTPServer
        with patch("satdeploy.csp.dtp_server.libcsp") as mock_csp:
            mock_csp.CSP_SO_RDPREQ = 0x04
            mock_csp.accept.return_value = None  # no connections

            server = DTPServer(
                local_path="/dev/null",
                payload_id=1,
                node_address=40,
                mtu=256,
            )
            server.start()
            assert server._running is True

            server.stop()
            assert server._running is False
            assert server._server_thread is None

    def test_handle_dtp_request_sends_metadata_and_data(self):
        """_handle_dtp_request sends metadata response and data packets."""
        from satdeploy.csp.dtp_server import DTPServer
        with patch("satdeploy.csp.dtp_server.libcsp") as mock_csp:
            mock_csp.CSP_O_NONE = 0
            mock_csp.CSP_PRIO_NORM = 2
            mock_csp.Error = type("Error", (Exception,), {})

            server = DTPServer(
                local_path="/tmp/test",
                payload_id=1,
                node_address=40,
                mtu=256,
            )
            server._file_data = b"A" * 100
            server._file_size = 100
            server._running = True

            # Build a minimal dtp_meta_req_t (16 bytes)
            req_data = struct.pack("<IBBBBI HH",
                                   1000000, 0, 1, 0, 0, 42, 256, 0)

            mock_conn = MagicMock()
            mock_packet = MagicMock()

            server._handle_dtp_request(req_data, 5425, mock_conn, mock_packet)

            # Should have sent metadata reply
            mock_csp.buffer_get.assert_called()
            mock_csp.sendto_reply.assert_called_once()
            # Should have sent data packets via sendto
            assert mock_csp.sendto.call_count > 0

    def test_handle_dtp_request_short_request_ignored(self):
        """_handle_dtp_request ignores requests shorter than 16 bytes."""
        from satdeploy.csp.dtp_server import DTPServer
        with patch("satdeploy.csp.dtp_server.libcsp") as mock_csp:
            server = DTPServer(
                local_path="/tmp/test",
                payload_id=1,
                node_address=40,
                mtu=256,
            )
            server._file_size = 100

            server._handle_dtp_request(b"\x00" * 10, 5425, MagicMock(), MagicMock())

            mock_csp.buffer_get.assert_not_called()

    def test_send_data_packets_frees_buffer_on_error(self):
        """_send_data_packets frees CSP buffer when sendto fails."""
        from satdeploy.csp.dtp_server import DTPServer
        with patch("satdeploy.csp.dtp_server.libcsp") as mock_csp:
            mock_csp.CSP_O_NONE = 0
            mock_csp.CSP_PRIO_NORM = 2
            mock_csp.Error = type("Error", (Exception,), {})

            mock_buf = MagicMock()
            mock_csp.buffer_get.return_value = mock_buf
            # sendto fails on first call, then succeeds
            call_count = [0]
            def sendto_side(*args):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise mock_csp.Error("congestion")
            mock_csp.sendto.side_effect = sendto_side

            server = DTPServer(
                local_path="/tmp/test",
                payload_id=1,
                node_address=40,
                mtu=256,
            )
            server._file_data = b"A" * 10
            server._file_size = 10
            server._running = True

            server._send_data_packets(5425, 42, 256)

            # Buffer should have been freed on the failed attempt
            mock_csp.buffer_free.assert_called_once_with(mock_buf)
