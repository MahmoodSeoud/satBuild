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
    result = template
    result = re.sub(r"\{\{\s*csp_addr\s*\}\}", str(module.csp_addr), result)
    result = re.sub(r"\{\{\s*netmask\s*\}\}", str(module.netmask), result)
    result = re.sub(r"\{\{\s*interface\s*\}\}", str(module.interface), result)
    result = re.sub(r"\{\{\s*baudrate\s*\}\}", str(module.baudrate), result)
    result = re.sub(r"\{\{\s*vmem_path\s*\}\}", module.vmem_path, result)
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
