# sat-deploy

Fast binary deployment tool for embedded Linux flatsat (satellite engineering model).

## Components

- **sat-agent**: Runs on flatsat, handles deployment commands
- **sat**: CLI tool for developer laptop (not yet implemented)

## Requirements

- Python 3.8+
- PyYAML (`pip install pyyaml`)

## Current Status

### Completed

#### sat-agent (Phase 1 complete)

| Command | Status | Description |
|---------|--------|-------------|
| `status` | Done | Returns JSON with running/stopped state of all services |
| `deploy <service>` | Done | Stops dependents, swaps binary, restarts services |
| `rollback <service>` | Done | Restore previous binary version |
| `restart <service>` | Pending | Restart service and dependents |

**Features implemented:**
- Configuration loading from YAML (path configurable via `SAT_AGENT_CONFIG` env var)
- Dependency-aware service restarts (topological ordering)
- Atomic binary deployment (backup, swap, chmod +x)
- Version logging to `versions.json`
- JSON output for all commands
- Error handling with JSON error responses

#### sat CLI (Phase 2 complete)

| Command | Status | Description |
|---------|--------|-------------|
| `status` | Done | SSH to agent, display formatted output |
| `deploy <service> <binary>` | Done | rsync + SSH to agent |
| `rollback <service>` | Done | Trigger rollback via SSH |
| `logs <service>` | Pending | Tail journalctl logs |
| `restart <service>` | Pending | Restart via SSH |

**Features implemented:**
- Configuration loading from YAML (path configurable via `SAT_CONFIG` env var)
- SSH command execution to remote flatsat
- rsync upload of binaries to remote host
- Nice terminal output with checkmarks/X marks
- Error handling for SSH and rsync failures

### Pending

#### Polish (Phase 4)
- Timing output ("Deployed in 34s")
- install-agent.sh script
- Better error messages

## Development

### Testing

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install pytest pyyaml

# Run all tests
python -m pytest tests/ -v
```

### Configuration

The sat-agent config path can be overridden for testing:

```bash
export SAT_AGENT_CONFIG=/path/to/test/config.yaml
```

Default production path: `/opt/sat-agent/config.yaml`

### Test Coverage

| Module | Tests | Status |
|--------|-------|--------|
| **sat-agent** | | |
| Config loading | 2 | Pass |
| Service status check | 2 | Pass |
| Status command | 4 | Pass |
| Dependency resolution | 6 | Pass |
| Service control | 2 | Pass |
| Binary operations | 5 | Pass |
| Deploy command | 6 | Pass |
| Rollback command | 8 | Pass |
| Main CLI | 1 | Pass |
| **sat CLI** | | |
| Config loading | 3 | Pass |
| SSH execution | 2 | Pass |
| rsync upload | 4 | Pass |
| Status command | 5 | Pass |
| Deploy command | 6 | Pass |
| Rollback command | 5 | Pass |
| Main CLI | 1 | Pass |
| **Total** | **62** | **All passing** |

## Architecture

```
Developer Laptop                         Flatsat (Yocto Linux)
+------------------+                     +------------------+
|                  |    SSH + rsync      |                  |
|  sat (CLI)       | ------------------> |  sat-agent       |
|                  |                     |                  |
|  - deploy        |    JSON responses   |  - deploy        |
|  - status        | <------------------ |  - status        |
|  - rollback      |                     |  - rollback      |
|  - logs          |                     |                  |
+------------------+                     +------------------+
```

## Usage

See `plan.md` for full specification.

### sat-agent Commands (on flatsat)

```bash
# Check status of all services
./sat_agent.py status
# {"status": "ok", "services": {"controller": "running", ...}}

# Deploy a service (binary must be uploaded as <path>.new first)
./sat_agent.py deploy controller
# {"status": "ok", "service": "controller", "hash": "a3f2c9b1"}
```

### sat CLI Commands (on developer laptop)

```bash
# Check status of all services
./sat.py status
# [+] controller: running
# [+] csp_server: running
# [+] param_handler: running

# Deploy a service
./sat.py deploy controller ./build/controller
# [~] Uploading controller...
# [~] Deploying controller...
# [+] Deployed controller (a3f2c9b1)

# Rollback a service
./sat.py rollback controller
# [~] Rolling back controller...
# [+] Rolled back controller (prev_hash)
```

## File Structure

```
sat-deploy/
├── sat_agent.py              # Agent script (runs on flatsat)
├── sat.py                    # CLI script (runs on developer laptop)
├── config.yaml               # Configuration for CLI
├── pyproject.toml            # Project configuration
├── tests/
│   ├── test_sat_agent.py     # 27 agent unit tests
│   └── test_sat.py           # 20 CLI unit tests
├── notes/
│   └── features/             # Feature development notes
├── plan.md                   # Full specification
└── README.md
```
