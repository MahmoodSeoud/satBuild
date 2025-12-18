#!/usr/bin/env python3
"""sat-agent: Deployment agent for flatsat.

Runs on the flatsat to handle deployment commands from the CLI.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = '/opt/sat-agent/config.yaml'


def load_config(config_path=None):
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses SAT_AGENT_CONFIG
                     env var or falls back to DEFAULT_CONFIG_PATH.

    Returns:
        dict: Configuration dictionary.

    Raises:
        FileNotFoundError: If config file doesn't exist.
    """
    if config_path is None:
        config_path = os.environ.get('SAT_AGENT_CONFIG', DEFAULT_CONFIG_PATH)

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        return yaml.safe_load(f)


def check_service_status(service_name):
    """Check if a systemd service is running.

    Args:
        service_name: Name of the systemd service (e.g., 'controller.service').

    Returns:
        str: 'running' if active, 'stopped' otherwise.
    """
    result = subprocess.run(
        ['systemctl', 'is-active', service_name],
        capture_output=True,
        text=True
    )
    return 'running' if result.returncode == 0 else 'stopped'


def get_status(config):
    """Get status of all configured services.

    Args:
        config: Configuration dictionary with 'services' key.

    Returns:
        dict: Status response with 'status' and 'services' keys.
    """
    services = config.get('services', {})
    service_statuses = {}

    for name, service_config in services.items():
        systemd_name = service_config.get('systemd', f'{name}.service')
        service_statuses[name] = check_service_status(systemd_name)

    return {
        'status': 'ok',
        'services': service_statuses
    }


def main():
    """Main entry point for sat-agent CLI."""
    if len(sys.argv) < 2:
        print(json.dumps({'status': 'failed', 'reason': 'No command provided'}))
        sys.exit(1)

    command = sys.argv[1]

    try:
        config = load_config()

        if command == 'status':
            result = get_status(config)
            print(json.dumps(result))
        else:
            print(json.dumps({'status': 'failed', 'reason': f'Unknown command: {command}'}))
            sys.exit(1)

    except FileNotFoundError as e:
        print(json.dumps({'status': 'failed', 'reason': str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({'status': 'failed', 'reason': str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
