#!/bin/bash
#
# install-agent.sh - Install sat-agent on flatsat
#
# Usage:
#   ./install-agent.sh [flatsat-host]
#
# If no host is specified, defaults to flatsat-disco.local

set -e

HOST="${1:-flatsat-disco.local}"
USER="root"
INSTALL_DIR="/opt/sat-agent"

echo "[~] Installing sat-agent to ${USER}@${HOST}..."

# Create install directory
echo "[~] Creating ${INSTALL_DIR}..."
ssh "${USER}@${HOST}" "mkdir -p ${INSTALL_DIR}/backups"

# Copy agent script
echo "[~] Copying sat_agent.py..."
rsync -az sat_agent.py "${USER}@${HOST}:${INSTALL_DIR}/sat-agent"
ssh "${USER}@${HOST}" "chmod +x ${INSTALL_DIR}/sat-agent"

# Copy config if it exists and remote config doesn't
echo "[~] Checking config..."
if ssh "${USER}@${HOST}" "[ ! -f ${INSTALL_DIR}/config.yaml ]"; then
    if [ -f config.yaml ]; then
        echo "[~] Copying config.yaml..."
        rsync -az config.yaml "${USER}@${HOST}:${INSTALL_DIR}/config.yaml"
    else
        echo "[!] Warning: No local config.yaml found"
        echo "    Create ${INSTALL_DIR}/config.yaml on the flatsat manually"
    fi
else
    echo "[~] Config already exists on remote, skipping"
fi

# Verify installation
echo "[~] Verifying installation..."
ssh "${USER}@${HOST}" "${INSTALL_DIR}/sat-agent status" || {
    echo "[x] Verification failed - check config.yaml"
    exit 1
}

echo "[+] sat-agent installed successfully to ${HOST}:${INSTALL_DIR}"
