## satdeploy CSP/DTP Implementation Plan

---

### Goal

Enable satdeploy to deploy binaries to DISCO-2 satellites over CSP/DTP, replacing SSH/SFTP for radio and CAN bus links.

---

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GROUND STATION                                    │
│                                                                             │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                        satdeploy (Python)                             │  │
│   │                                                                       │  │
│   │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │  │
│   │   │ Transport:      │  │ Transport:      │  │ DTP Server          │  │  │
│   │   │ SSH (existing)  │  │ CSP (new)       │  │ (serves binaries)   │  │  │
│   │   └─────────────────┘  └─────────────────┘  └─────────────────────┘  │  │
│   │                              │                        ▲               │  │
│   └──────────────────────────────┼────────────────────────┼───────────────┘  │
│                                  │                        │                  │
│                                  │ ZMQ                    │ DTP              │
│                                  ▼                        │                  │
│                        ┌─────────────────┐                │                  │
│                        │ GND Router ZMQ  │                │                  │
│                        │ Node: 4040      │                │                  │
│                        └────────┬────────┘                │                  │
│                                 │                         │                  │
└─────────────────────────────────┼─────────────────────────┼──────────────────┘
                                  │ CSP                     │
                                  │                         │
┌─────────────────────────────────┼─────────────────────────┼──────────────────┐
│                          SATELLITE                        │                  │
│                                 │                         │                  │
│   SOM1                          │                         │                  │
│   ┌─────────────────────────────┼─────────────────────────┼───────────────┐  │
│   │                             │                         │               │  │
│   │   ┌─────────────────────────▼─────────────────────────┼────────────┐  │  │
│   │   │              a53-app-sys-manager                  │            │  │  │
│   │   │              Node: 5421 (APPSYS)                  │            │  │  │
│   │   │                                                   │            │  │  │
│   │   │   Params:                                         │            │  │  │
│   │   │   - mng_satdeploy_agent = 5424                    │            │  │  │
│   │   │   - mng_camera_control = 5422                     │            │  │  │
│   │   │   - mng_dipp = 5423                               │            │  │  │
│   │   └───────────────────────────────────────────────────┼────────────┘  │  │
│   │                         │ spawns                      │               │  │
│   │                         ▼                             │               │  │
│   │   ┌───────────────────────────────────────────────────┼────────────┐  │  │
│   │   │              satdeploy-agent (NEW)                │            │  │  │
│   │   │              Node: 5424                           │            │  │  │
│   │   │              Port: 20                             │            │  │  │
│   │   │                                                   │            │  │  │
│   │   │   • Receives deploy commands ◄────────────────────┘            │  │  │
│   │   │   • DTP client (pulls binaries from ground) ───────────────────┘  │  │
│   │   │   • Backup/restore management                                     │  │
│   │   │   • Controls apps via libparam → a53-app-sys-manager              │  │
│   │   └───────────────────────────────────────────────────────────────────┘  │
│   │                                                                          │
│   │   ┌────────────────────┐  ┌────────────────────┐                        │
│   │   │ DiscoCameraControl │  │ DIPP               │                        │
│   │   │ Node: 5422         │  │ Node: 5423         │                        │
│   │   └────────────────────┘  └────────────────────┘                        │
│   │                                                                          │
│   └──────────────────────────────────────────────────────────────────────────┘
│                                                                              │
│   SOM2 (identical: nodes 5426, 5427, 5428, 5429)                            │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### CSP Node Addresses

| Node | SOM1 | SOM2 | Role |
|------|------|------|------|
| APPSYS | 5421 | 5426 | a53-app-sys-manager |
| CC | 5422 | 5427 | DiscoCameraController |
| DIPP | 5423 | 5428 | DIPP |
| AGENT | 5424 | 5429 | satdeploy-agent (replaces util) |
| GND Router | 4040 | - | Ground station ZMQ entry |

---

### Protocol

**CSP Port 20** - Deploy commands

