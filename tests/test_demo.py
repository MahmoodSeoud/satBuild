"""Tests for the dockerless demo mode."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from satdeploy.cli import main
from satdeploy.demo import (
    DEMO_CONFIG,
    DEMO_REMOTE_PATH,
    _init_source_repo,
    _install_v1_to_target,
    _seed_demo_history,
    _write_demo_config,
    demo_start,
    demo_status,
    demo_stop,
)
from satdeploy.history import History
from satdeploy.output import SatDeployError


@pytest.fixture
def isolated_demo(tmp_path, monkeypatch):
    """Redirect all demo paths into tmp_path so tests don't touch ~/.satdeploy."""
    root = tmp_path / "demo"
    source = root / "source"
    som1_target = root / "targets" / "som1"
    som2_target = root / "targets" / "som2"
    som1_backups = root / "backups" / "som1"
    som2_backups = root / "backups" / "som2"
    config_path = tmp_path / "config.yaml"

    # Patch module-level constants so the written config + computed target
    # dirs all live under tmp_path. `_target_dir_for` reads DEMO_ROOT at
    # call time, so patching DEMO_ROOT covers both targets transparently.
    monkeypatch.setattr("satdeploy.demo.DEMO_ROOT", root)
    monkeypatch.setattr("satdeploy.demo.DEMO_SOURCE", source)
    monkeypatch.setattr("satdeploy.demo.DEMO_TARGET", som1_target)
    monkeypatch.setattr("satdeploy.demo.DEMO_BACKUPS", som1_backups)
    monkeypatch.setattr("satdeploy.demo.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr("satdeploy.demo.DEMO_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "satdeploy.demo.SAVED_CONFIG_PATH", root / "saved-config.yaml",
    )
    monkeypatch.setitem(
        DEMO_CONFIG, "target_dir", str(som1_target),
    )
    monkeypatch.setitem(
        DEMO_CONFIG, "backup_dir", str(som1_backups),
    )
    monkeypatch.setitem(
        DEMO_CONFIG["apps"]["test_app"], "local", str(source / "test_app"),
    )

    yield {
        "root": root,
        "source": source,
        "target": som1_target,
        "backups": som1_backups,
        "som1_target": som1_target,
        "som2_target": som2_target,
        "som1_backups": som1_backups,
        "som2_backups": som2_backups,
        "config_path": config_path,
    }

    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


class TestInitSourceRepo:
    def test_creates_git_repo_with_two_commits(self, isolated_demo):
        _init_source_repo()
        source = isolated_demo["source"]

        assert (source / ".git").is_dir()
        assert (source / "test_app").is_file()

        # HEAD should contain v2 content
        head_content = (source / "test_app").read_text()
        assert "v2.0.0" in head_content
        assert "telemetry enabled" in head_content

        # There should be exactly 2 commits
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(source),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "2"

    def test_is_idempotent(self, isolated_demo):
        """Re-running leaves a working repo with v2 at HEAD — no git state leaks."""
        _init_source_repo()
        _init_source_repo()

        source = isolated_demo["source"]
        assert (source / ".git").is_dir()
        assert "v2.0.0" in (source / "test_app").read_text()

        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(source),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "2"


class TestInstallV1ToTarget:
    def test_pre_installs_v1_content_on_both_fleet_targets(self, isolated_demo):
        _init_source_repo()
        _install_v1_to_target()

        for key in ("som1_target", "som2_target"):
            resolved = isolated_demo[key] / DEMO_REMOTE_PATH.lstrip("/")
            assert resolved.exists()
            content = resolved.read_text()
            assert "v1.0.0" in content
            assert "telemetry enabled" not in content


class TestWriteDemoConfig:
    def test_writes_two_target_local_transport_config(self, isolated_demo):
        _write_demo_config()
        config_path = isolated_demo["config_path"]
        assert config_path.exists()

        data = yaml.safe_load(config_path.read_text())
        assert data["default_target"] == "som1"
        assert set(data["targets"].keys()) == {"som1", "som2"}
        assert data["targets"]["som1"]["transport"] == "local"
        assert data["targets"]["som1"]["target_dir"] == str(isolated_demo["som1_target"])
        assert data["targets"]["som2"]["target_dir"] == str(isolated_demo["som2_target"])
        assert "test_app" in data["apps"]
        assert data["apps"]["test_app"]["remote"] == DEMO_REMOTE_PATH

    def test_backs_up_existing_user_config(self, isolated_demo):
        isolated_demo["config_path"].parent.mkdir(parents=True, exist_ok=True)
        isolated_demo["config_path"].write_text(
            yaml.dump({"name": "my-satellite", "transport": "ssh"})
        )
        isolated_demo["root"].mkdir(parents=True, exist_ok=True)

        _write_demo_config()

        saved = isolated_demo["root"] / "saved-config.yaml"
        assert saved.exists()
        assert "my-satellite" in saved.read_text()


class TestSeedDemoHistory:
    def test_seeds_v1_record_per_fleet_target(self, isolated_demo):
        _init_source_repo()
        _install_v1_to_target()
        _write_demo_config()
        _seed_demo_history()

        history_db = isolated_demo["config_path"].parent / "history.db"
        assert history_db.exists()

        history = History(history_db)
        history.init_db()
        records = history.get_history("test_app")
        # One push record per fleet target.
        assert len(records) == 2
        assert {r.module for r in records} == {"som1", "som2"}
        for record in records:
            assert record.action == "push"
            assert record.success is True
            assert record.git_hash is not None
            assert record.git_hash.startswith("main@")
            # 8-char short hash, not full SHA
            assert len(record.file_hash) == 8


