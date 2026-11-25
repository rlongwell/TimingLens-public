#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
./timinglens.sh --help > /dev/null
.venv/bin/python -m pip install -e '.[gui,test]'
if [[ "${1:-}" == "--with-vivado" ]]; then
    export TIMINGLENS_TEST_VIVADO=1
    shift
    ./timinglens.sh doctor
fi
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
exec .venv/bin/python -m pytest "$@"
