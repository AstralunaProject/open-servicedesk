#!/usr/bin/env bash
# Instala o Open Servicedesk em /opt/open-servicedesk e registra um serviço systemd.
# Uso: sudo ./scripts/instalar-linux.sh [porta]
set -euo pipefail

PORT="${1:-8080}"
DEST=/opt/open-servicedesk
SERVICE_USER=chamados
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { echo "Erro: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "execute com sudo."
command -v python3 >/dev/null || fail "python3 não encontrado. Instale com: apt install python3 python3-venv"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fail "é necessário Python 3.10 ou superior."
python3 -m venv --help >/dev/null 2>&1 || fail "módulo venv ausente. Instale com: apt install python3-venv"

echo "==> Copiando arquivos para $DEST"
mkdir -p "$DEST"
cp -r "$SRC"/app "$SRC"/run.py "$SRC"/wsgi.py "$SRC"/requirements.txt "$DEST"/

id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin "$SERVICE_USER"

echo "==> Instalando dependências"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --quiet --upgrade pip
"$DEST/.venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

if [[ ! -f "$DEST/.env" ]]; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    cat > "$DEST/.env" <<ENV
PORT=$PORT
BASE_URL=http://${IP:-localhost}:$PORT
CHAMADOS_DATA_DIR=$DEST/data
ENV
fi
mkdir -p "$DEST/data"
chown -R "$SERVICE_USER": "$DEST"
chmod 600 "$DEST/.env"

echo "==> Criando serviço systemd"
cat > /etc/systemd/system/open-servicedesk.service <<UNIT
[Unit]
Description=Open Servicedesk - central de serviços de T.I
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$DEST
ExecStart=$DEST/.venv/bin/python run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now open-servicedesk

cat > /etc/cron.d/open-servicedesk-backup <<CRON
# Backup diário às 02h, mantendo os últimos 14 arquivos.
0 2 * * * $SERVICE_USER cd $DEST && .venv/bin/flask --app wsgi backup >/dev/null && ls -1t data/backups/*.zip | tail -n +15 | xargs -r rm --
CRON

echo
echo "Pronto! Acesse $(grep BASE_URL "$DEST/.env" | cut -d= -f2) para concluir a configuração."
echo "Logs: journalctl -u open-servicedesk -f"