class TestDemoStart:
    def test_end_to_end_sets_up_everything(self, isolated_demo):
        demo_start()

        assert isolated_demo["source"].exists()
        assert (isolated_demo["source"] / ".git").is_dir()
        assert isolated_demo["config_path"].exists()

        for tkey, bkey in (
            ("som1_target", "som1_backups"),
            ("som2_target", "som2_backups"),
        ):
            assert isolated_demo[tkey].exists()
            assert isolated_demo[bkey].exists()
            # v1 pre-installed on each fleet target
            resolved = isolated_demo[tkey] / DEMO_REMOTE_PATH.lstrip("/")
            assert "v1.0.0" in resolved.read_text()

        # History seeded
        history_db = isolated_demo["config_path"].parent / "history.db"
        assert history_db.exists()

    def test_requires_git(self, isolated_demo):
        with patch("satdeploy.demo.shutil.which", return_value=None):
            with pytest.raises(SatDeployError, match="git is required"):
                demo_start()


class TestDemoStop:
    def test_removes_demo_files(self, isolated_demo):
        demo_start()
        assert isolated_demo["som1_target"].exists()
        assert isolated_demo["som2_target"].exists()

        demo_stop()

        assert not isolated_demo["som1_target"].exists()
        assert not isolated_demo["som2_target"].exists()
        assert not isolated_demo["som1_backups"].exists()
        assert not isolated_demo["som2_backups"].exists()

    def test_clean_removes_root(self, isolated_demo):
        demo_start()
        demo_stop(clean=True)
        assert not isolated_demo["root"].exists()

    def test_restores_saved_user_config(self, isolated_demo):
        # User has their own config
        isolated_demo["config_path"].parent.mkdir(parents=True, exist_ok=True)
        isolated_demo["config_path"].write_text(
            yaml.dump({"name": "my-satellite", "transport": "ssh"})
        )

        demo_start()  # backs up the user config, replaces with demo config
        demo_stop()  # should restore

        restored = yaml.safe_load(isolated_demo["config_path"].read_text())
        assert restored["name"] == "my-satellite"


class TestDemoStatus:
    def test_not_set_up(self, isolated_demo, capsys):
        demo_status()
        out = capsys.readouterr().out
        assert "not set up" in out.lower()

    def test_set_up(self, isolated_demo, capsys):
        demo_start()
        capsys.readouterr()  # drain start output
        demo_status()
        out = capsys.readouterr().out
        assert "set up" in out.lower()


class TestDemoCLI:
    def test_demo_help_lists_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(main, ["demo", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        # demo shell no longer exists
        assert "shell" not in result.output

    def test_bare_demo_invokes_start(self):
        runner = CliRunner()
        with patch("satdeploy.demo.demo_start") as mock_start:
            runner.invoke(main, ["demo"])
            mock_start.assert_called_once()

    def test_demo_start_invokes_module(self):
        runner = CliRunner()
        with patch("satdeploy.demo.demo_start") as mock_start:
            runner.invoke(main, ["demo", "start"])
            mock_start.assert_called_once()

    def test_demo_stop_invokes_module(self):
        runner = CliRunner()
        with patch("satdeploy.demo.demo_stop") as mock_stop:
            runner.invoke(main, ["demo", "stop"])
            mock_stop.assert_called_once_with(clean=False)

    def test_demo_stop_clean_invokes_module(self):
        runner = CliRunner()
        with patch("satdeploy.demo.demo_stop") as mock_stop:
            runner.invoke(main, ["demo", "stop", "--clean"])
            mock_stop.assert_called_once_with(clean=True)


class TestConfigDirEnvvar:
    def test_envvar_sets_config_dir(self, tmp_path):
        config_dir = tmp_path / ".satdeploy"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({
            "name": "test",
            "transport": "ssh",
            "host": "test-host",
            "user": "test-user",
            "apps": {},
        }))

        runner = CliRunner()
        result = runner.invoke(
            main, ["config"],
            env={"SATDEPLOY_CONFIG": str(config_file)},
        )
        assert result.exit_code == 0
        assert "test-host" in result.output

    def test_flag_overrides_envvar(self, tmp_path):
        flag_dir = tmp_path / "flag"
        flag_dir.mkdir()
        (flag_dir / "config.yaml").write_text(yaml.dump({
            "name": "flag-target",
            "transport": "ssh",
            "host": "flag-host",
            "user": "test",
            "apps": {},
        }))

        env_dir = tmp_path / "env"
        env_dir.mkdir()
        (env_dir / "config.yaml").write_text(yaml.dump({
            "name": "env-target",
            "transport": "ssh",
            "host": "env-host",
            "user": "test",
            "apps": {},
        }))

        runner = CliRunner()
        result = runner.invoke(
            main, ["config", "--config", str(flag_dir / "config.yaml")],
            env={"SATDEPLOY_CONFIG": str(env_dir / "config.yaml")},
        )
        assert result.exit_code == 0
        assert "flag-host" in result.output
