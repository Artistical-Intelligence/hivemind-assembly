<#
.SYNOPSIS
Puts back the large files that Hivemind Assembly (HA) backed up as release assets.

.DESCRIPTION
GitHub refuses files over 100 MiB in a repository, so HA uploads them as assets of
this repository's release named in LARGE_FILES.json (usually "large-files"). Files of
2 GiB or more are split into numbered parts. This script reads LARGE_FILES.json,
downloads each file's assets, joins the parts back into the file at its original path
and checks its SHA-256. A file that is already there with the right SHA-256 is left
alone. Nothing else is changed. Works in Windows PowerShell 5.1 and PowerShell 7.

A private repository needs a GitHub token: -Token, the GITHUB_TOKEN or GH_TOKEN
environment variable, or a signed-in GitHub CLI (gh).

.EXAMPLE
.\restore-large-files.ps1
.\restore-large-files.ps1 -Destination 'D:\Restored copy'
.\restore-large-files.ps1 -Only 'videos/intro.mp4'
#>
param(
    [string]$Destination = $PSScriptRoot,
    [string]$Manifest = (Join-Path $PSScriptRoot 'LARGE_FILES.json'),
    [string]$Token = '',
    [string[]]$Only = @(),
    [string]$Api = $(if ($env:HA_GITHUB_API) { $env:HA_GITHUB_API } else { 'https://api.github.com' })
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

if (-not $Token) { $Token = $env:GITHUB_TOKEN }
if (-not $Token) { $Token = $env:GH_TOKEN }
if (-not $Token -and (Get-Command gh -ErrorAction SilentlyContinue)) {
    $fromGh = & gh auth token 2>$null
    if ($LASTEXITCODE -eq 0 -and $fromGh) { $Token = "$fromGh".Trim() }
}
$Api = $Api.TrimEnd('/')

function Get-Json([string]$Url) {
    $headers = @{ 'User-Agent' = 'Hivemind-Assembly-restore'; 'Accept' = 'application/vnd.github+json' }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    try {
        return Invoke-RestMethod -Uri $Url -Headers $headers -UseBasicParsing
    } catch {
        if (-not $Token) { throw "GitHub didn't allow the download. For a private repository, pass -Token or sign in with gh." }
        throw
    }
}

# GitHub answers an asset download with a redirect to the file's storage. Follow it
# without sending the token to the other host.
function Open-Download([string]$Url) {
    $withToken = [bool]$Token
    for ($hop = 0; $hop -lt 6; $hop++) {
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'Hivemind-Assembly-restore'
        $request.Accept = 'application/octet-stream'
        $request.Timeout = 120000
        $request.ReadWriteTimeout = 600000
        if ($withToken) { $request.Headers['Authorization'] = "Bearer $Token" }
        try { $response = $request.GetResponse() }
        catch [Net.WebException] {
            if ($_.Exception.Response) { $response = $_.Exception.Response } else { throw }
        }
        $code = [int]$response.StatusCode
        if ($code -ge 300 -and $code -lt 400) {
            $location = $response.Headers['Location']
            $response.Close()
            $current = New-Object Uri($Url)
            $next = New-Object Uri($current, $location)
            if ($next.Authority -ne $current.Authority) { $withToken = $false }
            $Url = $next.AbsoluteUri
            continue
        }
        if ($code -ne 200) {
            $response.Close()
            throw "GitHub answered HTTP $code for $Url"
        }
        return $response
    }
    throw "Too many redirects for $Url"
}

# .NET directly: Get-FileHash is missing when Windows PowerShell is started from PowerShell 7.
function Get-Sha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

# Where a file from the manifest goes: always inside the restore folder. A path that
# could lead anywhere else (absolute, a drive, '..', either slash on Windows, or a
# linked folder inside the restore folder) stops the restore.
$onWindows = ($PSVersionTable.PSEdition -eq 'Desktop') -or $IsWindows
function Get-Target([string]$Relative) {
    $parts = @(if ($onWindows) { $Relative -split '[\\/]' } else { $Relative -split '/' })
    $odd = @($parts | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' -or ($onWindows -and $_.Contains(':')) })
    if (-not $Relative -or $Relative.StartsWith('/') -or $Relative.StartsWith('\') -or $odd.Count -gt 0) {
        throw "Refusing an unsafe path in the manifest: $Relative"
    }
    $target = [IO.Path]::GetFullPath((Join-Path $root ($parts -join [IO.Path]::DirectorySeparatorChar)))
    if (-not $target.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing an unsafe path in the manifest: $Relative"
    }
    $folder = Split-Path -Parent $target
    while ($folder -and $folder.Length -ge $rootFull.Length) {
        if ((Test-Path -LiteralPath $folder) -and ((Get-Item -LiteralPath $folder -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing an unsafe path in the manifest (it goes through a linked folder): $Relative"
        }
        $folder = Split-Path -Parent $folder
    }
    return $target
}

$data = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$owner, $name = $data.repository.Split('/', 2)
$root = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)
$rootFull = [IO.Path]::GetFullPath($root).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$files = @($data.files | Where-Object { $Only.Count -eq 0 -or $Only -contains $_.path })
if ($files.Count -eq 0) { Write-Host 'Nothing to restore.'; exit 0 }
# Every path is checked before anything is downloaded or written.
$targets = @{}
foreach ($item in $files) { $targets[[string]$item.path] = Get-Target ([string]$item.path) }

$release = Get-Json "$Api/repos/$owner/$name/releases/tags/$([Uri]::EscapeDataString($data.release))"
$assets = @{}
$page = 1
do {
    # Invoke-RestMethod hands back a JSON list as one object; unroll it into its items.
    $batch = @((Get-Json "$Api/repos/$owner/$name/releases/$($release.id)/assets?per_page=100&page=$page") | ForEach-Object { $_ })
    foreach ($asset in $batch) { $assets[$asset.name] = $asset }
    $page++
} while ($batch.Count -eq 100)

$failed = 0
foreach ($item in $files) {
    $target = $targets[[string]$item.path]
    if ((Test-Path -LiteralPath $target -PathType Leaf) -and (Get-Item -LiteralPath $target).Length -eq $item.size -and (Get-Sha256 $target) -eq $item.sha256) {
        Write-Host "Already there: $($item.path)"
        continue
    }
    $missing = @($item.parts | Where-Object { -not $assets.ContainsKey($_.name) })
    if ($missing.Count) {
        Write-Host "Can't restore $($item.path): the release has no asset $($missing[0].name)."
        $failed++
        continue
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $partial = "$target.restoring"
    $out = [IO.File]::Open($partial, [IO.FileMode]::Create, [IO.FileAccess]::Write)
    $done = [long]0
    $buffer = New-Object byte[] 1048576
    try {
        $number = 0
        foreach ($part in $item.parts) {
            $number++
            $asset = $assets[$part.name]
            $response = Open-Download "$Api/repos/$owner/$name/releases/assets/$($asset.id)"
            try {
                $stream = $response.GetResponseStream()
                while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $out.Write($buffer, 0, $read)
                    $done += $read
                    $percent = [int][Math]::Min(100, $done * 100 / [Math]::Max(1, [long]$item.size))
                    Write-Progress -Activity "Restoring $($item.path)" -Status "Part $number of $($item.parts.Count)" -PercentComplete $percent
                }
            } finally { $response.Close() }
        }
    } finally { $out.Close() }
    Write-Progress -Activity "Restoring $($item.path)" -Completed
    if ((Get-Item -LiteralPath $partial).Length -ne $item.size -or (Get-Sha256 $partial) -ne $item.sha256) {
        Remove-Item -LiteralPath $partial
        Write-Host "Can't restore $($item.path): the downloaded file doesn't match its SHA-256."
        $failed++
        continue
    }
    Move-Item -LiteralPath $partial -Destination $target -Force
    Write-Host "Restored: $($item.path)"
}
if ($failed) {
    Write-Host "$failed file(s) couldn't be restored."
    exit 1
}
exit 0
