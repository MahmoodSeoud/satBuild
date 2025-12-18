# sat-deploy

Fast binary deployment tool for embedded Linux flatsat (satellite engineering model).

## Components

- **sat-agent**: Runs on flatsat, handles deployment commands
- **sat**: CLI tool for developer laptop

## Requirements

- Python 3.8+
- PyYAML (`pip install pyyaml`)

## Development

### Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_sat_agent.py -v
```

### Configuration

The sat-agent config path can be overridden for testing:

```bash
export SAT_AGENT_CONFIG=/path/to/test/config.yaml
```

Default production path: `/opt/sat-agent/config.yaml`

## Usage

See `plan.md` for full specification.
