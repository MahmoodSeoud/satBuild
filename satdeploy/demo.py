"""Zero-prerequisite demo mode for satdeploy.

Sets up a throwaway git repo + local target directory so users can run
the full push/status/rollback workflow in 10 seconds, with no Docker,
no agent container, no CSP simulator, and no satellite hardware.

The demo uses the real LocalTransport — every deploy, every hash, every
rollback is real product code hitting real files. The only difference
from a production deployment is that "remote" is a directory on the
user's own machine instead of a satellite.

After the demo clicks, the next step is `satdeploy init` to point
satdeploy at real hardware (SSH or CSP).
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import click
import yaml

from satdeploy.output import success, SatDeployError


DEMO_ROOT = Path.home() / ".satdeploy" / "demo"
DEMO_SOURCE = DEMO_ROOT / "source"       # throwaway git repo with v1+v2 binaries
DEMO_TARGET = DEMO_ROOT / "target"       # where files are "deployed" locally
DEMO_BACKUPS = DEMO_ROOT / "backups"     # versioned backups for rollback

DEFAULT_CONFIG_PATH = Path.home() / ".satdeploy" / "config.yaml"
DEMO_CONFIG_PATH = DEFAULT_CONFIG_PATH
SAVED_CONFIG_PATH = DEMO_ROOT / "saved-config.yaml"

# Deploy target inside DEMO_TARGET — mirrors a real satellite path layout
# so the demo output looks like a real deployment.
DEMO_REMOTE_PATH = "/bin/test_app"

DEMO_CONFIG = {
    "name": "demo",
    "transport": "local",
    "target_dir": str(DEMO_TARGET),
    "backup_dir": str(DEMO_BACKUPS),
    "max_backups": 5,
    "apps": {
        "test_app": {
            "local": str(DEMO_SOURCE / "test_app"),
            "remote": DEMO_REMOTE_PATH,
            "service": None,
        }
    },
}

V1_SCRIPT = """\
#!/bin/sh
echo "test_app v1.0.0 (demo)"
"""

V2_SCRIPT = """\
#!/bin/sh
echo "test_app v2.0.0 (demo) — telemetry enabled"
"""

TUTORIAL_TEXT = """\

  Ready. A throwaway git repo is at {source}
  and test_app v1.0.0 is "deployed" to {target}{remote}.

    satdeploy status             See what's running
    satdeploy push test_app      Deploy v2.0.0 (git-tagged)
    satdeploy rollback test_app  Undo the deploy in one command

  When you're done:  satdeploy demo stop
  Next step:         satdeploy init   (point at real hardware)
