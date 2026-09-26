#!/usr/bin/env bash
# Inicia o T.I Chamados manualmente (Linux/macOS). Na primeira execução instala as dependências.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
    echo "Instalando dependências..."
    python3 -m venv .venv
    .venv/bin/pip install --quiet -r requirements.txt
fi
exec .venv/bin/python run.py
