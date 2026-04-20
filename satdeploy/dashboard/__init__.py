"""Phase 0 satdeploy dashboard.

FastAPI + HTMX + Jinja2 surface showing deployment state, live-activity
ticker, and the R6 permanent-record iteration pages. Always local-first:
bound to a LAN interface by default, ``127.0.0.1`` when the user passes
``--bind 127.0.0.1``, full-net only when ``--bind 0.0.0.0`` is explicitly
requested. There is NO auth layer beyond the shared-secret header on
state-changing endpoints. Do not expose this to the internet.

Entrypoints:

- ``satdeploy dashboard`` CLI — launches uvicorn out-of-process (per
  eng-review landmine #10, in-process ``uvicorn.run()`` would freeze the
  CLI and block ``/api/rollback`` from working when invoked from a
  ``satdeploy watch`` loop).
- ``satdeploy.dashboard.app:app`` — ASGI callable for uvicorn. Requires
  ``SATDEPLOY_DASHBOARD_DB`` and ``SATDEPLOY_DASHBOARD_SECRET`` env vars;
  optional ``SATDEPLOY_DASHBOARD_CONFIG`` for app-name rendering.
- ``satdeploy.dashboard.app.create_app`` — pure factory, called by both
  the env-driven entrypoint and by tests (where env vars are awkward).
"""
