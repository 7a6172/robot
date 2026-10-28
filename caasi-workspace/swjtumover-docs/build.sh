#!/usr/bin/env bash
# Build the swjtumover manual and place the HTML inside the package.
#
#   ./build.sh          -> ../swjtumover/docs/*.html   (what ships)
#   ./build.sh serve    live preview on http://127.0.0.1:8000
#
# The Markdown sources live here, next to this script; the package carries only the generated HTML.
# mkdocs comes from PATH, or from the shared venv in ./.venv, which this creates on first use.
set -eo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="${here}/.venv"
out="${here}/../swjtumover/docs"

if command -v mkdocs >/dev/null 2>&1; then
  mkdocs_cmd=(mkdocs)
elif [ -x "${venv}/bin/python" ]; then
  # call through the interpreter: a relocated venv keeps stale shebangs, `-m` does not care
  mkdocs_cmd=("${venv}/bin/python" -m mkdocs)
else
  echo "docs: mkdocs not found; installing it into ${venv}"
  python3 -m venv "${venv}"
  "${venv}/bin/pip" install --quiet --upgrade pip
  "${venv}/bin/pip" install --quiet mkdocs
  mkdocs_cmd=("${venv}/bin/python" -m mkdocs)
fi

cd "${here}"
if [ "${1:-build}" = "serve" ]; then
  echo "docs: serving on http://127.0.0.1:8000  (Ctrl+C to stop)"
  exec "${mkdocs_cmd[@]}" serve --dev-addr 127.0.0.1:8000
fi
# --strict: a broken link or a missing page fails the build instead of shipping quietly
exec "${mkdocs_cmd[@]}" build --strict --site-dir "${out}"
