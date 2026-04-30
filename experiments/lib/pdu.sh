#!/usr/bin/env bash
# PDU control via csh. The flatsat PDU is a Space Inventor PDU-P4 — a CSP
# node that exposes `power on` / `power off` commands through the SI APM
# (libcsh_si.so). No HTTP, no SNMP, no custom networking — same shell that
# runs `satdeploy push` runs `power off obc`.
#
# Prereqs:
#   - SI APM installed (libcsh_si.so reachable from `apm load`).
#   - init/flatsat.csh customized for your bench: real CSP transport,
#     real PDU hostname, real OBC channel.
#
# This file is sourced by the harness when LINK_KIND=can (or any flatsat
# scenario). On dev tier (zmq/kiss with no real PDU), the harness skips
# the PDU helpers — they're noops if PDU_INIT doesn't exist.

set -euo pipefail

CSH_BIN="${CSH_BIN:-/usr/local/bin/csh}"
PDU_INIT="${PDU_INIT:-/satdeploy/init/flatsat.csh}"
PDU_OBC_NAME="${PDU_OBC_NAME:-obc}"
PDU_PING_TIMEOUT_S="${PDU_PING_TIMEOUT_S:-60}"
PDU_LOG_DIR="${PDU_LOG_DIR:-/tmp/satdeploy-experiments}"

mkdir -p "$PDU_LOG_DIR"

pdu_available() {
    [ -f "$PDU_INIT" ]
}

# Run a single csh command in batch mode. The same script(1) trick the
# csh_driver uses — slash needs a TTY, and `script` provides one.
_pdu_csh_one_shot() {
    local cmd="$1"
    local logfile="${2:-${PDU_LOG_DIR}/pdu.log}"
    if ! pdu_available; then
        echo "[pdu] PDU_INIT not found at $PDU_INIT — skipping '$cmd'" >&2
        return 0
    fi
    script -qfec \
        "$CSH_BIN -i $PDU_INIT \"$cmd\"" \
        /dev/null </dev/null >>"$logfile" 2>&1
}

pdu_off() {
    echo "[pdu] $(date -u +%FT%TZ) power off $PDU_OBC_NAME" >&2
    _pdu_csh_one_shot "power off $PDU_OBC_NAME"
}

pdu_on() {
    echo "[pdu] $(date -u +%FT%TZ) power on  $PDU_OBC_NAME" >&2
    _pdu_csh_one_shot "power on $PDU_OBC_NAME"
}

# Block until the OBC responds to CSP ping. Returns 0 on alive, 124 on
# timeout. Used after `pdu_on` to wait for the OBC to boot far enough to
# accept satdeploy commands.
obc_wait_ready() {
    local timeout_s="${1:-$PDU_PING_TIMEOUT_S}"
    local deadline=$(( $(date +%s) + timeout_s ))
    local probe_log="${PDU_LOG_DIR}/obc-ping-$(date -u +%H%M%S).log"
    while [ "$(date +%s)" -lt "$deadline" ]; do
        : > "$probe_log"
        if _pdu_csh_one_shot "ping -t 1000 $PDU_OBC_NAME" "$probe_log"; then
            if grep -q "Reply" "$probe_log" 2>/dev/null; then
                echo "[pdu] $(date -u +%FT%TZ) obc ready" >&2
                return 0
            fi
        fi
        sleep 1
    done
    echo "[pdu] obc_wait_ready: timeout after ${timeout_s}s" >&2
    return 124
}

# Cycle the OBC: off, sleep, on, wait for ready. Used by F6 reboot tests.
pdu_cycle() {
    local off_seconds="${1:-10}"
    pdu_off
    sleep "$off_seconds"
    pdu_on
    obc_wait_ready "$PDU_PING_TIMEOUT_S"
}
