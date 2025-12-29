## sat-deploy v0.2 Implementation Plan

### Overview

Extend sat-deploy from single-target deployment to multi-module fleet management for CubeSat FlatSat development. Primary use case: DISCO project with SOM1/SOM2 redundant payload modules.

---

### Current State (v0.1)

```
satdeploy/
├── __init__.py
├── cli.py          # Click CLI with push, rollback, history commands
├── config.py       # YAML config loading (single target)
├── deployer.py     # SSH deployment logic
├── history.py      # SQLite deployment tracking
└── utils.py        # Hash computation, helpers
```

**Current config.yaml structure:**
```yaml
target:
  host: 192.168.1.10
  user: root

backup_dir: /home/satdeploy/backups
max_backups: 10

apps:
  my-app:
    local: ./build/my-app
    remote: /usr/bin/my-app
    service: my-app.service
    depends_on: []
```

---

### Target State (v0.2)

**New config.yaml structure:**
```yaml
modules:
  som1:
    host: 192.168.1.10
    user: root
    csp_addr: 5421
    
  som2:
    host: 192.168.1.11
    user: root
    csp_addr: 5475

appsys:
  netmask: 8
  interface: 0
  baudrate: 100000
  vmem_path: /home/root/a53vmem

backup_dir: /home/satdeploy/backups
max_backups: 10

apps:
  a53-app-sys-manager:
    local: ./build/a53-app-sys-manager
    remote: /usr/bin/a53-app-sys-manager
    service: a53-app-sys-manager.service
    vmem_dir: /home/root/a53vmem
    service_template: |
      [Unit]
      Description=A53 Application System Manager
      [Service]
      Environment="GENICAM_GENTL64_PATH=:/etc/lib/VimbaX_2023-4-ARM64/cti"
      ExecStart=/usr/bin/a53-app-sys-manager {{ csp_addr }} {{ netmask }} {{ interface }} {{ baudrate }} -v {{ vmem_path }}
      Restart=always
      [Install]
      WantedBy=multi-user.target

  Disco2CameraControl:
    local: ./build/Disco2CameraControl
    remote: /usr/bin/Disco2CameraControl
    vmem_dir: /home/root/camctlvmem

  dipp:
    local: ./build/dipp
    remote: /usr/bin/dipp
    vmem_dir: /home/root/dippvmem

  upload_client:
    local: ./build/upload_client
    remote: /usr/bin/upload_client
```

---

### New CLI Commands

```bash
# Push (updated)
satdeploy push <apps...> --module <name> [--clean-vmem]
satdeploy push --all --module <name> [--clean-vmem]

# Fleet status
satdeploy fleet status

# Diff between modules
satdeploy diff <module1> <module2>

# Sync modules
satdeploy sync <source> <target> [--clean-vmem]
```

---

### Implementation Tasks

#### Task 1: Update config.py

**File:** `satdeploy/config.py`

**Changes:**

1. Add `ModuleConfig` dataclass:
```python
@dataclass
class ModuleConfig:
    name: str
    host: str
    user: str
    csp_addr: int
    netmask: int
    interface: int
    baudrate: int
    vmem_path: str
```

2. Add `AppConfig` dataclass:
```python
@dataclass
class AppConfig:
    name: str
    local: str
    remote: str
    service: str | None
    service_template: str | None
    vmem_dir: str | None
```

3. Add methods to `Config` class:
   - `get_modules() -> dict[str, ModuleConfig]` - return all modules
   - `get_module(name: str) -> ModuleConfig` - return single module with inherited appsys settings
   - `get_app(name: str) -> AppConfig` - return app config
   - `get_all_app_names() -> list[str]` - return all app names
   - `get_appsys() -> dict` - return appsys settings

4. Backward compatibility: if config has `target` instead of `modules`, treat as single module named `default`

---

#### Task 2: Create templates.py

**File:** `satdeploy/templates.py` (new file)

**Purpose:** Render service templates with module-specific values.

**Functions:**

1. `render_service_template(template: str, module: ModuleConfig) -> str`
   - Replace `{{ csp_addr }}` with `module.csp_addr`
   - Replace `{{ netmask }}` with `module.netmask`
   - Replace `{{ interface }}` with `module.interface`
   - Replace `{{ baudrate }}` with `module.baudrate`
   - Replace `{{ vmem_path }}` with `module.vmem_path`
   - Return rendered string

2. `compute_service_hash(content: str) -> str`
   - SHA256 hash of service file content
   - Used to detect if service file needs updating

---

#### Task 3: Update history.py

**File:** `satdeploy/history.py`

**Changes:**

