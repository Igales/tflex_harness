@echo off
setlocal
title T-FLEX Geometry - Launcher
set "TFLEX_FULL_LAUNCHER=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$text = [IO.File]::ReadAllText($env:TFLEX_FULL_LAUNCHER); $parts = $text -split '(?m)^# TFLEX_FULL_POWERSHELL\r?$', 2; if ($parts.Count -ne 2) { Write-Error 'Launcher payload not found'; exit 1 }; & ([scriptblock]::Create($parts[1]))"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Startup failed. Read the messages above. Existing processes were not stopped.
pause
exit /b %RESULT%
# TFLEX_FULL_POWERSHELL
$ErrorActionPreference = 'Stop'
try {
    $LauncherDir = Split-Path -LiteralPath $env:TFLEX_FULL_LAUNCHER
    $Script = Join-Path $LauncherDir 'Start-TFlexFull.ps1'
    $KeyFile = Join-Path $env:APPDATA 'TFlexDocs\mcp-api-key.dpapi'
    foreach ($File in @($Script, $KeyFile, (Join-Path $LauncherDir 'serve_mcp_full.py'), (Join-Path $LauncherDir 'tflex_geometry_stage1.py'))) {
        if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { throw ('Required file missing: ' + $File) }
    }
    foreach ($Name in @('uv', 'Get-NetTCPConnection')) {
        if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw ('Required command not found: ' + $Name) }
    }
    $ScriptText = [IO.File]::ReadAllText($Script)
    $RepoMatch = [regex]::Match($ScriptText, '(?m)^\$Repo\s*=\s*"([^"\r\n]+)"')
    if (-not $RepoMatch.Success -or -not [String]::Equals([IO.Path]::GetFullPath($RepoMatch.Groups[1].Value).TrimEnd('\'), [IO.Path]::GetFullPath($LauncherDir).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Start-TFlexFull.ps1 points to a different folder. No process started.'
    }
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 8000 is busy. The server may already be running. Do not launch a second server. No process started.'
    }
    $ReuseTunnel = $false
    if (Get-Process -Name ngrok -ErrorAction SilentlyContinue) {
        try {
            $Tunnels = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 5
            $Matching = @($Tunnels.tunnels | Where-Object {
                $_.proto -eq 'https' -and $_.public_url -match '^https://' -and
                $_.config.addr -match '^(https?://)?(127\.0\.0\.1|localhost):8000/?$'
            })
        } catch { throw 'ngrok is running, but its local API could not verify the tunnel. No process started. Inspect the existing tunnel; it was not modified.' }
        if ($Matching.Count -ne 1) { throw 'ngrok is running without exactly one verified HTTPS tunnel to localhost:8000. No process started; no tunnel modified.' }
        $ReuseTunnel = $true
        Write-Host ('Reusing verified ngrok endpoint: ' + $Matching[0].public_url + '/mcp')
    } elseif (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) { throw 'ngrok not found. No process started.' }

    # Existing DPAPI key is read by Start-TFlexFull.ps1, never printed or copied.
    Remove-Item Env:\TFLEX_MCP_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\TFLEX_MCP_ALLOW_RUN -ErrorAction SilentlyContinue
    Remove-Item Env:\TFLEX_MCP_ALLOW_BRIDGE_READ -ErrorAction SilentlyContinue
    Remove-Item Env:\TFLEX_MCP_ALLOW_BRIDGE_EDIT -ErrorAction SilentlyContinue
    $PowerShellExe = Join-Path $PSHOME 'powershell.exe'
    $ServerArgs = '-NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "{0}" -EnableBridgeRead -EnableBridgeEdit' -f $Script
    Write-Host 'Starting MCP: bridge read/edit enabled, arbitrary C# run disabled.'
    $ServerProcess = Start-Process -FilePath $PowerShellExe -ArgumentList $ServerArgs -WorkingDirectory $LauncherDir -PassThru
    $Deadline = (Get-Date).AddSeconds(120)
    while (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
        if ($ServerProcess.HasExited) { throw 'Server window closed before port 8000 became available. No new tunnel started.' }
        if ((Get-Date) -ge $Deadline) { throw 'Server startup timeout. Inspect the server window. No process was killed.' }
        Start-Sleep -Milliseconds 500
    }
    # A listening port is not an authenticated MCP health check.
    if (-not $ReuseTunnel) {
        $TunnelArgs = '-NoLogo -NoProfile -NoExit -Command "& ngrok http http://127.0.0.1:8000 --host-header=127.0.0.1:8000 --inspect=false; if ($LASTEXITCODE -ne 0) { Write-Host (''ngrok exited with code '' + $LASTEXITCODE) -ForegroundColor Red }"'
        Start-Process -FilePath $PowerShellExe -ArgumentList $TunnelArgs -WorkingDirectory $LauncherDir | Out-Null
        Write-Host 'New ngrok window started. Confirm Session Status = online.'
    }
    Write-Host ''
    Write-Host 'Check server window: Run enabled=False, Bridge reads=True, Bridge operations=True.'
    Write-Host 'Refresh the connector tool list if needed; stage1 adds 6 tools (normally 20 tools total).'
    Write-Host 'Expected capability: geometry_api=geometry-stage1-2. This launcher does NOT verify DLL loading or geometry.'
    Write-Host 'Keep service windows open. Stop each service using Ctrl+C. No keys, models or API DLLs were changed.'
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'No existing process was stopped. Inspect any server window already opened.'
    exit 1
}
