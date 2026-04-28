#!/usr/bin/env bash
# Build the satdeploy-test image and run it. The Dockerfile itself runs the
# version-flag smoke tests during `docker build`, so a successful build means
# the verifications passed. This script is just a convenience wrapper.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_TAG="${IMAGE_TAG:-satdeploy-test}"

echo ">>> Building $IMAGE_TAG (this rebuilds CSP/param/DTP/protobuf-c — first run is slow)"
docker build -t "$IMAGE_TAG" .

echo
echo ">>> Build succeeded — version verifications above passed."
echo ">>> Drop into a shell to poke around:"
echo "    docker run --rm -it $IMAGE_TAG"
