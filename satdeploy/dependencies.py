"""Dependency resolution for satdeploy."""

from collections import defaultdict
from typing import Optional


class DependencyResolver:
    """Resolves service dependencies for stop/start ordering."""

    def __init__(self, apps: dict):
        """Initialize with app configuration.

        Args:
            apps: Dictionary of app configurations from config.yaml.
        """
        self._apps = apps
        self._dependents: dict[str, list[str]] = defaultdict(list)
        self._build_graph()

    def _build_graph(self) -> None:
        """Build the dependency graph from app configurations."""
        for app_name, app_config in self._apps.items():
            depends_on = app_config.get("depends_on", [])
            for dep in depends_on:
                self._dependents[dep].append(app_name)

    def get_dependents(self, app_name: str) -> list[str]:
        """Get apps that depend on the given app.

        Args:
            app_name: The app to find dependents for.

        Returns:
            List of app names that depend on this app.
        """
        return self._dependents.get(app_name, [])

    def get_restart_apps(self, app_name: str) -> list[str]:
        """Get apps to restart when this app changes.

        Used for libraries with explicit restart lists.

        Args:
            app_name: The app that changed.

        Returns:
            List of app names to restart.
        """
        app_config = self._apps.get(app_name, {})
        return app_config.get("restart", [])

    def _get_all_dependents(self, app_name: str, visited: Optional[set] = None) -> list[str]:
        """Recursively get all apps that depend on the given app.

        Args:
            app_name: The app to find dependents for.
            visited: Set of already visited apps (for cycle detection).

        Returns:
            List of all dependent apps in topological order (leaves first).
        """
        if visited is None:
            visited = set()

        if app_name in visited:
            return []

        visited.add(app_name)

        result = []
        for dependent in self._dependents.get(app_name, []):
            result.extend(self._get_all_dependents(dependent, visited))
            if dependent not in result:
                result.append(dependent)

        return result

    def get_stop_order(self, app_name: str) -> list[str]:
        """Get the order to stop services for deploying this app.

        Dependents must be stopped first (top-down).

        Args:
            app_name: The app being deployed.

        Returns:
            List of app names in stop order.
        """
        all_dependents = self._get_all_dependents(app_name)
        return all_dependents + [app_name]

    def get_start_order(self, app_name: str) -> list[str]:
        """Get the order to start services after deploying this app.

        The deployed app starts first, then its dependents (bottom-up).

        Args:
            app_name: The app being deployed.

        Returns:
            List of app names in start order.
        """
        return list(reversed(self.get_stop_order(app_name)))

    def has_cycle(self) -> bool:
        """Check if the dependency graph has cycles.

        Returns:
            True if there's a cyclic dependency, False otherwise.
        """
        # Build reverse graph (dependencies, not dependents)
        dependencies: dict[str, list[str]] = defaultdict(list)
        for app_name, app_config in self._apps.items():
            depends_on = app_config.get("depends_on", [])
            dependencies[app_name] = list(depends_on)

        # DFS cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {app: WHITE for app in self._apps}

        def dfs(app: str) -> bool:
            color[app] = GRAY
            for dep in dependencies.get(app, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE and dfs(dep):
                    return True
            color[app] = BLACK
            return False

        for app in self._apps:
            if color[app] == WHITE:
                if dfs(app):
                    return True

        return False
