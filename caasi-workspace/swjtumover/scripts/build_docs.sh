#!/usr/bin/env bash
# Build the documentation as a static HTML site, outside the project directory.
#
#   scripts/build_docs.sh            # build into ../swjtumover-docs
#   scripts/build_docs.sh serve      # live preview on http://127.0.0.1:8000
#
# mkdocs lives in .mkdocs-venv so the system Python stays untouched; the first run creates it.
# --strict turns warnings into errors, so a broken link or a missing page fails the build instead of
# shipping quietly.
set -eo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$(dirname "${here}")"
# Build tooling lives outside the product: the project ships the sources (docs/, mkdocs.yml) and
# the person building the site supplies mkdocs, either from PATH or from this shared venv.
venv="${project}/../.docs-venv"
site="${project}/../swjtumover-docs"

if command -v mkdocs >/dev/null 2>&1; then
  mkdocs_cmd=(mkdocs)
elif [ -x "${venv}/bin/python" ]; then
  # call through the interpreter: a moved venv keeps stale shebangs, `-m` does not care
  mkdocs_cmd=("${venv}/bin/python" -m mkdocs)
else
  echo "docs: mkdocs not found; installing it into ${venv} (outside the project)"
  python3 -m venv "${venv}"
  "${venv}/bin/pip" install --quiet --upgrade pip
  "${venv}/bin/pip" install --quiet mkdocs
  mkdocs_cmd=("${venv}/bin/python" -m mkdocs)
fi

cd "${project}"
if [ "${1:-build}" = "serve" ]; then
  echo "docs: serving on http://127.0.0.1:8000  (Ctrl+C to stop)"
  exec "${mkdocs_cmd[@]}" serve --dev-addr 127.0.0.1:8000
fi
exec "${mkdocs_cmd[@]}" build --strict --site-dir "${site}"
