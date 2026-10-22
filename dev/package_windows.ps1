# Build the Windows ZIP, source ZIP and per-user installer, then verify them.
# Used by CI on every push and by the release workflow on version tags.
param(
    [Parameter(Mandatory = $true)][string]$Output
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force $Output | Out-Null

python (Join-Path $Root 'dev/build_release.py') $Output
if ($LASTEXITCODE -ne 0) { throw 'Release archive build failed' }
$Version = (Get-Content (Join-Path $Root '_app/release_status.json') -Raw | ConvertFrom-Json).version
$Archive = (Get-ChildItem (Join-Path $Output '*Windows.zip')).FullName

# Installer from exactly the files in the verified Windows ZIP.
$Iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $Iscc)) {
    choco install innosetup -y --no-progress | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installation failed' }
}
$Stage = Join-Path $env:RUNNER_TEMP 'ha-installer-stage'
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
Expand-Archive -LiteralPath $Archive -DestinationPath $Stage
& $Iscc "/DAppVersion=$Version" "/DSourceDir=$Stage\Hivemind_Assembly" "/DOutputDir=$Output" (Join-Path $Root 'dev/installer.iss') | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$Setup = (Get-ChildItem (Join-Path $Output '*_Setup.exe')).FullName

# Silent install, first-launch verification, upgrade over itself, uninstall:
# user data must survive every step.
$Installed = Join-Path $env:RUNNER_TEMP 'HA installed with spaces'
$Data = Join-Path $env:RUNNER_TEMP 'HA installer data'
$Log = Join-Path $env:RUNNER_TEMP 'ha-install.log'
$p = Start-Process -FilePath $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER', "/DIR=`"$Installed`"", "/LOG=`"$Log`"" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Installer exited with $($p.ExitCode)" }
foreach ($required in @('Start_Hivemind_Assembly.cmd', 'README.md', '_app\Start.ps1', '_app\package_manifest.json')) {
    if (-not (Test-Path (Join-Path $Installed $required))) { throw "Installed copy lacks $required" }
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Installed '_app\Start.ps1') -DataRoot $Data -VerifyOnly
if ($LASTEXITCODE -ne 0) { throw 'Installed first-launch verification failed' }
Set-Content -Path (Join-Path $Data 'installer-survival.txt') -Value 'keep'
$p = Start-Process -FilePath $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER', "/DIR=`"$Installed`"" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Reinstall exited with $($p.ExitCode)" }
$Uninstaller = (Get-ChildItem (Join-Path $Installed 'unins*.exe') | Select-Object -First 1).FullName
$p = Start-Process -FilePath $Uninstaller -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Uninstall exited with $($p.ExitCode)" }
# The uninstaller re-launches from a temporary copy; wait for it to finish.
for ($i = 0; $i -lt 120 -and (Test-Path (Join-Path $Installed '_app')); $i++) { Start-Sleep -Milliseconds 500 }
if (Test-Path (Join-Path $Installed '_app')) { throw 'Uninstall left application files behind' }
if (-not (Test-Path (Join-Path $Data 'installer-survival.txt'))) { throw 'Uninstall removed user data' }
if (-not (Test-Path (Join-Path $Data 'runtime-python312\python.exe'))) { throw 'Uninstall removed the user runtime' }

Get-ChildItem $Output | ForEach-Object {
    "{0}  {1}  {2}" -f $_.Name, $_.Length, (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower()
} | Out-Host
