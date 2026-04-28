# Build verification image for satdeploy.
#
# Goal: a clean Ubuntu container that builds satdeploy-agent (native x86_64)
# and satdeploy-apm (shared library), then smoke-tests the version flag and
# version-skew guard. Native — not Yocto — because the verification we need
# here is "does meson configure_file embed the version correctly, does
# `--version` work, does the version.h template compile", all of which are
# architecture-independent.
#
# For real flight builds, see satdeploy-agent/yocto_cross.ini and the build
# instructions in CLAUDE.md.
#
# Usage:
#   docker build -t satdeploy-test .
#   docker run --rm satdeploy-test
#
# Or invoke ./scripts/docker-test.sh from the host.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        meson \
        ninja-build \
        pkg-config \
        git \
        ca-certificates \
        libssl-dev \
        libsocketcan-dev \
        libzmq3-dev \
        libprotobuf-c-dev \
        protobuf-c-compiler \
        libyaml-dev \
        libsqlite3-dev \
        python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /satdeploy
COPY . /satdeploy

# Build the agent (x86_64 native — for verification only, never deploy).
# `--reconfigure` forces meson to re-run configure_file so version.h picks up
# the current git rev. The build-native dir name matches CLAUDE.md convention.
RUN meson setup satdeploy-agent/build-native satdeploy-agent --wipe \
    && ninja -C satdeploy-agent/build-native

# Build the APM shared library.
RUN meson setup satdeploy-apm/build satdeploy-apm --wipe \
    && ninja -C satdeploy-apm/build

# Smoke test the version flag on the agent. `set -e` makes the build fail if
# either the binary or the strings check fails — the Dockerfile becomes a CI
# gate for the version-flag work.
RUN set -e \
    && echo "=== agent --version ===" \
    && ./satdeploy-agent/build-native/satdeploy-agent --version \
    && echo "=== agent -V (short flag) ===" \
    && ./satdeploy-agent/build-native/satdeploy-agent -V \
    && echo "=== agent --help (truncated) ===" \
    && ./satdeploy-agent/build-native/satdeploy-agent --help | head -20 \
    && echo "=== APM .so version baked in (format string + value, %s-interpolated at runtime) ===" \
    && strings satdeploy-apm/build/libcsh_satdeploy_apm.so | grep -F "satdeploy-apm %s" \
    && strings satdeploy-apm/build/libcsh_satdeploy_apm.so | grep -F "0.4.0" \
    && echo "=== version.h contents (agent) ===" \
    && cat satdeploy-agent/build-native/version.h \
    && echo "=== version.h contents (APM) ===" \
    && cat satdeploy-apm/build/version.h \
    && echo "=== sanity check: version-skew error string is in the agent binary ===" \
    && strings ./satdeploy-agent/build-native/satdeploy-agent | grep -q "version skew: APM is older than agent" \
    && echo "    OK: skew error string baked in" \
    && echo "=== ALL VERIFICATIONS PASSED ==="

CMD ["/bin/bash"]
