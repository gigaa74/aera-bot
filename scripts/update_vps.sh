#!/usr/bin/env bash
# Update only AERA's source and services, preserving its .env and live database.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
    echo 'Run as root: bash scripts/update_vps.sh /root/aera-bot-vps.zip'
    exit 1
fi
task_archive=${1:-/root/aera-bot-vps.zip}
if [[ ! -f $task_archive || ! -x /opt/aera/.venv/bin/python || ! -f /opt/aera/.env ]]; then
    echo 'Existing AERA installation or source ZIP missing. No services changed.'
    exit 1
fi
if [[ $(getent passwd aera | cut -d: -f6) != /opt/aera ]]; then
    echo 'The aera account does not belong to /opt/aera. No services changed.'
    exit 1
fi
# Validate before stopping the bot. Reject secrets, databases and unsafe paths.
python3 - "$task_archive" <<'PY'
import hashlib
import sys
from pathlib import PurePosixPath
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as archive:
    names = archive.namelist()
    required = {'app/services/manual_lifecycle.py', 'scripts/install_preview.sh',
                'alembic/versions/0006_manual_portal.py', 'app/bot/portal.py',
                'scripts/bootstrap_portal.py',
                'alembic/versions/0007_paid_inventory.py', 'app/services/paid_pool.py',
                'alembic/versions/0008_trial_recycling.py',
                'alembic/versions/0009_trial_ready_time.py',
                'app/services/trial_recycling.py', 'app/services/trial_activation.py',
                'app/integrations/xui/trial_keys.py',
                'app/assets/installers/Hiddify-Windows-Setup-x64.exe'}
    if not required <= set(names) or len(names) != len(set(names)):
        raise SystemExit('Incomplete source ZIP. No services changed.')
    for name in names:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or any(part.startswith('.') and part not in
                       {'.env.example', '.gitignore', '.dockerignore', '.github'}
                       for part in path.parts)
                or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.log', '.zip', '.pyc'}):
            raise SystemExit('Unsafe source ZIP. No services changed.')
    expected = '3f6182b610168c0bb386ffea1fc7f68318d3df23c15840c8b13a3be51b080a96'
    checksum = hashlib.sha256()
    with archive.open('app/assets/installers/Hiddify-Windows-Setup-x64.exe') as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b''):
            checksum.update(chunk)
    if checksum.hexdigest() != expected or archive.testzip() is not None:
        raise SystemExit('ZIP integrity check failed. No services changed.')
print('Source ZIP checked; credentials and database will be preserved.')
PY
# Check that the private import belongs to the installed bot before stopping AERA.
/opt/aera/.venv/bin/python - "$task_archive" <<'PY'
import base64
import hashlib
import json
import sys
from zipfile import ZipFile
from cryptography.fernet import Fernet
from dotenv import dotenv_values

with ZipFile(sys.argv[1]) as archive:
    if 'private-bootstrap.enc' in archive.namelist():
        token = dotenv_values('/opt/aera/.env').get('BOT_TOKEN', '')
        key = base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest())
        try:
            payload = json.loads(Fernet(key).decrypt(archive.read('private-bootstrap.enc')))
            assert isinstance(payload['trial_links'], list)
            assert isinstance(payload.get('paid_links', {}), dict)
        except Exception:
            raise SystemExit('Private import does not match BOT_TOKEN. No services changed.')
print('Encrypted private import checked; no private values printed.')
PY
systemctl stop aera-preview-bot.service aera-preview-runtime.service
python3 - "$task_archive" <<'PY'
import sys
from pathlib import Path
from zipfile import ZipFile

root = Path('/opt/aera').resolve()
with ZipFile(sys.argv[1]) as archive:
    for info in archive.infolist():
        candidate = root.joinpath(info.filename)
        target = candidate.resolve()
        if root not in target.parents or any(p.is_symlink() for p in [candidate, *candidate.parents]):
            raise SystemExit('Source target escapes /opt/aera. AERA remains stopped.')
    archive.extractall(root)
PY
chown -R aera:aera /opt/aera
chmod 750 /opt/aera
chmod 600 /opt/aera/.env
if [[ -f /opt/aera/private-bootstrap.enc ]]; then
    chmod 600 /opt/aera/private-bootstrap.enc
fi
cd /opt/aera
bash scripts/install_preview.sh start
echo 'AERA updated. Open /start and /admin in Telegram.'
