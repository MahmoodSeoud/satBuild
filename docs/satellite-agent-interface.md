# satdeploy-agent Interface Specification

This document describes the interface that a satellite-side `satdeploy-agent` must implement to work with the ground-side satdeploy CSP transport.

## Overview

The satdeploy-agent runs on the satellite and handles deployment commands received from the ground station via CSP. It:

1. Listens for deploy commands on CSP port 20
2. Manages app lifecycle via libparam (stop/start)
3. Downloads binaries from ground via DTP
4. Handles backup/restore operations locally

## CSP Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| Deploy Port | 20 | CSP port for deploy commands |
| DTP Port | 7 | CSP port for DTP metadata requests |
| DTP Data Port | 8 | CSP port for DTP data reception |

## Protocol Messages

All messages use Protocol Buffers. See `satdeploy/csp/proto/deploy.proto` for the full schema.

### DeployRequest

Sent from ground to satellite.

```protobuf
message DeployRequest {
    DeployCommand command = 1;  // CMD_STATUS, CMD_DEPLOY, etc.
    string app_name = 2;
    string param_name = 3;      // e.g., "mng_dipp"
    uint32 appsys_node = 4;     // a53-app-sys-manager node
    uint32 run_node = 5;        // Node where app runs
    string remote_path = 6;     // Installation path
    uint32 dtp_server_node = 7; // Ground station node
    uint32 dtp_server_port = 8; // DTP port (7)
    uint32 payload_id = 9;      // DTP payload ID
    uint32 expected_size = 10;
    string expected_checksum = 11;
    string rollback_hash = 12;  // For CMD_ROLLBACK
}
```

### DeployResponse

Sent from satellite to ground.

```protobuf
message DeployResponse {
    bool success = 1;
    uint32 error_code = 2;
    string error_message = 3;
    repeated AppStatusEntry apps = 4;    // For CMD_STATUS
    repeated BackupEntry backups = 5;    // For CMD_LIST_VERSIONS
    string actual_checksum = 6;          // For CMD_VERIFY
    string backup_path = 7;              // For CMD_DEPLOY
}
```

## Command Implementations

### CMD_STATUS

Query the status of all managed apps.

**Agent Actions:**
1. For each known app, check if running (via libparam or process check)
2. Compute SHA256 checksum of installed binary
3. Return AppStatusEntry list

### CMD_DEPLOY

Deploy a new binary version.

**Agent Actions:**
1. Stop the app: `param_set(param_name, 0)` on appsys_node
2. Backup current binary to `/opt/satdeploy/backups/<app>/<timestamp>-<hash>.bak`
3. Connect to ground DTP server and download binary
4. Verify checksum matches expected_checksum
5. Install binary to remote_path, chmod +x
6. Start the app: `param_set(param_name, run_node)` on appsys_node
7. Return success with backup_path

**Error Handling:**
- If DTP download fails, return ERR_DTP_DOWNLOAD_FAILED
- If checksum mismatch, return ERR_CHECKSUM_MISMATCH
- If param_set fails, return ERR_PARAM_SET_FAILED

### CMD_ROLLBACK

Restore a previous version.

**Agent Actions:**
1. List backups for app
2. Find matching backup (by rollback_hash, or latest if not specified)
3. Stop the app via libparam
4. Copy backup to remote_path
5. Start the app via libparam
6. Return success

### CMD_LIST_VERSIONS

List available backups for an app.

**Agent Actions:**
1. List files in `/opt/satdeploy/backups/<app>/`
2. Parse version strings from filenames
3. Return BackupEntry list sorted newest first

### CMD_VERIFY

Verify installed binary checksum.

**Agent Actions:**
1. Compute SHA256 of file at remote_path
2. Return first 8 chars of hex digest

## DTP Client Integration

The agent acts as a DTP client to download binaries:

1. Connect to ground station's DTP server (dtp_server_node:dtp_server_port)
2. Send metadata request with payload_id
3. Receive metadata response (file size, MTU, intervals)
4. Bind to local port 8 for data reception
5. Receive data packets until complete
6. Write to temporary file, then move to destination

See `/home/mseo/bins/DIPP/lib/dtp/src/dtp_client.c` for reference implementation.

## libparam Integration

Apps are controlled via libparam parameters on the a53-app-sys-manager:

- To stop app: `param_set(param_name, 0)` on appsys_node
- To start app: `param_set(param_name, run_node)` on appsys_node

The param_name and nodes are provided in the DeployRequest.

## Backup Structure

Backups are stored at:
```
/opt/satdeploy/backups/
├── dipp/
│   ├── 20250115-143022-a1b2c3d4.bak
│   └── 20250116-091533-e5f6g7h8.bak
├── camera-control/
│   └── ...
└── satdeploy-agent/
    └── ...
```

Filename format: `YYYYMMDD-HHMMSS-<hash>.bak`

## Error Codes

```
ERR_NONE = 0
ERR_UNKNOWN_COMMAND = 1
ERR_APP_NOT_FOUND = 2
ERR_PARAM_SET_FAILED = 3
ERR_BACKUP_FAILED = 4
ERR_DTP_DOWNLOAD_FAILED = 5
ERR_CHECKSUM_MISMATCH = 6
ERR_INSTALL_FAILED = 7
ERR_NO_BACKUPS = 8
ERR_BACKUP_NOT_FOUND = 9
ERR_RESTORE_FAILED = 10
```

## Example File Structure

```
satdeploy-agent/
├── src/
│   ├── main.c                  # CSP init, spawn server thread
│   ├── deploy_handler.c        # Port 20 command handler
│   ├── param_client.c          # libparam client
│   ├── backup_manager.c        # Backup/restore/list
│   └── dtp_download.c          # DTP client wrapper
├── proto/
│   ├── deploy.proto            # Copy from satdeploy
│   └── deploy.pb-c.c           # Generated protobuf-c
├── meson.build
└── recipes/
    └── satdeploy-agent.bb      # Yocto recipe
```

## Testing

To test the ground-side implementation without a real satellite:

1. Create a mock agent that responds to protobuf commands
2. Use ZMQ loopback (localhost:4040)
3. Verify protobuf encoding/decoding
4. Test DTP server file serving
