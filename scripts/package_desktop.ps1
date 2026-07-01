param(
    [ValidateSet("portable", "unpacked")]
    [string]$Target = "portable",
    [string]$Python = "",
    [string]$CondaEnv = "py311",
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $SkipBackend) {
    & (Join-Path $PSScriptRoot "package_backend.ps1") -Python $Python -CondaEnv $CondaEnv
}

Set-Location (Join-Path $Root "frontend")

$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"

if (-not (Test-Path "node_modules")) {
    npm install
}

if ($Target -eq "portable") {
    npm run electron:portable
} else {
    npm run electron:pack
}
