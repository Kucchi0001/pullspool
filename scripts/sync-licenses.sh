#!/bin/sh
# Mirror repository-level license files into the Docker build context.
# Run after changing THIRD_PARTY_NOTICES.md, LICENSES/ or THIRD_PARTY_LICENSES/.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

rm -rf docker/licenses
mkdir -p docker/licenses
cp LICENSE docker/licenses/
cp THIRD_PARTY_NOTICES.md docker/licenses/
cp -R LICENSES docker/licenses/
cp -R THIRD_PARTY_LICENSES docker/licenses/

cat > docker/licenses/README.md <<'EOF'
This directory is copied into every PullSpool image at
/usr/share/doc/pullspool/ so users who only pull an image still receive the
third-party notices and license texts.

It is a build-time mirror of:
  ../../LICENSE
  ../../THIRD_PARTY_NOTICES.md
  ../../LICENSES/
  ../../THIRD_PARTY_LICENSES/

Regenerate with scripts/sync-licenses.sh after changing any of those files.
EOF

echo "synced docker/licenses ($(find docker/licenses -type f | wc -l) files)"
