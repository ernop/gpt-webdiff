#!/usr/bin/env bash
set -euo pipefail

AppDir="/opt/gpt-webdiff/app"
VenvDir="/opt/gpt-webdiff/venv"
ServiceUser="gptwebdiff"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this updater as root." >&2
    exit 1
fi

if systemctl is-active --quiet gpt-webdiff.service; then
    echo "GPT-WebDiff is currently running; retry after this check completes." >&2
    exit 1
fi

runuser -u "${ServiceUser}" -- git -C "${AppDir}" pull --ff-only
runuser -u "${ServiceUser}" -- "${VenvDir}/bin/python" -m pip install -r "${AppDir}/requirements.txt"
runuser -u "${ServiceUser}" -- env PYTHONPATH="${AppDir}" "${VenvDir}/bin/python" -m unittest discover -s "${AppDir}/tests" -v

if [[ "${1:-}" == "--run-now" ]]; then
    systemctl start gpt-webdiff.service
fi
