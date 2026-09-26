# Instala o T.I Chamados no Windows (pasta atual) e cria atalhos de inicialização.
# Uso (PowerShell como administrador): powershell -ExecutionPolicy Bypass -File scripts\instalar-windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "Python não encontrado. Instale o Python 3.10+ em https://www.python.org/downloads/ marcando 'Add python.exe to PATH'."
    exit 1
}

Write-Host "==> Criando ambiente virtual"
& $python.Source -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

Write-Host "==> Liberando a porta 8080 no firewall"
if (-not (Get-NetFirewallRule -DisplayName "TI Chamados" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "TI Chamados" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow | Out-Null
}

Write-Host "==> Registrando tarefa para iniciar junto com o Windows"
$action = New-ScheduledTaskAction -Execute "$Root\.venv\Scripts\python.exe" -Argument "run.py" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "TI Chamados" -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName "TI Chamados"

Write-Host ""
Write-Host "Pronto! Acesse http://localhost:8080 para concluir a configuração."
