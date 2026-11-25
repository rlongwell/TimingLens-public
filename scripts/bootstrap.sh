#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    printf '%s\n' 'TimingLens requires Python 3.11 or newer.' >&2
    exit 1
fi
export TIMINGLENS_REPO_ROOT="$project_root"
environment="$project_root/.venv"
exec 9>"$project_root/.timinglens-setup.lock"
flock 9
if [[ ! -x "$environment/bin/python" ]]; then
    if ! python3 -m venv "$environment"; then
        printf '%s\n' 'Install Ubuntu python3-venv and retry.' >&2
        exit 1
    fi
fi
spec="$(sha256sum "$project_root/pyproject.toml" | cut -d ' ' -f1)"
marker="$environment/timinglens-installed"
if [[ ! -f "$marker" || "$(cat "$marker")" != "$spec" || ! -x "$environment/bin/timinglens" ]]; then
    "$environment/bin/python" -m pip install -e "$project_root[gui]"
    printf '%s\n' "$spec" > "$marker"
fi
flock -u 9
exec 9>&-
exec "$environment/bin/timinglens" "$@"
