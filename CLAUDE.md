# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

sat-deploy is a deployment system for embedded Linux targets (satellites) via CSP/csh. It consists of:

- **satdeploy** (Python CLI) - Ground station tool for SSH-based deployment
- **satdeploy-agent** (C) - Runs on ARM target, handles deploy/rollback/status via CSP
- **satdeploy-apm** (C) - csh slash commands for ground station, talks to agent via CSP

## CRITICAL: Cross-Compilation

The **satdeploy-agent** runs on ARM targets (aarch64/cortex-a53). You MUST cross-compile:

```bash
# 1. Source Yocto SDK environment
source /opt/poky/environment-setup-armv8a-poky-linux

# 2. Build for ARM target
cd satdeploy-agent
meson setup build-arm --cross-file yocto_cross.ini
ninja -C build-arm

# The ARM binary is: build-arm/satdeploy-agent
```

**DO NOT** use the `build/` directory for deployment - that's x86 native builds for local testing only.

## Build Commands

### satdeploy-agent (ARM target)
```bash
source /opt/poky/environment-setup-armv8a-poky-linux
cd satdeploy-agent
meson setup build-arm --cross-file yocto_cross.ini --wipe  # --wipe to reconfigure
ninja -C build-arm
# Deploy: build-arm/satdeploy-agent
```

### satdeploy-apm (Ground station csh module)
```bash
cd satdeploy-apm
meson setup build --wipe
ninja -C build
# Install: cp build/libcsh_satdeploy_apm.so /root/.local/lib/csh/
```

### Python CLI (development)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

## CLI Usage

```bash
satdeploy init                     # Interactive setup
satdeploy push <app>               # Deploy binary
satdeploy status                   # Show service states
satdeploy list <app>               # List all versions (deployed + backups)
satdeploy rollback <app>           # Restore previous version
satdeploy logs <app>               # Show journalctl logs
```

## Architecture

### Module Responsibilities

- **cli.py**: Click command handlers - orchestrates the workflow using other modules
- **ssh.py**: SSH connection wrapper around paramiko - `SSHClient` context manager for connections
- **deployer.py**: Backup/deploy/rollback logic - handles file operations on remote
- **services.py**: Systemd service management - start/stop/status via SSH
- **dependencies.py**: Topological sort for service stop/start order based on `depends_on` config
- **history.py**: SQLite database for tracking deployments in `~/.satdeploy/history.db`
- **config.py**: YAML config loading from `~/.satdeploy/config.yaml`
- **output.py**: CLI output formatting (symbols, colors, step counters)

### Deployment Flow

When `push` is called:
1. Load config, resolve dependencies
2. Stop services top-down (dependents first)
3. Backup current remote binary to `{backup_dir}/{app}/{timestamp}.bak`
4. Upload new binary via SFTP
5. Start services bottom-up (dependencies first)
6. Log to history.db

### Dependency Resolution

The `DependencyResolver` builds a graph from `depends_on` config entries. For libraries with `restart` lists, it uses those directly instead of computing dependencies.

Stop order: Dependents first (top-down)
Start order: Dependencies first (bottom-up)

### Config Structure

```yaml
target:
  host: 192.168.1.50
  user: root

backup_dir: /opt/satdeploy/backups
max_backups: 10

apps:
  controller:
    local: ./build/controller        # Local binary path
    remote: /opt/disco/bin/controller # Remote deployment path
    service: controller.service       # Systemd service (null for libraries)
    depends_on: [csp_server]          # Services this depends on

  libparam:
    service: null
    restart: [csp_server, controller] # Services to restart when lib changes
```

## Testing

Tests use pytest with pytest-mock. Each CLI command has its own test file (`test_cli_*.py`). Module tests mock SSH connections and verify behavior without real network calls.

Test config fixtures create temporary `~/.satdeploy` directories with sample config.yaml files.
