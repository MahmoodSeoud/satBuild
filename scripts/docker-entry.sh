#!/usr/bin/env bash
# Container entrypoint. Pre-builds the agent + APM, starts zmqproxy in the
# background, then opens tmux with a vertical 2-pane layout:
#   left:  csh -i /satdeploy/init/zmq.csh   (ground station)
#   right: agent -i ZMQ -p localhost        (target running locally)
#
# Re-entering the container (docker exec / restart) reattaches to the
# existing session instead of rebuilding the layout.
set -euo pipefail

# Pull in the shared helpers (build-all, agent, etc.) — same path the
# /etc/profile.d hook uses, but we may run before that fires.
if [ -r /satdeploy/scripts/dev-shell.sh ]; then
    # shellcheck source=/satdeploy/scripts/dev-shell.sh
    . /satdeploy/scripts/dev-shell.sh
fi

SESSION="satdeploy"

# If a session already exists, just reattach — preserves whatever state
# (running agent, csh history, scrollback) the previous run left behind.
if tmux has-session -t "$SESSION" 2>/dev/null; then
    exec tmux attach -t "$SESSION"
fi

cd /satdeploy

echo ">>> Pre-building agent + APM (one-time per container start)"
build-all

echo ">>> Generating test apps (hello / controller / telemetry / payload)"
scripts/make-test-apps.sh

# Drop in the test config if the user hasn't created one yet. Doesn't
# clobber an existing config — the user can rerun `satdeploy init` to
# replace it interactively.
if [ ! -f /root/.satdeploy/config.yaml ]; then
    echo ">>> Installing /root/.satdeploy/config.yaml from init/test-config.yaml"
    mkdir -p /root/.satdeploy
    cp /satdeploy/init/test-config.yaml /root/.satdeploy/config.yaml
fi

# Make sure the agent's deploy targets directory exists. Agent will write
# files there when push commands land.
mkdir -p /tmp/satdeploy-target /tmp/satdeploy-backups

# Start zmqproxy in the background. Logs land in /tmp so they don't
# clutter the panes; tail them with: tail -f /tmp/zmqproxy.log
echo ">>> Starting zmqproxy in background"
nohup zmqproxy >/tmp/zmqproxy.log 2>&1 &
sleep 0.5  # let it bind 6000/7000 before clients try to connect

# Build the layout.
#   - new-session -d        : create detached, don't attach yet
#   - split-window -h       : add a right pane (vertical pane separator)
#   - send-keys              : queue commands in each pane's shell
#   - select-pane -t :.0     : leave focus on the left pane (csh) on attach
echo ">>> Opening tmux session: $SESSION"
tmux new-session -d -s "$SESSION" -c /satdeploy
tmux split-window -h -t "$SESSION":0 -c /satdeploy
tmux send-keys -t "$SESSION":0.0 'csh -i /satdeploy/init/zmq.csh' Enter
tmux send-keys -t "$SESSION":0.1 'agent -i ZMQ -p localhost -a 5425' Enter
tmux select-pane -t "$SESSION":0.0

exec tmux attach -t "$SESSION"
