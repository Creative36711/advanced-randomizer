<#
.SYNOPSIS
  Install the pinned Python the launcher and the importer both need.

.DESCRIPTION
  Windows PowerShell 5.1 can open a window but has no reliable Python, and the
  importer refuses anything except 3.12.13-build-20260718.  This script fetches
  exactly that archive, verifies both the archive and the extracted python.exe
  against the digests upstream already pins, and installs it under
  <Destination>\tools\cpython-3.12.13.

  Same trust shape as launcher\start\engine.py: an unverified byte is deleted,
  never installed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$version = "3.12.13"
$url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260718/cpython-3.12.13%2B20260718-x86_64-pc-windows-msvc-install_only.tar.gz"
$archiveSha256 = "56c9dd9681c4810cb8bfdec277ee2606d8ab17e678e5bc2bd138eb8098e330b6"
$pythonSha256 = "32783151cd5dcf5196ff2fa342c11fc0909436531d4deec7824cbc29fd8c1a0c"

$Destination = [IO.Path]::GetFullPath($Destination)
$toolsRoot = Join-Path $Destination "tools"
$target = Join-Path $toolsRoot "cpython-$version"
$python = Join-Path $target "python.exe"

function Write-Status {
    param([string]$Text)
    if (-not $Quiet) { Write-Host $Text }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

if (Test-Path -LiteralPath $python -PathType Leaf) {
    if ((Get-Sha256 -Path $python) -eq $pythonSha256) {
        Write-Status "Python $version уже установлен: $python"
        Write-Output $python
        exit 0
    }
    throw "Существующий python.exe не совпадает с закреплённым хешем: $python. Перенесите папку вручную и повторите."
}

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null

$archive = Join-Path ([IO.Path]::GetTempPath()) ("openbfme-python-" + [Guid]::NewGuid().ToString("N") + ".tar.gz")
$staging = Join-Path $toolsRoot (".cpython-$version.installing-" + [Guid]::NewGuid().ToString("N"))
try {
    Write-Status "Скачиваю Python $version (≈ 12 МБ)…"
    $previous = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
    } finally {
        $ProgressPreference = $previous
    }

    Write-Status "Проверяю SHA-256 архива…"
    $measured = Get-Sha256 -Path $archive
    if ($measured -ne $archiveSha256) {
        throw "SHA-256 архива Python не совпал.`n  ожидалось $archiveSha256`n  получено  $measured"
    }

    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $tar -PathType Leaf)) {
        $tar = (Get-Command tar.exe -ErrorAction Stop).Source
    }
    New-Item -ItemType Directory -Path $staging | Out-Null
    & $tar -xzf $archive -C $staging
    if ($LASTEXITCODE -ne 0) { throw "tar.exe не смог распаковать архив Python (код $LASTEXITCODE)." }

    $extracted = Join-Path $staging "python"
    $extractedExe = Join-Path $extracted "python.exe"
    if (-not (Test-Path -LiteralPath $extractedExe -PathType Leaf)) {
        throw "В архиве Python нет python\python.exe."
    }
    $exeHash = Get-Sha256 -Path $extractedExe
    if ($exeHash -ne $pythonSha256) {
        throw "python.exe из архива не совпадает с закреплённым хешем.`n  ожидалось $pythonSha256`n  получено  $exeHash"
    }

    $reported = & $extractedExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0 -or ([string]$reported).Trim() -ne $version) {
        throw "Распакованный Python не запускается или имеет другую версию: '$reported'."
    }

    Move-Item -LiteralPath $extracted -Destination $target
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python установился не туда: ожидался $python."
    }
    Write-Status "Python $version готов: $python"
    Write-Output $python
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}
