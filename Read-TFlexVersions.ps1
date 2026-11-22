param([Parameter(Mandatory=$true)][string]$ProgramDir)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$Names = @("TFlexCad.exe", "TFlexAPI.dll", "TFlexAPI3D.dll",
           "TFlexAPIData.dll", "TFlexCommandAPI.dll")
$Rows = @(
    foreach ($Name in $Names) {
        $Path = Join-Path $ProgramDir $Name
        $Row = [ordered]@{
            name = $Name; path = $Path; exists = $false; read_ok = $false
            file_version = $null; product_version = $null
            assembly_version = $null; assembly_error = $null
            sha256 = $null; size_bytes = $null; last_write_utc = $null
            error = $null
        }
        try {
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                throw "File not found"
            }
            $Row.exists = $true
            $Before = Get-Item -LiteralPath $Path
            $BeforeSize = $Before.Length
            $BeforeTicks = $Before.LastWriteTimeUtc.Ticks
            $Info = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Before.FullName)
            $Row.file_version = $Info.FileVersion
            $Row.product_version = $Info.ProductVersion
            if ($Before.Extension -ieq ".dll") {
                try {
                    $Row.assembly_version = (
                        [System.Reflection.AssemblyName]::GetAssemblyName($Before.FullName)
                    ).Version.ToString()
                }
                catch { $Row.assembly_error = $_.Exception.Message }
            }
            $Row.sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
            $After = Get-Item -LiteralPath $Path
            $Row.size_bytes = $After.Length
            $Row.last_write_utc = $After.LastWriteTimeUtc.ToString("o")
            if ($BeforeSize -ne $After.Length -or $BeforeTicks -ne $After.LastWriteTimeUtc.Ticks) {
                throw "File changed during inspection; retry the probe"
            }
            if ([string]::IsNullOrWhiteSpace($Row.file_version)) {
                throw "FileVersion is unavailable"
            }
            if ($Row.assembly_error) { throw "Assembly metadata could not be read" }
            $Row.read_ok = $true
        }
        catch { $Row.error = $_.Exception.Message }
        [PSCustomObject]$Row
    }
)
[PSCustomObject]@{
    ok = (@($Rows | Where-Object { -not $_.read_ok }).Count -eq 0)
    checked_at_utc = [DateTime]::UtcNow.ToString("o")
    source = "live_files_on_disk"
    files = @($Rows)
    cad_started = $false
    compilation_started = $false
    assembly_code_executed = $false
} | ConvertTo-Json -Depth 6 -Compress
