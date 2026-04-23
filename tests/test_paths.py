"""Tests for satdeploy.paths.expand_path."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from satdeploy.paths import expand_path


def test_expand_home_tilde(monkeypatch):
    monkeypatch.setenv("HOME", "/users/bench")
    assert expand_path("~/builds/controller") == "/users/bench/builds/controller"


def test_expand_home_env_var(monkeypatch):
    """The bug that triggered this module: literal $HOME in YAML."""
    monkeypatch.setenv("HOME", "/users/bench")
    assert expand_path("$HOME/builds/controller") == "/users/bench/builds/controller"


def test_expand_arbitrary_env_var(monkeypatch):
    monkeypatch.setenv("MYBUILD", "/opt/nightly")
    assert expand_path("$MYBUILD/libparam.so") == "/opt/nightly/libparam.so"


def test_expand_braced_env_var(monkeypatch):
    monkeypatch.setenv("SDK", "/opt/yocto")
    assert expand_path("${SDK}/sysroots/arm") == "/opt/yocto/sysroots/arm"


def test_expand_undefined_var_stays_literal(monkeypatch):
    """Match shell ``${VAR-}`` behavior — we don't want surprise-fail on
    a typo. Downstream 'file not found' error names the unresolved path."""
    monkeypatch.delenv("THIS_IS_UNSET", raising=False)
    assert expand_path("$THIS_IS_UNSET/x") == "$THIS_IS_UNSET/x"


def test_expand_absolute_path_unchanged():
    assert expand_path("/opt/app/bin/controller") == "/opt/app/bin/controller"


def test_expand_relative_path_unchanged():
    assert expand_path("./build/controller") == "./build/controller"


def test_expand_empty_string():
    assert expand_path("") == ""


def test_expand_none():
    assert expand_path(None) == ""


def test_expand_path_object(monkeypatch):
    monkeypatch.setenv("HOME", "/users/bench")
    result = expand_path(Path("~/builds/controller"))
    assert result == "/users/bench/builds/controller"


def test_expand_both_tilde_and_var(monkeypatch):
    """Combined: $VAR inside a ~-prefixed path. Env vars expand first,
    then ~, so this works as long as the var doesn't point at ~."""
    monkeypatch.setenv("SUBDIR", "nightly")
    monkeypatch.setenv("HOME", "/users/bench")
    assert expand_path("~/builds/$SUBDIR/controller") == "/users/bench/builds/nightly/controller"
