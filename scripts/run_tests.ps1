param(
    [string]$CondaEnv = "py311"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

conda run -n $CondaEnv python -m unittest discover -s tests
