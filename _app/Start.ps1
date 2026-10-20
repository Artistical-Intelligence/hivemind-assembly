$ErrorActionPreference = 'Stop'
$AppRoot = $PSScriptRoot
$DataRoot = Join-Path $env:LOCALAPPDATA 'UnifiedWorkbench'
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
& $Python (Join-Path $AppRoot 'launch.py') serve
exit $LASTEXITCODE
