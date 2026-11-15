#!/usr/bin/env bash
# Build a runnable, self-contained Tarla Dostu bundle.
#
# The farmer UI is plain HTML/CSS/JS, so there is no frontend compilation step.
# "Build" here means: verify the Python app, run the test suite, and package
# everything needed to boot the service on any machine with Python 3.12+.
#
# Usage:
#   ./scripts/build.sh              # verify + package
#   ./scripts/build.sh --skip-tests # package only
#   ./scripts/build.sh --docker     # also build the Docker image
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_TESTS=0
BUILD_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    --docker) BUILD_DOCKER=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "Bilinmeyen seçenek: $arg" >&2
      exit 2
      ;;
  esac
done

PYTHON="${PYTHON:-python3}"
VERSION="$("$PYTHON" - <<'PY'
from pathlib import Path
import re
text = Path("app/config.py").read_text(encoding="utf-8")
match = re.search(r'app_version:\s*str\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "dev")
PY
)"
STAMP="$(date -u +%Y%m%d)"
DIST="$ROOT/dist"
BUNDLE="tarla-dostu-${VERSION}-${STAMP}"

echo "==> Python $( "$PYTHON" -V 2>&1 | cut -d' ' -f2 ) • sürüm ${VERSION}"

echo "==> Sözdizimi kontrolü"
"$PYTHON" -m compileall -q app

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  echo "==> Testler"
  "$PYTHON" -m pytest -q
fi

echo "==> Paket hazırlanıyor"
mkdir -p "$DIST"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$BUNDLE"
cp -R app web "$STAGE/$BUNDLE/"
cp requirements.txt run.py README.md Procfile render.yaml "$STAGE/$BUNDLE/"
find "$STAGE/$BUNDLE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE/$BUNDLE" -type f -name '*.pyc' -delete

tar -C "$STAGE" -czf "$DIST/$BUNDLE.tar.gz" "$BUNDLE"
( cd "$DIST" && sha256sum "$BUNDLE.tar.gz" > "$BUNDLE.tar.gz.sha256" )

echo "==> Paket: dist/$BUNDLE.tar.gz"
ls -lh "$DIST/$BUNDLE.tar.gz" | awk '{print "    boyut: " $5}'
echo "    çalıştırma: tar -xzf $BUNDLE.tar.gz && cd $BUNDLE && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000"

if [[ "$BUILD_DOCKER" -eq 1 ]]; then
  echo "==> Docker imajı"
  docker build -t "tarla-dostu:${VERSION}" .
fi

echo "==> Tamam. Arayüz: http://127.0.0.1:8000/app/"