1. Update schema - add `module` column to deployments table:
```sql
CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY,
    module TEXT NOT NULL,        -- NEW
    app TEXT NOT NULL,
    hash TEXT NOT NULL,
    remote_path TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    service_hash TEXT,           -- NEW: track service file version
    vmem_cleared INTEGER DEFAULT 0  -- NEW: 1 if vmem was cleared
);
```

2. Update `record_deployment()` to accept `module` parameter

3. Add `get_module_state(module: str) -> dict[str, DeploymentRecord]` - return last known state of all apps on a module

4. Add `get_fleet_status() -> dict[str, dict[str, DeploymentRecord]]` - return state of all modules

5. Migration: add module column to existing databases, default to `default`

---

#### Task 4: Update deployer.py

**File:** `satdeploy/deployer.py`

**Changes:**

1. Update `Deployer` class to work with modules:
   - `connect(module: ModuleConfig) -> SSHClient` - connect to specific module
   - Remove single-target assumption

2. Add `clear_vmem_dir(ssh: SSHClient, vmem_dir: str) -> None`:
```python
def clear_vmem_dir(self, ssh: SSHClient, vmem_dir: str) -> None:
    """Clear vmem directory contents, recreate empty."""
    cmd = f"rm -rf {vmem_dir}/* {vmem_dir}/.* 2>/dev/null; mkdir -p {vmem_dir}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdout.channel.recv_exit_status()  # Wait for completion
```

3. Add `upload_service(ssh: SSHClient, service_name: str, content: str) -> None`:
```python
def upload_service(self, ssh: SSHClient, service_name: str, content: str) -> None:
    """Upload service file and reload systemd."""
    remote_path = f"/etc/systemd/system/{service_name}"
    # Upload content via SFTP
    sftp = ssh.open_sftp()
    with sftp.file(remote_path, 'w') as f:
        f.write(content)
    sftp.close()
    # Reload systemd
    ssh.exec_command("systemctl daemon-reload")
```

4. Add `push_many(apps: list[str], module_name: str, clean_vmem: bool) -> None`:
```python
def push_many(self, apps: list[str], module_name: str, clean_vmem: bool = False) -> None:
    """Deploy multiple apps to a module."""
    module = self.config.get_module(module_name)
    
    with self.connect(module) as ssh:
        for app_name in apps:
            app = self.config.get_app(app_name)
            
            # 1. Clear vmem if requested and app has vmem_dir
            if clean_vmem and app.vmem_dir:
                self.clear_vmem_dir(ssh, app.vmem_dir)
            
            # 2. Backup existing binary
            self.backup_remote(ssh, app.remote)
            
            # 3. Upload new binary
            self.upload(ssh, app.local, app.remote)
            
            # 4. Handle service template if present
            if app.service_template:
                content = render_service_template(app.service_template, module)
                self.upload_service(ssh, app.service, content)
            
            # 5. Record deployment
            self.history.record_deployment(
                module=module_name,
                app=app_name,
                hash=compute_hash(app.local),
                remote_path=app.remote,
                vmem_cleared=clean_vmem and app.vmem_dir is not None
            )
        
        # 6. Restart services (once, at end)
        services_to_restart = [
            self.config.get_app(name).service 
            for name in apps 
            if self.config.get_app(name).service
        ]
        for service in set(services_to_restart):
            self.restart_service(ssh, service)
```

5. Add `get_remote_hash(ssh: SSHClient, remote_path: str) -> str | None`:
```python
def get_remote_hash(self, ssh: SSHClient, remote_path: str) -> str | None:
    """Get SHA256 hash of remote file, None if doesn't exist."""
    cmd = f"sha256sum {remote_path} 2>/dev/null | cut -d' ' -f1"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    result = stdout.read().decode().strip()
    return result if result else None
```

6. Add `check_module_online(module: ModuleConfig) -> bool`:
```python
def check_module_online(self, module: ModuleConfig) -> bool:
    """Check if module is reachable via SSH."""
    try:
        with self.connect(module, timeout=5) as ssh:
            return True
    except Exception:
        return False
```

---

#### Task 5: Add fleet.py

**File:** `satdeploy/fleet.py` (new file)

**Purpose:** Fleet-level operations across modules.

**Classes/Functions:**

