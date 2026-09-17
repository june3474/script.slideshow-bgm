# Collect copy/paste-friendly diagnostics for Slideshow-BGM bug reports.
# Usage: .\collect-bug-report.ps1 [-KodiDataDirectory <path>]

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$KodiDataDirectory
)

$ErrorActionPreference = "Stop"
$AddonId = "script.slideshow-bgm"
$MaxLogLines = 200

function Find-FirstDirectory {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Container)) {
            return $candidate
        }
    }
    return $null
}

function Find-FirstFile {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }
    return $null
}

function Read-XmlDocument {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return [xml](Get-Content -LiteralPath $Path -Raw -ErrorAction Stop)
    }
    catch {
        return $null
    }
}

function Get-KodiSetting {
    param(
        [string]$Path,
        [string]$Id
    )

    $document = Read-XmlDocument -Path $Path
    if ($null -eq $document) {
        return $null
    }
    $node = $document.SelectSingleNode("//setting[@id='$Id']")
    if ($null -eq $node) {
        return $null
    }
    if ($node.InnerText) {
        return $node.InnerText.Trim()
    }
    if ($node.Attributes["value"]) {
        return $node.Attributes["value"].Value
    }
    return $null
}

function Get-KodiLogLevel {
    param([string]$Path)

    $document = Read-XmlDocument -Path $Path
    if ($null -eq $document) {
        return $null
    }
    $node = $document.SelectSingleNode("//loglevel")
    if ($null -eq $node) {
        return $null
    }
    $value = 0
    if ([int]::TryParse($node.InnerText.Trim(), [ref]$value)) {
        return $value
    }
    return $null
}

function Get-AddonVersion {
    param([string]$Path)

    $document = Read-XmlDocument -Path $Path
    if ($null -ne $document -and $document.addon.version) {
        return [string]$document.addon.version
    }
    return $null
}

function Get-KodiVersionFromLog {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $line = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "Starting Kodi" } |
        Select-Object -First 1
    if ($line -and $line -match "Starting Kodi\s*(.+)$") {
        return $Matches[1].Trim()
    }
    return $null
}

function Get-PlatformDescription {
    $description = $null
    $architecture = $env:PROCESSOR_ARCHITECTURE
    try {
        $description = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    }
    catch {
        $description = [System.Environment]::OSVersion.VersionString
    }
    return "$description ($architecture)"
}

function Get-SafeAddonLog {
    param(
        [string]$Path,
        [string]$SourcePath
    )

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return @()
    }
    $lines = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue |
        Where-Object { $_.Contains("[slideshow-BGM]") } |
        Select-Object -Last $MaxLogLines
    return @($lines | ForEach-Object {
        $line = $_
        if ($SourcePath) {
            $line = $line.Replace($SourcePath, "<redacted>")
        }
        if ($HOME) {
            $line = $line.Replace($HOME, "~")
        }
        $line = $line -replace "(source=(?:PLAYLIST|DIRECTORY):).*?(?=\s+shuffle=)", '${1}<redacted>'
        $line = $line -replace "([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@", '${1}<credentials>@'
        $line
    })
}

if (-not $KodiDataDirectory) {
    $portableCandidates = @(
        (Join-Path $env:ProgramFiles "Kodi\portable_data")
    )
    if (${env:ProgramFiles(x86)}) {
        $portableCandidates += Join-Path ${env:ProgramFiles(x86)} "Kodi\portable_data"
    }
    $KodiDataDirectory = Find-FirstDirectory -Candidates @(
        (Join-Path $env:APPDATA "Kodi")
        (Join-Path $env:LOCALAPPDATA "Packages\XBMCFoundation.Kodi_4n2hpmxwrvr6p\LocalCache\Roaming\Kodi")
        $portableCandidates
    )
}

if (-not $KodiDataDirectory -or
    -not (Test-Path -LiteralPath $KodiDataDirectory -PathType Container)) {
    throw "Kodi data directory was not found. Pass -KodiDataDirectory explicitly."
}

$userDataDirectory = Join-Path $KodiDataDirectory "userdata"
$guiSettings = Join-Path $userDataDirectory "guisettings.xml"
$advancedSettings = Join-Path $userDataDirectory "advancedsettings.xml"
$addonSettings = Join-Path $userDataDirectory "addon_data\$AddonId\settings.xml"
$addonManifest = Join-Path $KodiDataDirectory "addons\$AddonId\addon.xml"
$logFile = Find-FirstFile -Candidates @(
    (Join-Path $KodiDataDirectory "kodi.log")
    (Join-Path $KodiDataDirectory "temp\kodi.log")
)
$oldLogFile = Find-FirstFile -Candidates @(
    (Join-Path $KodiDataDirectory "kodi.old.log")
    (Join-Path $KodiDataDirectory "temp\kodi.old.log")
)

