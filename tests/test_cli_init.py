"""Tests for the satdeploy init command."""

import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from satdeploy.cli import main
from satdeploy.output import SYMBOLS


# Prompt order after DX review 2026-04-23 decision #2:
#   1. Target name (default: "default")
#   2. Target host
#   3. SSH user (default: "root")
#   4. App name (default: "controller")
#   5. Local binary path (required, no default)
#   6. Remote path (default: /opt/bin/{app_name})
#   7. systemd service name (default: blank)
#
# Tests feed a canonical happy-path string "\n192.168.1.50\nroot\n\n" +
# "/tmp/build/controller\n\n\n" and override individual answers where
# they need to assert on a specific value.

_HAPPY_PATH_INPUT = (
    "\n"                       # target name: default "default"
    "192.168.1.50\n"           # host
    "root\n"                   # ssh user
    "\n"                       # app name: default "controller"
    "/tmp/build/controller\n"  # local path
    "\n"                       # remote path: default /opt/bin/controller
    "\n"                       # service name: default blank
)


class TestInitCommand:
    """Test the init command."""

    def test_init_command_exists(self):
        """The init command should exist."""
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "Interactive setup" in result.output or "config" in result.output.lower()

    def test_init_creates_config_file(self, tmp_path):
        """Init should create a config.yaml file."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        assert result.exit_code == 0
        assert (config_dir / "config.yaml").exists()

    def test_init_prompts_for_host(self, tmp_path):
        """Init should prompt for target host."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        assert "host" in result.output.lower() or "Target host" in result.output

    def test_init_prompts_for_user(self, tmp_path):
        """Init should prompt for target user."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        assert "user" in result.output.lower()

    def test_init_saves_user_input(self, tmp_path):
        """Init should save the user input to config file."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            # name, host, user, then default app prompts
            input="som1\n10.0.0.100\nadmin\n\n/tmp/build/controller\n\n\n",
        )

        config_file = config_dir / "config.yaml"
        config = yaml.safe_load(config_file.read_text())

        assert config["name"] == "som1"
        assert config["host"] == "10.0.0.100"
        assert config["user"] == "admin"
        assert config["transport"] == "ssh"

    def test_init_sets_defaults(self, tmp_path):
        """Init should set default values for backup_dir and max_backups."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        config_file = config_dir / "config.yaml"
        config = yaml.safe_load(config_file.read_text())

        assert config["backup_dir"] == "/opt/satdeploy/backups"
        assert config["max_backups"] == 10
        # Default app name after DX review #2.
        assert "controller" in config["apps"]

    def test_init_prompts_for_app_configuration(self, tmp_path):
        """DX review 2026-04-23 decision #2: init asks for app name,
        local binary path, remote path, and optional service so the
        written config is runnable without a manual YAML edit."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        assert result.exit_code == 0
        assert "App name" in result.output
        assert "Local binary path" in result.output
        assert "Remote path on target" in result.output
        assert "systemd service name" in result.output

    def test_init_writes_runnable_app_config(self, tmp_path):
        """Generated YAML has real paths, not placeholder strings."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=(
                "\n192.168.1.50\nroot\n"
                "dipp\n"                        # app name
                "./build/dipp\n"                # local
                "/opt/disco/bin/dipp\n"         # remote (override default)
                "disco.service\n"               # service
            ),
        )

        assert result.exit_code == 0, result.output
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        assert list(config["apps"].keys()) == ["dipp"]
        dipp = config["apps"]["dipp"]
        assert dipp["local"] == "./build/dipp"
        assert dipp["remote"] == "/opt/disco/bin/dipp"
        assert dipp["service"] == "disco.service"
        # No placeholder text survives into the written config.
        yaml_text = (config_dir / "config.yaml").read_text()
        assert "/path/to/build/" not in yaml_text
        assert "example_app" not in yaml_text

    def test_init_remote_path_defaults_to_opt_bin_app(self, tmp_path):
        """Default remote path is /opt/bin/{app_name} so accepting the
        default twice (app name + remote) still produces runnable YAML."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        assert config["apps"]["controller"]["remote"] == "/opt/bin/controller"

    def test_init_blank_service_name_omits_service_key(self, tmp_path):
        """Libraries / .so / assets have no systemd unit. A blank service
        prompt should drop the key entirely rather than write an empty
        string that breaks downstream service handling."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,  # happy path leaves service blank
        )

        app = yaml.safe_load((config_dir / "config.yaml").read_text())["apps"]["controller"]
        assert "service" not in app

    def test_init_warns_when_local_path_missing(self, tmp_path):
        """If the local path the user typed doesn't exist yet, init
        prints a gentle note — not an error. Pilots bringing their own
        build tree may type the path before first compile."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=(
                "\n192.168.1.50\nroot\n"
                "controller\n"
                "/does/not/exist/yet\n"
                "\n\n"
            ),
        )

        assert result.exit_code == 0, result.output
        assert "/does/not/exist/yet" in result.output
        assert "doesn't exist yet" in result.output or "Build it" in result.output

    def test_init_does_not_prompt_for_csp(self, tmp_path):
        """Post-cd38042 the Python CLI doesn't support transport=csp.
        Init must not offer CSP — it would produce a config that fails
        on push/iterate at cli.py:75. CSP teams use satdeploy-apm
        inside CSH instead."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        # No prompt should ask for transport or ZMQ endpoint.
        assert "Transport type" not in result.output
        assert "ZMQ endpoint" not in result.output
        # The intro mentions CSP only to point users at the APM.
        assert "satdeploy-apm" in result.output

    def test_init_warns_if_config_exists(self, tmp_path):
        """Init should warn if config already exists."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("host: old\n")

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input="n\n",  # Don't overwrite
        )

        # Should ask about overwriting
        assert "exist" in result.output.lower() or "overwrite" in result.output.lower()

    def test_init_can_overwrite_existing_config(self, tmp_path):
        """Init should overwrite config if user confirms."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("name: old\nhost: old\nuser: old\n")

        runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input="y\n" + _HAPPY_PATH_INPUT,  # overwrite, then happy path
        )

        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        assert config["host"] == "192.168.1.50"


class TestInitPolishedOutput:
    """Tests for polished CLI output formatting."""

    def test_init_success_shows_checkmark(self, tmp_path):
        """Init should show checkmark when config is saved."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
            color=True,
        )

        assert result.exit_code == 0
        assert SYMBOLS["check"] in result.output

    def test_init_prints_next_steps_leading_with_doctor(self, tmp_path):
        """DX review 2026-04-23: init's next-steps should lead with
        `satdeploy doctor --for iterate` (catches setup issues before
        iterate fails mid-flight), then iterate, then the SATDEPLOY_SDK
        hint as optional."""
        runner = CliRunner()
        config_dir = tmp_path / ".satdeploy"

        result = runner.invoke(
            main,
            ["init", "--config", str(config_dir / "config.yaml")],
            input=_HAPPY_PATH_INPUT,
        )

        assert result.exit_code == 0
        assert "Next steps" in result.output
        # Doctor comes before iterate in the output.
        doctor_idx = result.output.find("satdeploy doctor")
        iterate_idx = result.output.find("satdeploy iterate")
        assert doctor_idx != -1, "Next steps should reference satdeploy doctor"
        assert iterate_idx != -1, "Next steps should reference satdeploy iterate"
        assert doctor_idx < iterate_idx, (
            "Doctor should precede iterate in Next steps — catches setup "
            "issues before iterate fails mid-flight."
        )
        assert "SATDEPLOY_SDK" in result.output