1. `FleetManager` class:
```python
class FleetManager:
    def __init__(self, config: Config, history: History, deployer: Deployer):
        self.config = config
        self.history = history
        self.deployer = deployer
    
    def get_status(self) -> dict:
        """Get status of all modules and apps."""
        # For each module:
        #   - Check if online (try SSH)
        #   - If online: get live hashes of all apps
        #   - If offline: get last known state from history
        # Return structured dict
    
    def diff_modules(self, module1: str, module2: str) -> dict:
        """Compare two modules, return differences."""
        # Get state of both modules (live or from history)
        # Compare app hashes
        # Return: {app_name: {module1: hash, module2: hash, match: bool}}
    
    def sync_modules(self, source: str, target: str, clean_vmem: bool = False) -> None:
        """Sync target module to match source."""
        # 1. Get source state (must be online or have history)
        # 2. Connect to target (must be online)
        # 3. For each app where target differs from source:
        #    - Upload binary from local (local must have the file)
        #    - If app has service_template, render with target's csp_addr
        # 4. If clean_vmem, clear all vmem_dirs
        # 5. Restart affected services
```

---

#### Task 6: Update cli.py

**File:** `satdeploy/cli.py`

**Changes:**

1. Update `push` command:
```python
@cli.command()
@click.argument("apps", nargs=-1)
@click.option("--all", "all_apps", is_flag=True, help="Deploy all apps")
@click.option("--module", "-m", required=True, help="Target module")
@click.option("--clean-vmem", is_flag=True, help="Clear vmem for deployed apps")
def push(apps: tuple[str], all_apps: bool, module: str, clean_vmem: bool):
    """Deploy one or more apps to a module."""
    if not apps and not all_apps:
        raise click.UsageError("Specify app names or use --all")
    if apps and all_apps:
        raise click.UsageError("Cannot use both app names and --all")
    
    config = Config()
    history = History()
    deployer = Deployer(config, history)
    
    if all_apps:
        apps = config.get_all_app_names()
    
    deployer.push_many(list(apps), module, clean_vmem=clean_vmem)
```

2. Add `fleet` command group with `status` subcommand:
```python
@cli.group()
def fleet():
    """Fleet management commands."""
    pass

@fleet.command()
def status():
    """Show status of all modules."""
    config = Config()
    history = History()
    deployer = Deployer(config, history)
    fleet_mgr = FleetManager(config, history, deployer)
    
    status = fleet_mgr.get_status()
    # Pretty print with rich library
    # Show: module, online/offline, app, hash, last deployed
```

3. Add `diff` command:
```python
@cli.command()
@click.argument("module1")
@click.argument("module2")
def diff(module1: str, module2: str):
    """Compare two modules."""
    config = Config()
    history = History()
    deployer = Deployer(config, history)
    fleet_mgr = FleetManager(config, history, deployer)
    
    differences = fleet_mgr.diff_modules(module1, module2)
    # Pretty print differences
```

4. Add `sync` command:
```python
@cli.command()
@click.argument("source")
@click.argument("target")
@click.option("--clean-vmem", is_flag=True, help="Clear vmem on target")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def sync(source: str, target: str, clean_vmem: bool, yes: bool):
    """Sync target module to match source."""
    config = Config()
    history = History()
    deployer = Deployer(config, history)
    fleet_mgr = FleetManager(config, history, deployer)
    
    # Show what will be synced
    diff = fleet_mgr.diff_modules(source, target)
    # ... display diff ...
    
    if not yes:
        click.confirm("Proceed?", abort=True)
    
    fleet_mgr.sync_modules(source, target, clean_vmem=clean_vmem)
```

---

### File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `satdeploy/config.py` | Modify | Add ModuleConfig, AppConfig dataclasses. Add multi-module methods. Backward compat for single target. |
| `satdeploy/templates.py` | Create | Service template rendering with variable substitution. |
| `satdeploy/history.py` | Modify | Add module column. Add fleet status queries. Schema migration. |
| `satdeploy/deployer.py` | Modify | Module-aware connections. Add vmem clearing. Add service upload. Add push_many. |
| `satdeploy/fleet.py` | Create | FleetManager class for cross-module operations. |
| `satdeploy/cli.py` | Modify | Update push command. Add fleet status, diff, sync commands. |

---

### Implementation Order

1. **config.py** - Foundation, everything depends on this
2. **templates.py** - Simple, standalone
3. **history.py** - Database changes needed for tracking
4. **deployer.py** - Core deployment logic
5. **fleet.py** - Higher-level operations
6. **cli.py** - Wire everything together

---

### Testing Checklist

- [ ] Config loads old single-target format (backward compat)
- [ ] Config loads new multi-module format
- [ ] Template rendering produces correct service file
- [ ] History records deployments with module name
- [ ] History migration adds module column to existing DB
- [ ] Push single app to module works
- [ ] Push multiple apps to module works
- [ ] Push --all works
- [ ] --clean-vmem clears correct directories
- [ ] Fleet status shows online/offline correctly
- [ ] Fleet status shows last known state for offline modules
- [ ] Diff shows correct differences between modules
- [ ] Sync copies binaries and regenerates service file
- [ ] Sync with --clean-vmem clears vmem on target
