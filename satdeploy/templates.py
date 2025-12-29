"""Service template rendering for satdeploy."""

import hashlib
import re

from satdeploy.config import ModuleConfig


def render_service_template(template: str, module: ModuleConfig) -> str:
    """Render a service template with module-specific values.

    Replaces placeholders like {{ csp_addr }} with actual values from
    the module configuration.

    Args:
        template: The service template string with placeholders.
        module: ModuleConfig containing values to substitute.

    Returns:
        The rendered template with all placeholders replaced.
    """
    replacements = {
        "csp_addr": str(module.csp_addr),
        "netmask": str(module.netmask),
        "interface": str(module.interface),
        "baudrate": str(module.baudrate),
        "vmem_path": module.vmem_path,
    }
    result = template
    for name, value in replacements.items():
        result = re.sub(rf"\{{\{{\s*{name}\s*\}}\}}", value, result)
    return result


def compute_service_hash(content: str) -> str:
    """Compute SHA256 hash of service file content.

    Used to detect if a service file needs updating on the remote.

    Args:
        content: The service file content string.

    Returns:
        First 8 characters of the hex digest.
    """
    return hashlib.sha256(content.encode()).hexdigest()[:8]
