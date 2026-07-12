param(
    [string]$CondaEnv = "py311",
    [int]$BackendPort = 8765,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendScript = Join-Path $Root "scripts\run_web_backend.ps1"
$FrontendScript = Join-Path $Root "scripts\run_web_frontend.ps1"
$LogDir = Join-Path $Root "logs"
$BackendOutLog = Join-Path $LogDir "web-backend.out.log"
$BackendErrLog = Join-Path $LogDir "web-backend.err.log"
$HealthUrl = "http://127.0.0.1:$BackendPort/api/health"
$TokenPath = Join-Path $LogDir "web-api-token.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ApiToken = if (Test-Path $TokenPath) { (Get-Content -LiteralPath $TokenPath -Raw).Trim() } else { "" }
if ($ApiToken.Length -lt 32) {
    $TokenBytes = New-Object byte[] 32
    $TokenGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $TokenGenerator.GetBytes($TokenBytes)
    $TokenGenerator.Dispose()
    $ApiToken = -join ($TokenBytes | ForEach-Object { $_.ToString("x2") })
    Set-Content -LiteralPath $TokenPath -Value $ApiToken -NoNewline
}
$AuthHeaders = @{ Authorization = "Bearer $ApiToken" }

function Test-BackendReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -Headers $AuthHeaders -TimeoutSec 2
        $data = $response.Content | ConvertFrom-Json
        return $response.StatusCode -eq 200 -and $data.authenticated -eq $true
    } catch {
        return $false
    }
}

function Show-BackendLogs {
    if (Test-Path $BackendOutLog) {
        Write-Host ""
        Write-Host "Backend stdout tail:"
        Get-Content -Path $BackendOutLog -Tail 80
    }
    if (Test-Path $BackendErrLog) {
        Write-Host ""
        Write-Host "Backend stderr tail:"
        Get-Content -Path $BackendErrLog -Tail 120
    }
}

if (-not (Test-BackendReady)) {
    Write-Host "Starting Python backend on $HealthUrl ..."

    $backendProcess = Start-Process powershell -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $BackendOutLog `
        -RedirectStandardError $BackendErrLog `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $BackendScript,
            "-CondaEnv",
            $CondaEnv,
            "-Port",
            $BackendPort,
            "-ApiToken",
            $ApiToken
        )

    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendReady) {
            Write-Host "Python backend is ready."
            break
        }
        if ($backendProcess.HasExited) {
            Show-BackendLogs
            throw "Python backend exited before becoming ready. See logs\web-backend.err.log"
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not (Test-BackendReady)) {
        Show-BackendLogs
        throw "Python backend did not become ready within 45 seconds. See logs\web-backend.err.log"
    }
} else {
    Write-Host "Python backend is already running on $HealthUrl."
}

& $FrontendScript -Port $FrontendPort -BackendPort $BackendPort -ApiToken $ApiToken