"""


def _git(*args: str, cwd: Path) -> None:
    """Run a git command in cwd, raising on failure."""
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_source_repo() -> None:
    """Create a throwaway git repo with two commits (v1 then v2).

    satdeploy reads git provenance from the directory containing the
    binary being deployed. By committing v1 and v2 to real git commits,
    every `push` and `rollback` gets real git hashes in the demo output
    — which is the whole point: showing the user that satdeploy tracks
    which commit made it to the target.
    """
    if DEMO_SOURCE.exists():
        shutil.rmtree(DEMO_SOURCE)
    DEMO_SOURCE.mkdir(parents=True)

    _git("init", "-q", "-b", "main", cwd=DEMO_SOURCE)
    # Scope user config to this repo so we don't touch ~/.gitconfig
    _git("config", "user.email", "demo@satdeploy.local", cwd=DEMO_SOURCE)
    _git("config", "user.name", "satdeploy demo", cwd=DEMO_SOURCE)

    binary = DEMO_SOURCE / "test_app"

    binary.write_text(V1_SCRIPT)
    binary.chmod(0o755)
    _git("add", "test_app", cwd=DEMO_SOURCE)
    _git("commit", "-q", "-m", "feat: initial test_app v1.0.0", cwd=DEMO_SOURCE)

    binary.write_text(V2_SCRIPT)
    _git("add", "test_app", cwd=DEMO_SOURCE)
    _git(
        "commit", "-q",
        "-m", "feat: enable telemetry (test_app v2.0.0)",
        cwd=DEMO_SOURCE,
    )


def _install_v1_to_target() -> None:
    """Pre-install v1 on the local target so `status` shows it deployed.

    After the demo sets up the git repo at v2 (HEAD), we also temporarily
    check out v1 to write it to the target dir, then return HEAD to v2 so
    the user's next `push` deploys v2 as an upgrade.
    """
    resolved_target = DEMO_TARGET / DEMO_REMOTE_PATH.lstrip("/")
    resolved_target.parent.mkdir(parents=True, exist_ok=True)

    # Get the first commit's content for v1
    result = subprocess.run(
        ["git", "show", "HEAD~1:test_app"],
        cwd=str(DEMO_SOURCE),
        capture_output=True,
        text=True,
        check=True,
    )
    resolved_target.write_text(result.stdout)
    resolved_target.chmod(0o755)


def _write_demo_config() -> None:
    """Write the demo config to the default config path, backing up any existing one."""
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    DEMO_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DEMO_CONFIG_PATH.exists():
        try:
            with open(DEMO_CONFIG_PATH) as f:
                existing = yaml.safe_load(f)
            if existing and existing.get("name") != "demo":
                shutil.copy2(DEMO_CONFIG_PATH, SAVED_CONFIG_PATH)
        except (yaml.YAMLError, OSError):
            pass

    with open(DEMO_CONFIG_PATH, "w") as f:
        yaml.dump(DEMO_CONFIG, f, default_flow_style=False)


def _reset_demo_history() -> None:
    """Remove the demo history db so every demo start is a clean slate."""
    history_db = DEMO_CONFIG_PATH.parent / "history.db"
    if history_db.exists():
        history_db.unlink()


def _seed_demo_history() -> None:
    """Seed history with a v1 push record so the baseline `status` shows deployed.

    Computes the real hash of the v1 binary sitting on the target and
    the real git hash of the v1 commit, so every line of the baseline
    output is honest.
    """
    import hashlib
    from satdeploy.history import DeploymentRecord, History
    from satdeploy.provenance import capture_provenance

    resolved_target = DEMO_TARGET / DEMO_REMOTE_PATH.lstrip("/")
    if not resolved_target.exists():
        return

    file_hash = hashlib.sha256(resolved_target.read_bytes()).hexdigest()[:8]

    # Git provenance for v1 — we get it by asking git about HEAD~1
    # directly, since the source binary on disk is at HEAD (v2).
    git_hash_full = subprocess.run(
        ["git", "rev-parse", "--short=8", "HEAD~1"],
        cwd=str(DEMO_SOURCE),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git_provenance = f"main@{git_hash_full}"

    history_db = DEMO_CONFIG_PATH.parent / "history.db"
    history = History(history_db)
    history.init_db()
    history.record(DeploymentRecord(
        app="test_app",
        file_hash=file_hash,
        remote_path=DEMO_REMOTE_PATH,
        action="push",
        success=True,
        module="demo",
        git_hash=git_provenance,
        provenance_source="local",
    ))


def demo_start() -> None:
    """Set up the dockerless demo environment."""
    # Friendly preflight: git is the only hard dependency
    if not shutil.which("git"):
        raise SatDeployError(
            "git is required for the demo (used to track provenance). "
            "Install git and try again."
        )

    click.echo("Setting up demo environment...")

    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    if DEMO_TARGET.exists():
        shutil.rmtree(DEMO_TARGET)
    DEMO_TARGET.mkdir(parents=True)
    if DEMO_BACKUPS.exists():
        shutil.rmtree(DEMO_BACKUPS)
    DEMO_BACKUPS.mkdir(parents=True)

    _init_source_repo()
    _install_v1_to_target()
    _write_demo_config()
    _reset_demo_history()
    _seed_demo_history()

    click.echo(success(f"Demo config written to {DEMO_CONFIG_PATH}"))
    click.echo(TUTORIAL_TEXT.format(
        source=DEMO_SOURCE,
        target=DEMO_TARGET,
        remote=DEMO_REMOTE_PATH,
    ))


def demo_stop(clean: bool = False) -> None:
    """Tear down the demo environment."""
    if DEMO_ROOT.exists() and not clean:
        # Keep the saved-config backup if present; remove everything else.
        for child in DEMO_ROOT.iterdir():
            if child.name == "saved-config.yaml":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        click.echo(success("Demo target and backups removed"))

    _reset_demo_history()

    # Restore the user's real config if we stashed one
    if SAVED_CONFIG_PATH.exists():
        shutil.move(str(SAVED_CONFIG_PATH), str(DEMO_CONFIG_PATH))
        click.echo(success("Restored your previous config"))
    elif DEMO_CONFIG_PATH.exists():
        try:
            with open(DEMO_CONFIG_PATH) as f:
                existing = yaml.safe_load(f)
            if existing and existing.get("name") == "demo":
                DEMO_CONFIG_PATH.unlink()
                click.echo(success("Demo config removed"))
        except (yaml.YAMLError, OSError):
            pass

    if clean and DEMO_ROOT.exists():
        shutil.rmtree(DEMO_ROOT)
        click.echo(success("Removed demo files"))


def demo_status() -> None:
    """Show whether the demo environment is set up."""
    if not DEMO_ROOT.exists() or not DEMO_TARGET.exists():
        click.echo("Demo environment is not set up.")
        click.echo("Start with: satdeploy demo start")
        return

    click.echo(success("Demo environment is set up"))
    click.echo(f"  Source repo: {DEMO_SOURCE}")
    click.echo(f"  Target:      {DEMO_TARGET}")
    click.echo(f"  Backups:     {DEMO_BACKUPS}")
    click.echo(f"  Config:      {DEMO_CONFIG_PATH}")
