# Functions and aliases for the satdeploy dev container.
#
# This file is volume-mounted at /satdeploy/scripts/dev-shell.sh inside the
# container, so editing it on the host updates the helpers on the next shell
# start — no docker rebuild needed.
#
# Sourced from /etc/profile.d/satdeploy.sh (login shells) and
# /etc/bash.bashrc (interactive shells).

# Don't load twice
[ "${_SATDEPLOY_SHELL_LOADED:-0}" = 1 ] && return
_SATDEPLOY_SHELL_LOADED=1

export PS1='\[\e[1;32m\]satdeploy-dev\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]$ '
export EDITOR=vim
alias ll='ls -lah --color=auto'
alias g='git'

# Path where csh dlopens APM .so files from. CSH searches:
#   $HOME/.local/lib/csh
#   /opt/csh/builddir
#   /usr/lib/csh
# Use the first one — it doesn't require root and is per-user.
SATDEPLOY_APM_DIR="${SATDEPLOY_APM_DIR:-/root/.local/lib/csh}"

agent() { ./satdeploy-agent/build-native/satdeploy-agent "$@"; }

build-agent() {
    meson setup satdeploy-agent/build-native satdeploy-agent --reconfigure \
        && ninja -C satdeploy-agent/build-native
}

# Builds the APM and installs the .so to where csh expects it. Auto-install
# is the default because forgetting to copy and then hitting "No APMs found
# in ..." is the most common dev-flow papercut.
build-apm() {
    meson setup satdeploy-apm/build satdeploy-apm --reconfigure \
        && ninja -C satdeploy-apm/build \
        && mkdir -p "$SATDEPLOY_APM_DIR" \
        && cp satdeploy-apm/build/libcsh_satdeploy_apm.so "$SATDEPLOY_APM_DIR/" \
        && echo "installed: $SATDEPLOY_APM_DIR/libcsh_satdeploy_apm.so"
}

build-all() { build-agent && build-apm; }

# Backward-compat: install-apm is now identical to build-apm.
install-apm() { build-apm; }

# `csh` is intentionally NOT overridden — it stays the plain spaceinventor
# binary so the operator can launch with any init file:
#   csh                          # bare shell, no init
#   csh -i init/zmq.csh          # ZMQ ground transport
#   csh -i init/can.csh          # (future) CAN transport
# The auto-launched pane on container entry uses the ZMQ init script.
