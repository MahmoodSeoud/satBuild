# sat-agent-status Feature Notes

## Overview
Implementing the `status` command for sat-agent, which returns the running/stopped state of all configured services.

## Key Decisions
- Config path is configurable via `SAT_AGENT_CONFIG` env var, defaults to `/opt/sat-agent/config.yaml`
- All output is JSON to stdout
- Uses systemctl to check service status

## Dependencies
- Python 3.8+
- PyYAML
- systemd (on target flatsat)

## Test Strategy
- Mock subprocess calls to systemctl for unit testing
- Config path override allows local testing without flatsat

## Status Command Spec
Input: `sat-agent status`
Output:
```json
{
  "status": "ok",
  "services": {
    "controller": "running",
    "csp_server": "running",
    "param_handler": "stopped"
  }
}
```

On error:
```json
{
  "status": "failed",
  "reason": "error message"
}
```