$kodiVersion = Get-KodiVersionFromLog -Path $logFile
if (-not $kodiVersion) {
    $kodiVersion = Get-KodiVersionFromLog -Path $oldLogFile
}
if (-not $kodiVersion) {
    $kodiVersion = "Not detected"
}

$skinId = Get-KodiSetting -Path $guiSettings -Id "lookandfeel.skin"
if (-not $skinId) {
    $skinId = "Not detected"
}

$addonVersion = Get-AddonVersion -Path $addonManifest
if (-not $addonVersion -and $logFile) {
    $sessionLine = Get-Content -LiteralPath $logFile -ErrorAction SilentlyContinue |
        Where-Object { $_.Contains("[slideshow-BGM] session start: version=") } |
        Select-Object -Last 1
    if ($sessionLine -match "session start: version=([^\s]+)") {
        $addonVersion = $Matches[1]
    }
}
if (-not $addonVersion) {
    $addonVersion = "Not detected"
}

$sourceKind = Get-KodiSetting -Path $addonSettings -Id "type"
if (-not $sourceKind) {
    $sourceKind = "Not detected"
}

$playlistFormat = "Not applicable"
$sourcePath = $null
if ($sourceKind -eq "Playlist") {
    $sourcePath = Get-KodiSetting -Path $addonSettings -Id "playlist"
    $extension = if ($sourcePath) {
        [System.IO.Path]::GetExtension($sourcePath).ToLowerInvariant()
    }
    else {
        $null
    }
    if ($extension -in @(".m3u", ".pls", ".xsp")) {
        $playlistFormat = $extension
    }
    else {
        $playlistFormat = "Not detected"
    }
}
elseif ($sourceKind -eq "Directory") {
    $sourcePath = Get-KodiSetting -Path $addonSettings -Id "directory"
}

$guiDebug = Get-KodiSetting -Path $guiSettings -Id "debug.showloginfo"
$guiDebugEnabled = $null
if ($guiDebug -match "^(?i:true|1)$") { $guiDebugEnabled = $true }
elseif ($guiDebug -match "^(?i:false|0)$") { $guiDebugEnabled = $false }

$logLevel = Get-KodiLogLevel -Path $advancedSettings
$logLevelEnabled = $null
if ($null -ne $logLevel) { $logLevelEnabled = $logLevel -ge 1 }

if ($guiDebugEnabled -eq $true -or $logLevelEnabled -eq $true) {
    $debugLogging = "Enabled"
}
elseif ($null -ne $guiDebugEnabled -or $null -ne $logLevelEnabled) {
    $debugLogging = "Disabled"
}
else {
    $debugLogging = "Not detected"
}

$diagnosticLog = @(Get-SafeAddonLog -Path $logFile -SourcePath $sourcePath)
$diagnosticLogName = if ($diagnosticLog.Count -gt 0) { "kodi.log" } else { $null }
if ($diagnosticLog.Count -eq 0) {
    $diagnosticLog = @(Get-SafeAddonLog -Path $oldLogFile -SourcePath $sourcePath)
    if ($diagnosticLog.Count -gt 0) {
        $diagnosticLogName = "kodi.old.log"
    }
}
if ($diagnosticLog.Count -eq 0) {
    $diagnosticLog = @(
        "No [slideshow-BGM] lines were found. Reproduce the problem, then run this script again."
    )
    $diagnosticLogName = "No matching log found"
}

$fence = '```'
$report = @"
<!-- Copy the report below into the GitHub bug report. -->

## Automatically collected environment

- Kodi version: $kodiVersion
- Platform: $(Get-PlatformDescription)
- Skin: $skinId
- Slideshow-BGM version: $addonVersion
- Music source kind: $sourceKind
- Playlist format: $playlistFormat
- Kodi debug logging: $debugLogging

## Slideshow-BGM log

Source: $diagnosticLogName

$($fence)text
$($diagnosticLog -join [Environment]::NewLine)
$fence

**Review the output for personal information before posting it publicly.**
"@

$report
