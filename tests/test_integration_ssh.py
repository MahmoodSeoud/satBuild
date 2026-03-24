"""Integration tests for SSH transport against a real SSH server.

These tests start an Alpine Docker container with sshd and exercise real
SSH/SFTP operations: connect, run commands, upload/download files,
backup creation, hash verification, and the full deploy lifecycle.

Run with:
    pytest tests/test_integration_ssh.py -m integration -v

Requires: Docker Desktop running
"""

import os
import subprocess
import tempfile
import time

import paramiko
import pytest

from satdeploy.ssh import SSHClient, SSHError
from satdeploy.transport.ssh import SSHTransport
from satdeploy.transport.base import DeployResult


SSH_PORT = 2222
SSH_USER = "root"
SSH_PASSWORD = "satdeploy_test_123"
CONTAINER_NAME = "satdeploy-ssh-test"


def docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def ssh_container():
    """Start an Alpine Docker container with sshd for SSH testing."""
    if not docker_available():
        pytest.skip("Docker not available")

    # Stop any existing test container
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
    )

    # Start container with sshd + password auth
    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", CONTAINER_NAME,
            "-p", f"{SSH_PORT}:22",
            "alpine",
            "sh", "-c",
            f"apk add --no-cache openssh coreutils && "
            f"ssh-keygen -A && "
            f"echo 'root:{SSH_PASSWORD}' | chpasswd && "
            f"echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config && "
            f"echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && "
            f"mkdir -p /opt/satdeploy/backups /opt/demo/bin && "
            f"echo 'original-v1' > /opt/demo/bin/test_app && "
            f"/usr/sbin/sshd -D",
        ],
        capture_output=True,
    )

    if result.returncode != 0:
        pytest.skip(f"Failed to start SSH container: {result.stderr.decode()}")

    # Wait for sshd to start
    for attempt in range(15):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect("localhost", port=SSH_PORT, username=SSH_USER,
                       password=SSH_PASSWORD, timeout=2)
            c.close()
            break
        except Exception:
            time.sleep(1)
    else:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
        pytest.skip("SSH container sshd failed to start within 15 seconds")

    yield {
        "host": "localhost",
        "port": SSH_PORT,
        "user": SSH_USER,
        "password": SSH_PASSWORD,
    }

    # Cleanup
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


@pytest.fixture
def ssh_client(ssh_container):
    """Create a connected SSHClient using password auth."""
    client = SSHClient(
        ssh_container["host"],
        ssh_container["user"],
        port=ssh_container["port"],
    )
    # Bypass the normal connect() to inject password auth
    client._client = paramiko.SSHClient()
    client._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client._client.connect(
        hostname=ssh_container["host"],
        port=ssh_container["port"],
        username=ssh_container["user"],
        password=ssh_container["password"],
    )
    yield client
    client.disconnect()


def make_ssh_transport(ssh_container, apps=None):
    """Create an SSHTransport with password auth to the test container."""
    from satdeploy.deployer import Deployer
    from satdeploy.services import ServiceManager

    transport = SSHTransport(
        host=ssh_container["host"],
        user=ssh_container["user"],
        backup_dir="/opt/satdeploy/backups",
        port=ssh_container["port"],
        apps=apps or {},
    )
    # Inject the SSH connection with password auth
    transport._ssh = SSHClient(
        ssh_container["host"],
        ssh_container["user"],
        port=ssh_container["port"],
    )
    transport._ssh._client = paramiko.SSHClient()
    transport._ssh._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    transport._ssh._client.connect(
        hostname=ssh_container["host"],
        port=ssh_container["port"],
        username=ssh_container["user"],
        password=ssh_container["password"],
    )
    # Initialize deployer and service manager (deploy() checks these)
    transport._deployer = Deployer(transport._ssh, "/opt/satdeploy/backups")
    transport._service_manager = ServiceManager(transport._ssh)
    return transport


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not docker_available(),
        reason="Docker not available",
    ),
]


