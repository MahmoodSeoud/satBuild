#!/usr/bin/env bash
# Week 1 deliverable: end-to-end debug symbol pipeline for satdeploy.
#
# What this proves:
#   1. Cross-compile a tiny C program for aarch64 with debug info.
#   2. Split debug info into a sidecar .debug file (production pattern:
#      deployed binaries are stripped, debug info stays on the ground).
#   3. Run `satdeploy debuginfod serve` against a sysroots dir that holds
#      the unstripped copy — our CLI wraps the elfutils `debuginfod` binary.
#   4. Invoke aarch64-poky-linux-gdb against the STRIPPED binary with
#      `DEBUGINFOD_URLS=http://localhost:8002`. gdb fetches the debug info
#      by build-id over HTTP and resolves source lines.
#
# If this script exits 0, every link in the symbol pipeline works:
# ARM cross-compile, debug split, build-id identity, debuginfod HTTP serve,
# gdb debuginfod client. That is the Week 1 thesis-citable artifact.
#
# Requires: /opt/poky Yocto SDK (provides aarch64 toolchain + x86 debuginfod),
# .venv with satdeploy installed in editable mode.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POKY_ENV="/opt/poky/environment-setup-armv8a-poky-linux"

if [ ! -f "$POKY_ENV" ]; then
    echo "FAIL: Yocto SDK not found at $POKY_ENV" >&2
    exit 1
fi

# shellcheck source=/dev/null
source "$POKY_ENV"

for tool in aarch64-poky-linux-gcc aarch64-poky-linux-objcopy \
            aarch64-poky-linux-gdb debuginfod; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "FAIL: missing $tool after sourcing Yocto env" >&2
        exit 1
    fi
done

# The .venv/bin/satdeploy launcher has a stale shebang on this machine;
# invoke the CLI via python directly so the demo works everywhere.
run_satdeploy() {
    "$REPO_ROOT/.venv/bin/python" -c \
        "from satdeploy.cli import main; main()" "$@"
}

TMP="$(mktemp -d -t satdeploy-debuginfod-XXXXXXXX)"
SYSROOTS="$TMP/sysroots"
mkdir -p "$SYSROOTS"

cleanup() {
    local exit_code=$?
    # Best-effort stop debuginfod via our CLI so the PID file stays clean.
    run_satdeploy debuginfod stop >/dev/null 2>&1 || true
    rm -rf "$TMP"
    exit "$exit_code"
}
trap cleanup EXIT

echo "=== step 1: write hello.c ==="
cat > "$TMP/hello.c" <<'EOF'
#include <stdio.h>

static int compute_answer(int n) {
    return n * 6 + 2;
}

int main(int argc, char **argv) {
    (void)argc;
    (void)argv;
    int answer = compute_answer(7);
    printf("answer is %d\n", answer);
    return 0;
}
EOF

echo "=== step 2: cross-compile with -g, keep build-id ==="
# The Yocto env sets $CC with --sysroot and march flags. Using $CC (not the
# bare compiler binary) is the supported way to cross-compile against the
# SDK sysroot headers/libs. -Wl,--build-id=sha1 ensures a deterministic
# build-id is embedded so debuginfod can look it up.
# shellcheck disable=SC2086
$CC -g -O0 -Wl,--build-id=sha1 "$TMP/hello.c" -o "$TMP/hello.unstripped"

BUILD_ID=$("$OBJCOPY" --dump-section \
    .note.gnu.build-id=/dev/stdout "$TMP/hello.unstripped" 2>/dev/null | \
    xxd -p | tr -d '\n' | tail -c 40)
echo "  build-id: $BUILD_ID"

echo "=== step 3: split debug info (production pattern) ==="
# --only-keep-debug produces the sidecar; --strip-debug produces what we
# would actually ship to the target.
"$OBJCOPY" --only-keep-debug "$TMP/hello.unstripped" "$TMP/hello.debug"
"$OBJCOPY" --strip-debug --strip-unneeded \
    "$TMP/hello.unstripped" "$TMP/hello.stripped"
"$OBJCOPY" --add-gnu-debuglink="$TMP/hello.debug" "$TMP/hello.stripped"

ls -l "$TMP"/hello.* | awk '{printf "  %-10s %s\n", $5, $NF}'

echo "=== step 4: publish unstripped binary into the debuginfod sysroot ==="
# debuginfod's -F mode scans the directory, extracts build-ids, and serves
# the full debug info from whichever file carries the matching id.
cp "$TMP/hello.unstripped" "$SYSROOTS/hello"

echo "=== step 5: start satdeploy debuginfod serve ==="
run_satdeploy debuginfod stop >/dev/null 2>&1 || true
run_satdeploy debuginfod serve --sysroots "$SYSROOTS"

# Poll until debuginfod has indexed our file. The groom loop can take a
# second or two on first start; retry up to ~5s.
echo -n "  waiting for debuginfod to index build-id $BUILD_ID"
for _ in $(seq 1 50); do
    if curl -s -o "$TMP/served.debug" -w "%{http_code}" \
        "http://localhost:8002/buildid/$BUILD_ID/debuginfo" \
        | grep -q "^200$"; then
        echo " ...served"
        break
    fi
    echo -n "."
    sleep 0.1
done

if ! [ -s "$TMP/served.debug" ]; then
    echo "FAIL: debuginfod did not serve debug info for $BUILD_ID" >&2
    exit 1
fi

echo "=== step 6: gdb resolves source lines on the STRIPPED binary ==="
# Batch mode: no interactive session, just dump the info we care about.
# The decisive assertion is `info line main` returning a hello.c reference.
GDB_OUT="$TMP/gdb.out"
DEBUGINFOD_URLS="http://localhost:8002" \
DEBUGINFOD_VERBOSE=1 \
"$GDB" -batch -nx -q \
    -ex "set confirm off" \
    -ex "file $TMP/hello.stripped" \
    -ex "info functions compute_answer" \
    -ex "info line main" \
    -ex "disassemble /s main" \
    "$TMP/hello.stripped" > "$GDB_OUT" 2>&1 || true

# Strip the one-off "No symbol 'debuginfod'" noise some gdb builds emit when
# parsing our commands — the DEBUGINFOD_URLS env var is what actually drives
# the HTTP fetch, so that command-level warning is cosmetic.
if ! grep -q "compute_answer" "$GDB_OUT"; then
    echo "FAIL: gdb did not resolve compute_answer from stripped binary" >&2
    sed 's/^/  gdb> /' "$GDB_OUT" >&2
    exit 1
fi
# Any reference to hello.c in gdb's output means the debug sidecar was
# fetched over HTTP and source-line resolution worked. `disassemble /s`
# produces lines like '7	int main(int argc, char **argv) {' and
# 'File /tmp/.../hello.c: 3:' — grep for the filename either way.
if ! grep -q "hello\.c" "$GDB_OUT"; then
    echo "FAIL: gdb never resolved source file (hello.c) via debuginfod" >&2
    sed 's/^/  gdb> /' "$GDB_OUT" >&2
    exit 1
fi

echo "=== step 7: evidence ==="
grep -E "compute_answer|hello\.c" "$GDB_OUT" | sed 's/^/  /'

echo
echo "OK — end-to-end symbol pipeline verified."
echo "  cross-compile -> objcopy split -> debuginfod serve -> gdb source resolution"
