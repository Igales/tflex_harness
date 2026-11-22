param([switch]$EnableRun)
$ErrorActionPreference = "Stop"
$Repo = "C:\Users\Admin\Documents\GitHub\tflex_harness"
$Server = Join-Path $Repo "serve_mcp_full.py"
$KeyFile = Join-Path $env:APPDATA "TFlexDocs\mcp-api-key.dpapi"
foreach ($File in @($Server, $KeyFile, (Join-Path $Repo "serve_mcp_readonly.py"))) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "Required file missing: $File"
    }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not found" }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8000 is busy. Stop the old MCP server first."
}
$Names = @("TFLEX_MCP_API_KEY", "TFLEX_MCP_ALLOW_RUN", "TFLEX_HARNESS_REPO_DIR",
           "TFLEX_API_DOCS_DIR", "TFLEX_INSTALL_DIR", "TFLEX_PROGRAM_DIR")
$Previous = @{}
foreach ($Name in $Names) { $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process") }
$PreviousLocation = Get-Location
try {
    $Secure = (Get-Content -LiteralPath $KeyFile -Raw -Encoding UTF8).Trim() | ConvertTo-SecureString
    $Credential = New-Object System.Management.Automation.PSCredential("TFlexDocs", $Secure)
    $env:TFLEX_MCP_API_KEY = $Credential.GetNetworkCredential().Password
    $env:TFLEX_MCP_ALLOW_RUN = "0"
    if ($EnableRun) { $env:TFLEX_MCP_ALLOW_RUN = "1" }
    $env:TFLEX_HARNESS_REPO_DIR = $Repo
    $env:TFLEX_API_DOCS_DIR = "C:\Users\Admin\Documents\GitHub\tflex_api"
    $env:TFLEX_INSTALL_DIR = "C:\Program Files\T-FLEX CAD 17"
    $env:TFLEX_PROGRAM_DIR = "C:\Program Files\T-FLEX CAD 17\Program"
    Set-Location -LiteralPath $Repo
    Write-Host ("Run enabled: " + [bool]$EnableRun)
    Write-Host "Keep this window open. Stop with Ctrl+C."
    & uv tool run --from tflex-harness python $Server
    if ($LASTEXITCODE -ne 0) { throw "MCP server exited with code $LASTEXITCODE" }
}
finally {
    foreach ($Name in $Names) { [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], "Process") }
    Set-Location -LiteralPath $PreviousLocation.Path
    $Credential = $null
    $Secure = $null
}
