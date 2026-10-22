param(
    [string]$DataRoot = '',
    [switch]$VerifyOnly,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$AppRoot = $PSScriptRoot
if (-not $DataRoot) { $DataRoot = Join-Path $env:LOCALAPPDATA 'UnifiedWorkbench' }
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$RuntimeRoot = Join-Path $DataRoot 'runtime-python312'
$Python = Join-Path $RuntimeRoot 'python.exe'
New-Item -ItemType Directory -Force $DataRoot | Out-Null
if (-not (Test-Path $Python)) {
    Write-Host 'Preparing the bundled Python runtime. No system Python installation is required.'
    $Archive = Join-Path $AppRoot 'bootstrap\python-3.12.10-embed-amd64.zip'
    $Hash = (Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLower()
    if ($Hash -ne '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3') { throw 'Bundled Python archive failed its integrity check.' }
    $Stage = Join-Path $DataRoot ('runtime-stage-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $Archive -DestinationPath $Stage
    if (Test-Path $RuntimeRoot) { throw 'An incomplete runtime already exists. Preserve it and inspect setup before replacing it.' }
    Move-Item -LiteralPath $Stage -Destination $RuntimeRoot
}
# Python 3.12.10's own SQLite (3.49.1) has the WAL-reset corruption bug. Replace it once
# with the bundled, fixed release; existing runtimes are updated on their next start.
$SqliteMarker = Join-Path $RuntimeRoot 'sqlite-3540100.installed'
if (-not (Test-Path $SqliteMarker)) {
    $SqliteArchive = Join-Path $AppRoot 'bootstrap\sqlite-dll-win-x64-3540100.zip'
    if ((Get-FileHash -Algorithm SHA256 $SqliteArchive).Hash.ToLower() -ne 'f436f53ad8f965af43f3817b42c99c0689e6787f6b7ace208fe38dab7ffc4971') { throw 'Bundled SQLite archive failed its integrity check.' }
    $SqliteStage = Join-Path $DataRoot ('sqlite-stage-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $SqliteArchive -DestinationPath $SqliteStage
    try {
        Copy-Item -LiteralPath (Join-Path $SqliteStage 'sqlite3.dll') -Destination (Join-Path $RuntimeRoot 'sqlite3.dll') -Force
        Set-Content -Path $SqliteMarker -Value '3.54.1'
    } catch {
        Write-Host 'SQLite could not be updated because HA is already running. It will be updated on the next start.'
    } finally {
        Remove-Item -Recurse -Force $SqliteStage
    }
}
$SitePackages = Join-Path $RuntimeRoot 'Lib\site-packages'
New-Item -ItemType Directory -Force $SitePackages | Out-Null
@('python312.zip', '.', 'Lib\site-packages', 'import site') | Set-Content -Encoding ASCII (Join-Path $RuntimeRoot 'python312._pth')
if (-not (Test-Path (Join-Path $SitePackages 'pip\__main__.py'))) {
    $PipWheel = Join-Path $AppRoot 'bootstrap\pip-25.0.1-py3-none-any.whl'
    if ((Get-FileHash -Algorithm SHA256 $PipWheel).Hash.ToLower() -ne 'c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f') { throw 'Bundled pip wheel failed its integrity check.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $AppRoot 'bootstrap\pip-25.0.1-py3-none-any.whl'), $SitePackages)
}
$Requirements = Join-Path $AppRoot 'requirements-windows.lock'
$DesiredHash = (Get-FileHash -Algorithm SHA256 $Requirements).Hash
$Marker = Join-Path $RuntimeRoot 'runtime-requirements.sha256'
$InstalledHash = if (Test-Path $Marker) { (Get-Content $Marker -Raw).Trim() } else { '' }
if ($DesiredHash -ne $InstalledHash) {
    Write-Host 'Installing pinned dependencies. This first run requires internet access.'
    & $Python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes --no-deps --find-links (Join-Path $AppRoot 'bootstrap\wheels') -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Existing user data was preserved.' }
    $Edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
    $Chrome = Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
    if (-not (Test-Path $Edge) -and -not (Test-Path $Chrome)) {
        & $Python -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed. Reopen the launcher to retry.' }
    }
    Set-Content -Path $Marker -Value $DesiredHash
}
if ($VerifyOnly) {
    & $Python (Join-Path $AppRoot 'launch.py') verify --data-dir $DataRoot
} elseif ($NoBrowser) {
    & $Python (Join-Path $AppRoot 'launch.py') serve --data-dir $DataRoot --no-browser
} else {
    & $Python (Join-Path $AppRoot 'launch.py') serve --data-dir $DataRoot
}
exit $LASTEXITCODE