| Command | Description |
|---------|-------------|
| CMD_STATUS | Query agent status, list deployed apps |
| CMD_DEPLOY | Stop app, backup, download binary, install, start app |
| CMD_ROLLBACK | Restore previous version |
| CMD_LIST_VERSIONS | List available backups for an app |
| CMD_VERIFY | Check installed binary checksum |

**Protobuf Messages**

`DeployRequest`:
- command (enum)
- app_name
- param_name (e.g., "mng_dipp")
- appsys_node (e.g., 5421)
- run_node (e.g., 5423 for DIPP)
- remote_path
- dtp_server_addr
- payload_id
- expected_checksum
- expected_size
- rollback_hash (for rollback command)

`DeployResponse`:
- success
- error_code
- error_message
- backups (list, for LIST_VERSIONS)
- actual_checksum (for VERIFY)

---

### Deployment Flow

```
satdeploy push dipp -m som1-csp

Ground (satdeploy)                              Satellite (satdeploy-agent)
       │                                                 │
       │  1. Connect ZMQ to 4040                        │
       │                                                 │
       │  2. Start DTP server (serve dipp binary)       │
       │                                                 │
       │  3. CMD_DEPLOY ────────────────────────────────►│
       │     app: dipp                                   │
       │     param: mng_dipp                             │
       │     appsys_node: 5421                           │
       │     run_node: 5423                              │
       │     remote_path: /usr/bin/dipp                  │
       │     dtp_server: <ground_addr>                   │
       │     payload_id: X                               │
       │     checksum: Y                                 │
       │                                                 │
       │                                                 │  4. param set mng_dipp 0
       │                                                 │     (on node 5421)
       │                                                 │
       │                                                 │  5. Backup /usr/bin/dipp
       │                                                 │
       │                                                 │  6. DTP download from ground
       │  ◄──────────────────────────────────────────────│
       │     (agent pulls binary)                        │
       │                                                 │
       │                                                 │  7. Verify checksum
       │                                                 │
       │                                                 │  8. Install to /usr/bin/dipp
       │                                                 │
       │                                                 │  9. param set mng_dipp 5423
       │                                                 │     (on node 5421)
       │                                                 │
       │  10. DeployResponse(success) ◄──────────────────│
       │                                                 │
```

---

### Config Structure

```yaml
modules:
  som1-ssh:
    transport: ssh
    host: 192.168.1.10
    user: root

  som2-ssh:
    transport: ssh
    host: 192.168.1.11
    user: root

  som1-csp:
    transport: csp
    zmq_endpoint: tcp://localhost:4040
    appsys_node: 5421
    agent_node: 5424

  som2-csp:
    transport: csp
    zmq_endpoint: tcp://localhost:4040
    appsys_node: 5426
    agent_node: 5429

apps:
  a53-app-sys-manager:
    local: ./build/a53-app-sys-manager
    remote: /usr/bin/a53-app-sys-manager
    service: a53-app-sys-manager.service

  satdeploy-agent:
    local: ./build/satdeploy-agent
    remote: /usr/bin/satdeploy-agent
    param: mng_satdeploy_agent

  camera-control:
    local: ./build/DiscoCameraController
    remote: /usr/bin/DiscoCameraController
    param: mng_camera_control

  dipp:
    local: ./build/dipp
    remote: /usr/bin/dipp
    param: mng_dipp
```

---

### CLI Usage

```bash
# SSH transport (existing)
satdeploy push dipp -m som1-ssh
satdeploy status -m som1-ssh
satdeploy rollback dipp -m som1-ssh

# CSP transport (new, same commands)
satdeploy push dipp -m som1-csp
satdeploy status -m som1-csp
satdeploy rollback dipp -m som1-csp
satdeploy list dipp -m som1-csp
```

---

### File Structure

**Satellite (C)**

```
satdeploy-agent/
├── src/
│   ├── main.c                  # CSP init, spawn server thread
│   ├── deploy_handler.c        # Port 20 command handler
│   ├── param_client.c          # libparam client (talk to a53)
│   ├── backup_manager.c        # Backup/restore/list versions
│   └── dtp_download.c          # DTP client wrapper
├── proto/
│   ├── deploy.proto
│   └── deploy.pb-c.c           # Generated
├── meson.build
└── recipes/
    └── satdeploy-agent.bb      # Yocto recipe
```

