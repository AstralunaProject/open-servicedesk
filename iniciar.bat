@echo off
rem Inicia o Open Servicedesk manualmente (Windows). Na primeira execução instala as dependências.
cd /d "%~dp0"
if not exist .venv (
    echo Instalando dependencias...
    py -m venv .venv 2>nul || python -m venv .venv || (echo Python 3.10+ nao encontrado. & pause & exit /b 1)
    .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt || (pause & exit /b 1)
)
.venv\Scripts\python.exe run.py
pause