# ─── SSH connectivity ─────────────────────────────────────────────


class TestSSHConnectivity:
    """Test real SSH connections to Docker container."""

    def test_connect_and_run_command(self, ssh_client):
        """Should connect and run a basic command."""
        result = ssh_client.run("echo hello")
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_run_command_with_nonzero_exit(self, ssh_client):
        """Non-zero exit should raise SSHError when check=True."""
        with pytest.raises(SSHError):
            ssh_client.run("exit 1")

    def test_run_command_check_false(self, ssh_client):
        """Non-zero exit should return result when check=False."""
        result = ssh_client.run("exit 42", check=False)
        assert result.exit_code == 42

    def test_run_complex_command(self, ssh_client):
        """Should handle pipes and multiline output."""
        result = ssh_client.run("echo -e 'line1\\nline2\\nline3' | wc -l")
        assert result.exit_code == 0
        assert "3" in result.stdout


# ─── SFTP operations ─────────────────────────────────────────────


class TestSFTPOperations:
    """Test real SFTP file transfer."""

    def test_upload_file(self, ssh_client):
        """Should upload a file via SFTP."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test upload content")
            f.flush()
            local_path = f.name

        try:
            ssh_client.upload(local_path, "/tmp/test_upload.txt")
            result = ssh_client.run("cat /tmp/test_upload.txt")
            assert result.stdout.strip() == "test upload content"
        finally:
            os.unlink(local_path)

    def test_download_file(self, ssh_client):
        """Should download a file via SFTP."""
        ssh_client.run("echo 'download content' > /tmp/test_download.txt")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            local_path = f.name

        try:
            ssh_client.download("/tmp/test_download.txt", local_path)
            with open(local_path) as f:
                assert "download content" in f.read()
        finally:
            os.unlink(local_path)

    def test_file_exists(self, ssh_client):
        """Should detect file existence correctly."""
        ssh_client.run("echo 'exists' > /tmp/exists.txt")
        assert ssh_client.file_exists("/tmp/exists.txt") is True
        assert ssh_client.file_exists("/tmp/nope_not_here.txt") is False

    def test_upload_binary_file(self, ssh_client):
        """Should transfer binary data correctly."""
        binary_data = bytes(range(256)) * 100  # 25.6 KB of binary
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(binary_data)
            f.flush()
            local_path = f.name

        try:
            ssh_client.upload(local_path, "/tmp/binary_test.bin")

            # Download and verify round-trip
            download_path = local_path + ".downloaded"
            ssh_client.download("/tmp/binary_test.bin", download_path)

            with open(download_path, "rb") as f:
                downloaded = f.read()
            assert downloaded == binary_data
            os.unlink(download_path)
        finally:
            os.unlink(local_path)

    def test_upload_large_file(self, ssh_client):
        """Should handle larger files (~1MB)."""
        data = os.urandom(1_000_000)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(data)
            f.flush()
            local_path = f.name

        try:
            ssh_client.upload(local_path, "/tmp/large_test.bin")
            result = ssh_client.run("wc -c < /tmp/large_test.bin")
            assert int(result.stdout.strip()) == 1_000_000
        finally:
            os.unlink(local_path)


# ─── SSH transport: deploy lifecycle ──────────────────────────────


class TestSSHTransportDeploy:
    """Test SSHTransport deploy with real SSH."""

    def test_deploy_uploads_file(self, ssh_container, ssh_client):
        """Deploy should upload the file to the remote path."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"deployed binary v2")
            f.flush()
            local_path = f.name

        try:
            transport = make_ssh_transport(ssh_container)
            result = transport.deploy(
                app_name="test_app",
                local_path=local_path,
                remote_path="/opt/demo/bin/test_app",
            )
            transport.disconnect()

            assert result.success, f"Deploy failed: {result.error_message}"

            # Verify the file was uploaded
            check = ssh_client.run("cat /opt/demo/bin/test_app")
            assert check.stdout.strip() == "deployed binary v2"
        finally:
            os.unlink(local_path)

    def test_deploy_creates_backup(self, ssh_container, ssh_client):
        """Deploy should backup the existing file before overwriting."""
        # Ensure there's an existing file
        ssh_client.run("echo 'v1-for-backup' > /opt/demo/bin/backup_test")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"v2-new")
            f.flush()
            local_path = f.name

        try:
            transport = make_ssh_transport(ssh_container)
            result = transport.deploy(
                app_name="backup_test",
                local_path=local_path,
                remote_path="/opt/demo/bin/backup_test",
            )
            transport.disconnect()

            assert result.success
            assert result.backup_path, "Deploy should report a backup path"

            # Verify backup was created
            backups = ssh_client.run(
                "ls /opt/satdeploy/backups/backup_test/", check=False,
            )
            assert backups.exit_code == 0
            assert ".bak" in backups.stdout
        finally:
            os.unlink(local_path)

    def test_deploy_returns_file_hash(self, ssh_container):
        """Deploy result should include the file hash."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"hash test payload")
            f.flush()
            local_path = f.name

        try:
            from satdeploy.hash import compute_file_hash
            expected = compute_file_hash(local_path)[:8]

            transport = make_ssh_transport(ssh_container)
            result = transport.deploy(
                app_name="hash_test",
                local_path=local_path,
                remote_path="/opt/demo/bin/hash_test",
            )
            transport.disconnect()

            assert result.success
            assert result.file_hash == expected
        finally:
            os.unlink(local_path)


# ─── Hash verification ────────────────────────────────────────────


class TestSSHHashVerification:
    """Test file hash computation over SSH."""

    def test_remote_hash_matches_local(self, ssh_client):
        """SHA256 hash computed remotely should match local computation."""
        from satdeploy.hash import compute_file_hash

        content = b"hash verification test content"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(content)
            f.flush()
            local_path = f.name

        try:
            local_hash = compute_file_hash(local_path)  # 8-char truncated

            ssh_client.upload(local_path, "/tmp/hash_test.bin")
            result = ssh_client.run("sha256sum /tmp/hash_test.bin")
            remote_full_hash = result.stdout.split()[0]

            # compute_file_hash returns first 8 chars of SHA256
            assert remote_full_hash.startswith(local_hash), (
                f"Remote hash {remote_full_hash[:8]} != local hash {local_hash}"
            )
        finally:
            os.unlink(local_path)


# ─── Full round-trip ──────────────────────────────────────────────


class TestSSHFullRoundTrip:
    """End-to-end: deploy → verify → backup check."""

    def test_deploy_verify_backup(self, ssh_container, ssh_client):
        """Full lifecycle: deploy a file, verify it's there, check backup exists."""
        from satdeploy.hash import compute_file_hash

        # 1. Set up initial state
        ssh_client.run("echo 'original' > /opt/demo/bin/lifecycle_app")

        # 2. Deploy new version
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"new version payload")
            f.flush()
            local_path = f.name

        try:
            expected_hash = compute_file_hash(local_path)[:8]

            transport = make_ssh_transport(ssh_container)
            result = transport.deploy(
                app_name="lifecycle_app",
                local_path=local_path,
                remote_path="/opt/demo/bin/lifecycle_app",
            )
            transport.disconnect()

            assert result.success
            assert result.file_hash == expected_hash

            # 3. Verify file content
            check = ssh_client.run("cat /opt/demo/bin/lifecycle_app")
            assert check.stdout.strip() == "new version payload"

            # 4. Verify backup exists and contains old content
            backups = ssh_client.run("ls /opt/satdeploy/backups/lifecycle_app/")
            bak_files = [f for f in backups.stdout.strip().split("\n") if f.endswith(".bak")]
            assert len(bak_files) >= 1

            bak_content = ssh_client.run(
                f"cat /opt/satdeploy/backups/lifecycle_app/{bak_files[0]}"
            )
            assert "original" in bak_content.stdout
        finally:
            os.unlink(local_path)
