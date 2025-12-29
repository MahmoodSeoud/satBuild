"""Tests for the fleet module."""

from unittest.mock import Mock

import pytest

from satdeploy.fleet import FleetManager


class TestFleetManagerInit:
    """Tests for FleetManager initialization."""

    def test_fleet_manager_accepts_dependencies(self):
        """FleetManager should accept config, history, and deployer."""
        config = Mock()
        history = Mock()
        deployer = Mock()

        fleet = FleetManager(config=config, history=history, deployer=deployer)

        assert fleet.config is config
        assert fleet.history is history
        assert fleet.deployer is deployer