**Ground (Python)**

```
satdeploy/
├── transport/
│   ├── base.py                 # Abstract Transport interface
│   ├── ssh.py                  # Existing SSH transport
│   └── csp.py                  # NEW: CSP transport
├── csp/
│   ├── client.py               # CSP client via ZMQ
│   ├── dtp_server.py           # DTP server (serve binaries)
│   └── proto/
│       ├── deploy.proto
│       └── deploy_pb2.py       # Generated
├── cli.py                      # Add transport selection
├── config.py                   # Parse transport config
├── deployer.py                 # Use Transport abstraction
└── services.py                 # Adapt for param-based control
```

---

### Transport Interface

Both SSH and CSP transports implement:

| Method | SSH | CSP |
|--------|-----|-----|
| `connect()` | SSH connection | ZMQ socket to 4040 |
| `disconnect()` | Close SSH | Close ZMQ |
| `stop_app(app)` | systemctl stop | CMD_DEPLOY triggers param set 0 |
| `start_app(app)` | systemctl start | CMD_DEPLOY triggers param set X |
| `upload_binary(local, remote)` | SFTP put | DTP (agent pulls) |
| `backup(app)` | cp on remote | CMD_DEPLOY does backup |
| `rollback(app, hash)` | cp backup | CMD_ROLLBACK |
| `list_versions(app)` | ls backup dir | CMD_LIST_VERSIONS |
| `verify(app)` | sha256sum | CMD_VERIFY |
| `status()` | systemctl status | CMD_STATUS |

**Key difference:** SSH transport does each step separately. CSP transport sends one CMD_DEPLOY and agent does everything.

---

### Phases

**Phase 1: satdeploy-agent (Satellite, C)**

- CSP server on port 20
- Protobuf message handling
- libparam client (stop/start via mng_* params)
- Backup manager (backup dir, versioning, restore)
- DTP client integration (download from ground)
- Checksum verification
- Yocto recipe for meta-disco-scheduler
- Add `mng_satdeploy_agent` param to a53-app-sys-manager

**Phase 2: CSP Transport (Ground, Python)**

- CSP client via ZMQ
- DTP server (serve binaries for agent to pull)
- Protobuf message encoding/decoding
- Transport interface implementation

**Phase 3: satdeploy Integration**

- Transport abstraction in deployer
- Config parsing for CSP modules
- CLI unchanged (transport selected by module config)

**Phase 4: Testing**

- ZMQ loopback (localhost)
- CAN bus (flatsat)
- KISS/UART
- Radio link (if available)

---

### Backup Structure

On satellite:

```
/opt/satdeploy/backups/
├── dipp/
│   ├── 20250115-143022-a1b2c3d4.bak
│   ├── 20250116-091533-e5f6g7h8.bak
│   └── 20250117-120000-i9j0k1l2.bak
├── camera-control/
│   └── ...
└── satdeploy-agent/
    └── ...
```

---

### What's NOT Supported Over CSP

| Feature | SSH | CSP |
|---------|-----|-----|
| Arbitrary shell commands | ✓ | ✗ |
| Log streaming | ✓ | ✗ |
| Interactive session | ✓ | ✗ |
| File download (from sat) | ✓ | ✗ (not needed for deploy) |

---

### Success Criteria

1. `satdeploy push <app> -m som1-csp` works
2. `satdeploy rollback <app> -m som1-csp` works
3. `satdeploy status -m som1-csp` shows app states
4. `satdeploy list <app> -m som1-csp` shows versions
5. Interrupted transfers resume correctly
6. SSH transport unchanged and still works
7. Works over ZMQ, CAN, KISS interfaces

---

### Open Items

1. **Ground CSP address** - What node address does satdeploy use when connecting via ZMQ?

2. **DTP payload_id allocation** - How to generate unique IDs for each transfer?

3. **a53-app-sys-manager changes** - Adding `mng_satdeploy_agent` param and spawn logic

4. **Deploying satdeploy-agent itself** - Bootstrap problem: first deploy via SSH, then agent can update itself?
