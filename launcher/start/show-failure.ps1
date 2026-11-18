<#
.SYNOPSIS
  Shown by AdvancedRandomizer.cmd when the window never opened.

.DESCRIPTION
  The window script has no console, so without this a failure is silent: the
  player sees a black box flash and nothing else.  This prints the reason the
  launcher recorded, then the exact command that shows the raw error, and waits
  so the text cannot scroll away.
#>
[CmdletBinding()]
param(
    [string]$Log = "",
    [string]$Launcher = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Show-Headline {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Yellow
}

Show-Headline "Окно лаунчера не открылось."
Write-Host ""
Write-Host "Причина, которую удалось записать:"
Write-Host ""

if ($Log -and (Test-Path -LiteralPath $Log -PathType Leaf)) {
    $lines = Get-Content -LiteralPath $Log -Encoding UTF8
    if ($lines) {
        foreach ($line in $lines) { Write-Host "  $line" }
    } else {
        Write-Host "  (файл есть, но пуст)"
    }
} else {
    Write-Host "  (файл не создан — значит, не запустился даже этот этап)"
}

Write-Host ""
if ($Log) { Write-Host "Полный лог: $Log" }

if ($Launcher) {
    Write-Host ""
    Write-Host "Чтобы увидеть ошибку целиком, выполните в этом же окне:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$Launcher`"" -ForegroundColor Cyan
}

Write-Host ""
Read-Host "Нажмите Enter, чтобы закрыть"
