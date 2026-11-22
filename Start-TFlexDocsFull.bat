@echo off
setlocal
title T-FLEX Full - Launcher
set "TFLEX_FULL_LAUNCHER=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$text = [IO.File]::ReadAllText($env:TFLEX_FULL_LAUNCHER); $parts = $text -split '(?m)^# TFLEX_FULL_POWERSHELL\r?$', 2; if ($parts.Count -ne 2) { Write-Error 'Launcher payload not found'; exit 1 }; & ([scriptblock]::Create($parts[1]))"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Startup failed. Review the messages above.
pause
exit /b %RESULT%
# TFLEX_FULL_POWERSHELL
$ErrorActionPreference = 'Stop'
try {
    $LauncherDir = Split-Path -LiteralPath $env:TFLEX_FULL_LAUNCHER
    $Script = Join-Path $LauncherDir 'Start-TFlexFull.ps1'
    $KeyFile = Join-Path $env:APPDATA 'TFlexDocs\mcp-api-key.dpapi'

    foreach ($File in @($Script, $KeyFile)) {
        if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
            throw ('Required file missing: ' + $File)
        }
    }
    foreach ($Name in @('uv', 'ngrok', 'Get-NetTCPConnection')) {
        if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
            throw ('Required command not found: ' + $Name)
        }
    }
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 8000 is busy. Stop the old MCP server first. No new processes started.'
    }
    if (Get-Process -Name ngrok -ErrorAction SilentlyContinue) {
        throw 'ngrok is already running. No new processes started.'
    }

    # The server script reads the existing DPAPI key itself.
    # Do not pass an inherited plaintext MCP key to either new window.
    Remove-Item Env:\TFLEX_MCP_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\TFLEX_MCP_ALLOW_RUN -ErrorAction SilentlyContinue

    $PowerShellExe = Join-Path $PSHOME 'powershell.exe'
    $ServerArgs = '-NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "{0}" -EnableRun -EnableBridgeRead' -f $Script
    Write-Host 'Starting full MCP server with C# execution and direct bridge reads enabled.'
    $ServerProcess = Start-Process -FilePath $PowerShellExe -ArgumentList $ServerArgs -WorkingDirectory $LauncherDir -PassThru

    Write-Host 'Waiting up to 120 seconds for local port 8000...'
    $Deadline = (Get-Date).AddSeconds(120)
    while (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
        if ($ServerProcess.HasExited) {
            throw 'Server window closed before port 8000 became available. ngrok was not started.'
        }
        if ((Get-Date) -ge $Deadline) {
            throw 'Startup timeout. Inspect the MCP server window. ngrok was not started.'
        }
        Start-Sleep -Milliseconds 500
    }

    # A listening port is a readiness signal, not an authenticated MCP health check.
    $TunnelArgs = '-NoLogo -NoProfile -NoExit -Command "& ngrok http http://127.0.0.1:8000 --host-header=127.0.0.1:8000 --inspect=false; if ($LASTEXITCODE -ne 0) { Write-Host (''ngrok exited with code '' + $LASTEXITCODE) -ForegroundColor Red }"'
    Start-Process -FilePath $PowerShellExe -ArgumentList $TunnelArgs -WorkingDirectory $LauncherDir | Out-Null

    Write-Host ''
    Write-Host 'Startup commands completed. Check BOTH new windows for errors.'
    Write-Host 'MCP: confirm Run enabled: True and Bridge reads enabled: True.'
    Write-Host 'ngrok: confirm Session Status = online.'
    Write-Host 'Connector URL: HTTPS forwarding address + /mcp.'
    Write-Host 'The existing MCP API key and local ngrok configuration are reused.'
    Write-Host 'Keep both windows open. Stop each service with Ctrl+C.'
    Write-Host 'This launcher does not verify CAD geometry or grant approval for CAD operations.'
    exit 0
}
catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'No processes were terminated automatically. Inspect any windows already opened.'
    exit 1
}