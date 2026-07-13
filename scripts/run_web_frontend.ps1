param(
    [int]$Port = 5173,
    [int]$BackendPort = 8765,
    [Parameter(Mandatory = $true)]
    [string]$ApiToken
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $Root "frontend")
$env:VITE_API_TOKEN = $ApiToken
$env:VITE_BACKEND_PORT = [string]$BackendPort

if (-not (Test-Path "node_modules")) {
    npm ci
}

npm run dev -- --port $Port
