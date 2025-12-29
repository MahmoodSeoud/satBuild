"""Tests for service template rendering."""

import pytest

from satdeploy.config import ModuleConfig
from satdeploy.templates import compute_service_hash, render_service_template


class TestRenderServiceTemplate:
    """Test service template rendering."""

    def test_replaces_csp_addr_placeholder(self):
        """Should replace {{ csp_addr }} with module's csp_addr value."""
        module = ModuleConfig(
            name="som1",
            host="192.168.1.10",
            user="root",
            csp_addr=5421,
            netmask=8,
            interface=0,
            baudrate=100000,
            vmem_path="/home/root/a53vmem",
        )
        template = "ExecStart=/usr/bin/app {{ csp_addr }}"

        result = render_service_template(template, module)

        assert result == "ExecStart=/usr/bin/app 5421"

    def test_replaces_all_placeholders(self):
        """Should replace all supported placeholders."""
        module = ModuleConfig(
            name="som1",
            host="192.168.1.10",
            user="root",
            csp_addr=5421,
            netmask=8,
            interface=0,
            baudrate=100000,
            vmem_path="/home/root/a53vmem",
        )
        template = (
            "ExecStart=/usr/bin/app "
            "{{ csp_addr }} {{ netmask }} {{ interface }} {{ baudrate }} "
            "-v {{ vmem_path }}"
        )

        result = render_service_template(template, module)

        assert result == (
            "ExecStart=/usr/bin/app "
            "5421 8 0 100000 "
            "-v /home/root/a53vmem"
        )

    def test_handles_flexible_whitespace_in_placeholders(self):
        """Should handle placeholders with varying whitespace."""
        module = ModuleConfig(
            name="som1",
            host="192.168.1.10",
            user="root",
            csp_addr=5421,
            netmask=8,
            interface=0,
            baudrate=100000,
            vmem_path="/home/root/a53vmem",
        )
        template = "{{csp_addr}} {{  netmask  }} {{ interface}}"

        result = render_service_template(template, module)

        assert result == "5421 8 0"

    def test_returns_unchanged_template_with_no_placeholders(self):
        """Should return template unchanged when no placeholders exist."""
        module = ModuleConfig(
            name="som1",
            host="192.168.1.10",
            user="root",
            csp_addr=5421,
            netmask=8,
            interface=0,
            baudrate=100000,
            vmem_path="/home/root/a53vmem",
        )
        template = "[Unit]\nDescription=My Service\n[Service]\nExecStart=/bin/true"

        result = render_service_template(template, module)

        assert result == template


class TestComputeServiceHash:
    """Test service content hashing."""

    def test_returns_8_char_hex_string(self):
        """Should return 8-character hex hash for consistency with binary hashes."""
        content = "[Unit]\nDescription=Test\n[Service]\nExecStart=/bin/app"

        result = compute_service_hash(content)

        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)
