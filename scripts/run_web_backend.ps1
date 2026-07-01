param(
    [string]$CondaEnv = "py311",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

conda run -n $CondaEnv python backend/run_backend.py --config config.local.json --host 127.0.0.1 --port $Port
