#!/usr/bin/env bash
# Build the manual as a static HTML site.
#
#   scripts/build_docs.sh            # build into site/
#   scripts/build_docs.sh serve      # live preview on http://127.0.0.1:8000
#
# mkdocs lives in .mkdocs-venv so the system Python stays untouched; the first run creates it.
# --strict turns warnings into errors, so a broken link or a missing page fails the build instead of
# shipping quietly.
set -eo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$(dirname "${here}")"
venv="${project}/.mkdocs-venv"

if [ ! -x "${venv}/bin/mkdocs" ]; then
  echo "docs: creating ${venv} and installing mkdocs (once)"
  python3 -m venv "${venv}"
  "${venv}/bin/pip" install --quiet --upgrade pip
  "${venv}/bin/pip" install --quiet mkdocs
fi

cd "${project}"
if [ "${1:-build}" = "serve" ]; then
  echo "docs: serving on http://127.0.0.1:8000  (Ctrl+C to stop)"
  exec "${venv}/bin/mkdocs" serve --dev-addr 127.0.0.1:8000
fi
exec "${venv}/bin/mkdocs" build --strict
