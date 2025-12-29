"""Fleet-level operations across modules."""

from satdeploy.config import Config
from satdeploy.deployer import Deployer
from satdeploy.history import History


class FleetManager:
    """Manages fleet-level operations across multiple modules."""

    def __init__(self, config: Config, history: History, deployer: Deployer):
        self.config = config
        self.history = history
        self.deployer = deployer
