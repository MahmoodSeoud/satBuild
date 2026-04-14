"""satdeploy - Deploy files to embedded Linux targets."""

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("satdeploy")
except Exception:  # pragma: no cover — installed-from-source fallback
    __version__ = "0.0.0+unknown"
