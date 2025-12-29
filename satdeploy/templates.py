"""Service template rendering for satdeploy."""

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
    result = re.sub(r"\{\{\s*csp_addr\s*\}\}", str(module.csp_addr), template)
    return result
