#!/usr/bin/env bash
# Generate test apps of various sizes for exercising satdeploy push /
# rollback / status inside the dev container. Idempotent — files are only
# (re)created if missing or wrong size, so repeated container starts are
# fast.
#
# Sizes are chosen to exercise different code paths:
#   tiny     ~50 B   shell script — minimum end-to-end transfer
#   small   100 KB   sub-second at 3 MB/s — common case
#   medium    5 MB   multi-buffer DTP path
#   large    50 MB   long enough to Ctrl-C mid-transfer (cross-pass resume!)
set -euo pipefail

DEST="${1:-/tmp/satdeploy-test-apps}"
mkdir -p "$DEST"

# `hello` is a real shell script — proves the deploy preserves +x and
# the file actually executes on the target.
cat > "$DEST/hello" <<'EOF'
#!/bin/sh
echo "hello from satdeploy test-app, deployed at $(date -u +%FT%TZ)"
EOF
chmod +x "$DEST/hello"

# /dev/urandom so the SHA256 hash actually changes between regenerations —
# important for testing version-skew detection and the no-op redeploy path.
make_blob() {
    local path="$1" size="$2"
    if [ ! -f "$path" ] || [ "$(stat -c%s "$path" 2>/dev/null)" != "$size" ]; then
        head -c "$size" /dev/urandom > "$path"
        chmod +x "$path"
    fi
}

make_blob "$DEST/controller" $((100 * 1024))
make_blob "$DEST/telemetry"  $((5 * 1024 * 1024))
make_blob "$DEST/payload"    $((50 * 1024 * 1024))

echo "Test apps in $DEST:"
ls -lh "$DEST"
