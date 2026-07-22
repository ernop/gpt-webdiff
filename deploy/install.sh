#!/usr/bin/env bash
set -euo pipefail

Branch="${1:-master}"
InstallRoot="/opt/gpt-webdiff"
AppDir="${InstallRoot}/app"
VenvDir="${InstallRoot}/venv"
ServiceUser="gptwebdiff"
Repository="https://github.com/ernop/gpt-webdiff.git"
ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi

if ! id "${ServiceUser}" >/dev/null 2>&1; then
    useradd --system --home-dir "${InstallRoot}" --create-home --shell /usr/sbin/nologin "${ServiceUser}"
fi

install -d -o "${ServiceUser}" -g "${ServiceUser}" -m 0750 "${InstallRoot}"

if [[ ! -d "${AppDir}/.git" ]]; then
    runuser -u "${ServiceUser}" -- git clone --branch "${Branch}" --single-branch "${Repository}" "${AppDir}"
fi

if [[ ! -x "${VenvDir}/bin/python" ]]; then
    runuser -u "${ServiceUser}" -- python3 -m venv "${VenvDir}"
fi

runuser -u "${ServiceUser}" -- "${VenvDir}/bin/python" -m pip install --upgrade pip
runuser -u "${ServiceUser}" -- "${VenvDir}/bin/python" -m pip install -r "${AppDir}/requirements.txt"

install -o root -g root -m 0644 "${ScriptDir}/gpt-webdiff.service" /etc/systemd/system/gpt-webdiff.service
install -o root -g root -m 0644 "${ScriptDir}/gpt-webdiff.timer" /etc/systemd/system/gpt-webdiff.timer
systemctl daemon-reload

echo "Installed GPT-WebDiff from branch ${Branch}."
echo "Copy config.json to ${AppDir}/config.json, set ownership to ${ServiceUser}, then enable the timer."
