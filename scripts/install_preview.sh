#!/usr/bin/env bash
# Manual Ubuntu 22.04 setup of the isolated bot. Does not manage 3x-ui or firewall.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo 'Run with sudo: sudo bash scripts/install_preview.sh setup|start'
    exit 1
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 22.04 ]]; then
    echo 'This installer is prepared for Ubuntu 22.04 only.'
    exit 1
fi
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [[ $task_root != /opt/aera ]]; then
    echo 'Extract the source package into the new /opt/aera directory first.'
    exit 1
fi
cd -- "$task_root"

case ${1:-} in
    setup)
        command -v curl >/dev/null || { echo 'Install curl first.'; exit 1; }
        if id aera >/dev/null 2>&1; then
            task_account_home=$(getent passwd aera | cut -d: -f6)
            if [[ $task_account_home != /opt/aera ]]; then
                echo 'Existing aera user belongs to another location; stop and check.'
                exit 1
            fi
        else
            useradd --system --user-group --home-dir /opt/aera --shell /usr/sbin/nologin aera
        fi
        chown -R aera:aera /opt/aera
        chmod 750 /opt/aera
        install -d -o aera -g aera -m 750 /opt/aera/tools /opt/aera/python
        if [[ ! -x /opt/aera/tools/uv ]]; then
            curl -LsSf https://astral.sh/uv/install.sh -o /opt/aera/tools/install-uv.sh
            runuser -u aera -- env UV_INSTALL_DIR=/opt/aera/tools UV_NO_MODIFY_PATH=1 \
                sh /opt/aera/tools/install-uv.sh
        fi
        runuser -u aera -- env UV_PYTHON_INSTALL_DIR=/opt/aera/python \
            UV_PYTHON_INSTALL_BIN=false /opt/aera/tools/uv python install 3.12
        if [[ ! -x /opt/aera/.venv/bin/python ]]; then
            runuser -u aera -- env UV_PYTHON_INSTALL_DIR=/opt/aera/python \
                /opt/aera/tools/uv venv --python 3.12 --seed /opt/aera/.venv
        fi
        runuser -u aera -- /opt/aera/tools/uv pip install \
            --python /opt/aera/.venv/bin/python -r /opt/aera/requirements.lock
        runuser -u aera -- /opt/aera/.venv/bin/python -m scripts.setup_env
        chmod 600 /opt/aera/.env
        echo 'Setup finished. Edit /opt/aera/.env: BOT_TOKEN, BOT_USERNAME, ADMIN_TELEGRAM_IDS.'
        echo 'Then stop the PC bot and run: sudo bash scripts/install_preview.sh start'
        ;;
    start)
        if [[ ! -x /opt/aera/.venv/bin/python || ! -f /opt/aera/.env ]]; then
            echo 'Run setup and fill the private .env first.'
            exit 1
        fi
        if ! systemctl is-active --quiet aera-preview-runtime.service; then
            if [[ -n $(ss -H -ltn '( sport = :8000 or sport = :6389 )') ]]; then
                echo 'Port 8000 or 6389 is occupied. Stop and check; no process was killed.'
                exit 1
            fi
        fi
        runuser -u aera -- /opt/aera/.venv/bin/python - <<'PY'
from dotenv import dotenv_values
values = dotenv_values('.env')
if not values.get('BOT_TOKEN') or values.get('BOT_USERNAME') != 'AERAVPN_BOT':
    raise SystemExit('Fill BOT_TOKEN and BOT_USERNAME=AERAVPN_BOT first.')
ids = (values.get('ADMIN_TELEGRAM_IDS') or '').split(',')
if not ids or not all(value.strip().isdigit() for value in ids):
    raise SystemExit('Set the numeric ADMIN_TELEGRAM_IDS first.')
print('Required bot settings present; private values not printed.')
PY
        install -m 644 docker/systemd/aera-preview-runtime.service /etc/systemd/system/aera-preview-runtime.service
        install -m 644 docker/systemd/aera-preview-bot.service /etc/systemd/system/aera-preview-bot.service
        systemctl daemon-reload
        systemctl enable --now aera-preview-runtime.service
        task_ready=0
        # The first startup can take longer under the service's CPU quota.
        task_deadline=$((SECONDS + 180))
        while (( SECONDS < task_deadline )); do
            if runuser -u aera -- /opt/aera/.venv/bin/python -m scripts.local_status; then
                task_ready=1
                break
            fi
            sleep 1
        done
        if [[ $task_ready != 1 ]]; then
            echo 'Runtime not ready. Read: journalctl -u aera-preview-runtime.service -n 30'
            exit 1
        fi
        systemctl enable --now aera-preview-bot.service
        systemctl status aera-preview-runtime.service aera-preview-bot.service --no-pager
        echo 'Check /start and /admin. Stars fulfillment and automatic trial-only key recycling.'
        ;;
    *)
        echo 'Usage: sudo bash scripts/install_preview.sh setup|start'
        exit 1
        ;;
esac
