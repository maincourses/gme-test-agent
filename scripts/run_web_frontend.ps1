param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $Root "frontend")

if (-not (Test-Path "node_modules")) {
    npm install
}

npm run dev -- --port $Port
