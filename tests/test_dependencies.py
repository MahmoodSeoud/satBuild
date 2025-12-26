"""Tests for dependency resolution module."""

import pytest

from satdeploy.dependencies import DependencyResolver


class TestBuildGraph:
    """Test dependency graph building."""

    def test_build_graph_with_no_dependencies(self):
        """Should handle apps with no dependencies."""
        apps = {
            "controller": {
                "service": "controller.service",
            },
            "csp_server": {
                "service": "csp_server.service",
            },
        }

        resolver = DependencyResolver(apps)

        assert resolver.get_dependents("controller") == []
        assert resolver.get_dependents("csp_server") == []

    def test_build_graph_with_simple_dependency(self):
        """Should track simple dependency relationships."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
            },
        }

        resolver = DependencyResolver(apps)

        # csp_server has controller as a dependent
        assert "controller" in resolver.get_dependents("csp_server")

    def test_build_graph_with_chain_dependency(self):
        """Should handle chain dependencies."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
                "depends_on": ["param_handler"],
            },
            "param_handler": {
                "service": "param_handler.service",
            },
        }

        resolver = DependencyResolver(apps)

        # param_handler has csp_server as direct dependent
        assert "csp_server" in resolver.get_dependents("param_handler")
        # csp_server has controller as direct dependent
        assert "controller" in resolver.get_dependents("csp_server")


class TestStopOrder:
    """Test stop order computation (dependents first)."""

    def test_stop_order_single_app_no_deps(self):
        """Stop order for single app with no deps should be just that app."""
        apps = {
            "controller": {
                "service": "controller.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_stop_order("controller")

        assert order == ["controller"]

    def test_stop_order_stops_dependents_first(self):
        """Stop order should stop dependents before the target."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_stop_order("csp_server")

        # controller depends on csp_server, so controller must stop first
        assert order.index("controller") < order.index("csp_server")

    def test_stop_order_chain(self):
        """Stop order should handle chain dependencies correctly."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
                "depends_on": ["param_handler"],
            },
            "param_handler": {
                "service": "param_handler.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_stop_order("param_handler")

        # Should stop: controller, then csp_server, then param_handler
        assert order.index("controller") < order.index("csp_server")
        assert order.index("csp_server") < order.index("param_handler")

    def test_stop_order_multiple_dependents(self):
        """Stop order should handle multiple dependents."""
        apps = {
            "app_a": {
                "service": "app_a.service",
                "depends_on": ["shared_lib"],
            },
            "app_b": {
                "service": "app_b.service",
                "depends_on": ["shared_lib"],
            },
            "shared_lib": {
                "service": "shared_lib.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_stop_order("shared_lib")

        # Both app_a and app_b must stop before shared_lib
        assert order.index("app_a") < order.index("shared_lib")
        assert order.index("app_b") < order.index("shared_lib")


class TestStartOrder:
    """Test start order computation (dependencies first)."""

    def test_start_order_single_app_no_deps(self):
        """Start order for single app with no deps should be just that app."""
        apps = {
            "controller": {
                "service": "controller.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_start_order("controller")

        assert order == ["controller"]

    def test_start_order_is_reverse_of_stop(self):
        """Start order should be reverse of stop order."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
            },
        }

        resolver = DependencyResolver(apps)
        stop_order = resolver.get_stop_order("csp_server")
        start_order = resolver.get_start_order("csp_server")

        assert start_order == list(reversed(stop_order))

    def test_start_order_chain(self):
        """Start order should handle chain dependencies correctly."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
                "depends_on": ["param_handler"],
            },
            "param_handler": {
                "service": "param_handler.service",
            },
        }

        resolver = DependencyResolver(apps)
        order = resolver.get_start_order("param_handler")

        # Should start: param_handler, then csp_server, then controller
        assert order.index("param_handler") < order.index("csp_server")
        assert order.index("csp_server") < order.index("controller")


class TestRestartList:
    """Test restart list handling for libraries."""

    def test_get_restart_apps_returns_list(self):
        """Should return the restart list for an app."""
        apps = {
            "libparam": {
                "remote": "/usr/lib/libparam.so",
                "service": None,
                "restart": ["csp_server", "controller"],
            },
            "csp_server": {
                "service": "csp_server.service",
            },
            "controller": {
                "service": "controller.service",
            },
        }

        resolver = DependencyResolver(apps)
        restart_apps = resolver.get_restart_apps("libparam")

        assert "csp_server" in restart_apps
        assert "controller" in restart_apps

    def test_get_restart_apps_empty_when_no_restart_field(self):
        """Should return empty list when no restart field."""
        apps = {
            "controller": {
                "service": "controller.service",
            },
        }

        resolver = DependencyResolver(apps)
        restart_apps = resolver.get_restart_apps("controller")

        assert restart_apps == []


class TestCyclicDependencyDetection:
    """Test detection of cyclic dependencies."""

    def test_detects_direct_cycle(self):
        """Should detect direct cyclic dependency."""
        apps = {
            "app_a": {
                "service": "app_a.service",
                "depends_on": ["app_b"],
            },
            "app_b": {
                "service": "app_b.service",
                "depends_on": ["app_a"],
            },
        }

        resolver = DependencyResolver(apps)

        assert resolver.has_cycle() is True

    def test_detects_indirect_cycle(self):
        """Should detect indirect cyclic dependency."""
        apps = {
            "app_a": {
                "service": "app_a.service",
                "depends_on": ["app_b"],
            },
            "app_b": {
                "service": "app_b.service",
                "depends_on": ["app_c"],
            },
            "app_c": {
                "service": "app_c.service",
                "depends_on": ["app_a"],
            },
        }

        resolver = DependencyResolver(apps)

        assert resolver.has_cycle() is True

    def test_no_false_positive_for_valid_graph(self):
        """Should not detect cycle in valid dependency graph."""
        apps = {
            "controller": {
                "service": "controller.service",
                "depends_on": ["csp_server"],
            },
            "csp_server": {
                "service": "csp_server.service",
                "depends_on": ["param_handler"],
            },
            "param_handler": {
                "service": "param_handler.service",
            },
        }

        resolver = DependencyResolver(apps)

        assert resolver.has_cycle() is False
