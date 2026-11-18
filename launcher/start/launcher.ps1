<#
.SYNOPSIS
  Advanced Randomizer: one window, one button, no console.

.DESCRIPTION
  This file draws the window and nothing else.  Every decision (paths, hashes,
  ordering, refusals) lives in launcher\start\engine.py, which is testable off
  Windows; this script only collects clicks, runs the engine and shows its log.

  Windows PowerShell 5.1 and WinForms are part of Windows itself, so the
  launcher needs nothing installed before it can open - which matters, because
  it is the thing that installs everything else.

  The engine's output goes through a log FILE, not a pipe: a blocking
  ReadLine() on a pipe freezes this window for as long as Blender or Godot
  stay quiet, and a launcher that looks hung is worse than a slow one.
#>
[CmdletBinding()]
param(
    [string]$EnginePython = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[System.Windows.Forms.Application]::EnableVisualStyles()

# Russian text out of Python must survive a redirected stream.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$engine = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "engine.py"))
$bootstrapRoot = Join-Path $env:LOCALAPPDATA "AdvancedRandomizer\bootstrap"
$settingsPath = Join-Path $env:APPDATA "AdvancedRandomizer\settings.json"

if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
    [System.Windows.Forms.MessageBox]::Show("Не найден engine.py рядом с лаунчером:`n$engine", "Advanced Randomizer") | Out-Null
    exit 1
}

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
$ink = [System.Drawing.Color]::FromArgb(238, 236, 232)
$muted = [System.Drawing.Color]::FromArgb(158, 154, 148)
$accent = [System.Drawing.Color]::FromArgb(212, 172, 96)
$good = [System.Drawing.Color]::FromArgb(126, 190, 140)
$bad = [System.Drawing.Color]::FromArgb(206, 108, 108)
$line = [System.Drawing.Color]::FromArgb(58, 56, 53)
$fieldBg = [System.Drawing.Color]::FromArgb(36, 34, 32)

$uiFont = New-Object System.Drawing.Font("Segoe UI", 10)
$titleFont = New-Object System.Drawing.Font("Segoe UI Semibold", 18)
$smallFont = New-Object System.Drawing.Font("Segoe UI", 9)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function New-Label {
    param([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height, $Font, $Color)
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point($X, $Y)
    $label.Size = New-Object System.Drawing.Size($Width, $Height)
    $label.Font = if ($Font) { $Font } else { $uiFont }
    $label.ForeColor = if ($Color) { $Color } else { $ink }
    $label.BackColor = [System.Drawing.Color]::Transparent
    return $label
}

function New-Field {
    param([string]$Tag, [int]$X, [int]$Y, [int]$Width)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Location = New-Object System.Drawing.Point($X, $Y)
    $box.Size = New-Object System.Drawing.Size($Width, 26)
    $box.BackColor = $fieldBg
    $box.ForeColor = $ink
    $box.BorderStyle = "FixedSingle"
    $box.Tag = $Tag
    return $box
}

function New-Button {
    param([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height, $Font, $BackColor, $ForeColor)
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Location = New-Object System.Drawing.Point($X, $Y)
    $button.Size = New-Object System.Drawing.Size($Width, $Height)
    $button.FlatStyle = "Flat"
    $button.FlatAppearance.BorderColor = $line
    $button.FlatAppearance.BorderSize = 1
    $button.BackColor = if ($BackColor) { $BackColor } else { [System.Drawing.Color]::FromArgb(46, 44, 41) }
    $button.ForeColor = if ($ForeColor) { $ForeColor } else { $ink }
    $button.Font = if ($Font) { $Font } else { $uiFont }
    return $button
}

function Get-PinnedPythonPath {
    param([string]$Root)
    return (Join-Path $Root "tools\cpython-3.12.13\python.exe")
}

function Ensure-BootstrapPython {
    # The launcher's own interpreter for running the engine before an install
    # root exists.  It is the same pinned build the importer demands, so the
    # engine never runs on a Python that would later be refused.
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($EnginePython)) { $candidates += $EnginePython }
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $document = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            if ($document.installRoot) {
                $candidates += (Get-PinnedPythonPath -Root $document.installRoot)
            }
        } catch { }
    }
    $candidates += (Get-PinnedPythonPath -Root $bootstrapRoot)

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }

    $script = Join-Path $PSScriptRoot "bootstrap-python.ps1"
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $script -Destination $bootstrapRoot -Quiet | Out-Null
    $installed = Get-PinnedPythonPath -Root $bootstrapRoot
    if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) {
        throw "Не удалось подготовить Python для лаунчера: $installed"
    }
    return $installed
}

function Quote-Argument {
    param([string]$Value)
    if ($Value -match '[\s"]') { return '"' + $Value.Replace('"', '\"') + '"' }
    return $Value
}

# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Advanced Randomizer"
$form.Size = New-Object System.Drawing.Size(940, 700)
$form.MinimumSize = New-Object System.Drawing.Size(860, 640)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(20, 19, 18)
$form.ForeColor = $ink
$form.Font = $uiFont

$form.Controls.Add((New-Label -Text "Advanced Randomizer" -X 28 -Y 18 -Width 520 -Height 40 -Font $titleFont))
$form.Controls.Add((New-Label -Text "Случайные юниты, палантир, карты драфта и волны хаоса поверх OpenBFME." -X 30 -Y 62 -Width 860 -Height 22 -Font $smallFont -Color $muted))

$rows = @(
    @{ Key = "install-root"; Title = "Папка лаунчера"; Hint = "движок, контент и кэш конвертации"; Y = 100 },
    @{ Key = "bfme2-install"; Title = "BFME2 1.06"; Hint = "ваша папка игры; файлы не копируются"; Y = 160 },
    @{ Key = "rotwk-install"; Title = "RotWK 2.01"; Hint = "необязательно; нужно для полного контента RotWK"; Y = 220 },
    @{ Key = "patch202-root"; Title = "Патч 2.02"; Hint = "необязательно; папка с __patch202.big (≈1,26 ГБ)"; Y = 280 }
)

foreach ($row in $rows) {
    $form.Controls.Add((New-Label -Text $row.Title -X 30 -Y $row.Y -Width 320 -Height 22))
    $form.Controls.Add((New-Label -Text $row.Hint -X 30 -Y ($row.Y + 20) -Width 320 -Height 18 -Font $smallFont -Color $muted))
    $form.Controls.Add((New-Field -Tag $row.Key -X 360 -Y ($row.Y + 16) -Width 430))

    $browse = New-Button -Text "Обзор…" -X 800 -Y ($row.Y + 14) -Width 100 -Height 30
    $tag = $row.Key
    $browse.Add_Click({
        param($sender, $eventArgs)
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Выберите папку"
        $dialog.ShowNewFolderButton = $true
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            foreach ($control in $form.Controls) {
                if ($control -is [System.Windows.Forms.TextBox] -and $control.Tag -eq $tag) {
                    $control.Text = $dialog.SelectedPath
                }
            }
        }
    }.GetNewClosure())
    $form.Controls.Add($browse)
}

$form.Controls.Add((New-Label -Text "Seed" -X 30 -Y 340 -Width 320 -Height 22))
$form.Controls.Add((New-Label -Text "1–32 латинские буквы или цифры; у всех игроков одинаковый" -X 30 -Y 360 -Width 320 -Height 18 -Font $smallFont -Color $muted))
$seedBox = New-Field -Tag "seed" -X 360 -Y 352 -Width 220
$form.Controls.Add($seedBox)

$reseed = New-Button -Text "Другой seed" -X 592 -Y 350 -Width 120 -Height 30
$reseed.Add_Click({
    param($sender, $eventArgs)
    $alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $bytes = New-Object 'byte[]' 12
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($bytes)
    $text = ""
    foreach ($byte in $bytes) { $text += $alphabet[$byte % $alphabet.Length] }
    $seedBox.Text = $text
})
$form.Controls.Add($reseed)

$statusLabel = New-Label -Text "Проверяю…" -X 30 -Y 396 -Width 870 -Height 40 -Font $smallFont -Color $muted
$statusLabel.AutoSize = $false
$form.Controls.Add($statusLabel)

$play = New-Button -Text "ИГРАТЬ" -X 30 -Y 440 -Width 250 -Height 56 -Font (New-Object System.Drawing.Font("Segoe UI Semibold", 15)) -BackColor $accent -ForeColor ([System.Drawing.Color]::FromArgb(24, 22, 18))
$play.FlatAppearance.BorderSize = 0
$play.Enabled = $false
$form.Controls.Add($play)

$setup = New-Button -Text "Настроить всё за меня" -X 296 -Y 440 -Width 250 -Height 56
$form.Controls.Add($setup)

$quit = New-Button -Text "Выход" -X 760 -Y 440 -Width 140 -Height 56
$form.Controls.Add($quit)

$full = New-Button -Text "Полный контент RotWK (2.02)" -X 30 -Y 504 -Width 870 -Height 32
$full.Visible = $false
$form.Controls.Add($full)

$log = New-Object System.Windows.Forms.TextBox
$log.Location = New-Object System.Drawing.Point(30, 544)
$log.Size = New-Object System.Drawing.Size(870, 92)
$log.Multiline = $true
$log.ScrollBars = "Vertical"
$log.ReadOnly = $true
$log.BackColor = [System.Drawing.Color]::FromArgb(16, 15, 14)
$log.ForeColor = $muted
$log.BorderStyle = "FixedSingle"
$log.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$log.Anchor = "Top,Bottom,Left,Right"
$form.Controls.Add($log)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(30, 648)
$progress.Size = New-Object System.Drawing.Size(870, 8)
$progress.Style = "Marquee"
$progress.MarqueeAnimationSpeed = 30
$progress.Visible = $false
$progress.Anchor = "Bottom,Left,Right"
$form.Controls.Add($progress)

# ---------------------------------------------------------------------------
# Log and engine plumbing
# ---------------------------------------------------------------------------
function Write-Log {
    param([string]$Text)
    $log.AppendText($Text + [Environment]::NewLine)
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

function Read-NewLogLines {
    param($Reader, [string]$Trim = $false)
    if ($null -eq $Reader) { return }
    while ($null -ne ($line = $Reader.ReadLine())) {
        if ($line.Trim().Length -gt 0) { Write-Log $line }
    }
}

function Invoke-Engine {
    param([string[]]$Arguments)

    $play.Enabled = $false
    $setup.Enabled = $false
    $progress.Visible = $true
    $logFile = Join-Path ([IO.Path]::GetTempPath()) ("advanced-randomizer-" + [Guid]::NewGuid().ToString("N") + ".log")
    $errFile = "$logFile.err"
    $stream = $null
    $reader = $null

    try {
        $python = Ensure-BootstrapPython
        $all = @($python, $engine) + $Arguments
        $commandLine = ($all | ForEach-Object { Quote-Argument $_ }) -join " "
        Write-Log "> $commandLine"

        $process = Start-Process -FilePath "`"$python`"" -ArgumentList (($all[1..($all.Length - 1)] | ForEach-Object { Quote-Argument $_ }) -join " ") `
            -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $logFile -RedirectStandardError $errFile

        $stream = New-Object System.IO.FileStream($logFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)

        while (-not $process.HasExited) {
            Start-Sleep -Milliseconds 150
            [System.Windows.Forms.Application]::DoEvents()
            Read-NewLogLines -Reader $reader
        }
        $process.WaitForExit()
        Read-NewLogLines -Reader $reader

        if (Test-Path -LiteralPath $errFile -PathType Leaf) {
            $errors = Get-Content -LiteralPath $errFile -Encoding UTF8 -ErrorAction SilentlyContinue
            foreach ($line in $errors) {
                if ($line -and $line.Trim().Length -gt 0) { Write-Log "! $line" }
            }
        }
        return $process.ExitCode
    } finally {
        if ($reader) { $reader.Dispose() }
        if ($stream) { $stream.Dispose() }
        Remove-Item -LiteralPath $logFile, $errFile -Force -ErrorAction SilentlyContinue
        $progress.Visible = $false
        $setup.Enabled = $true
    }
}

function Read-Status {
    $python = Ensure-BootstrapPython
    $logFile = Join-Path ([IO.Path]::GetTempPath()) ("advanced-randomizer-status-" + [Guid]::NewGuid().ToString("N") + ".json")
    try {
        Start-Process -FilePath "`"$python`"" -ArgumentList ((Quote-Argument $engine), "status") `
            -WorkingDirectory $repoRoot -WindowStyle Hidden -Wait `
            -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" | Out-Null
        if (-not (Test-Path -LiteralPath $logFile -PathType Leaf)) { return $null }
        $raw = Get-Content -LiteralPath $logFile -Raw -Encoding UTF8
        if (-not $raw) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    } finally {
        Remove-Item -LiteralPath $logFile, "$logFile.err" -Force -ErrorAction SilentlyContinue
    }
}

function Set-FieldText {
    param([string]$Tag, [string]$Value)
    foreach ($control in $form.Controls) {
        if ($control -is [System.Windows.Forms.TextBox] -and $control.Tag -eq $Tag) {
            $control.Text = $Value
        }
    }
}

function Get-FieldText {
    param([string]$Tag)
    foreach ($control in $form.Controls) {
        if ($control -is [System.Windows.Forms.TextBox] -and $control.Tag -eq $Tag) {
            return $control.Text.Trim()
        }
    }
    return ""
}

function Refresh-Status {
    $info = Read-Status
    if ($null -eq $info) {
        $statusLabel.Text = "Не удалось прочитать настройки лаунчера. Подробности — в логе."
        $statusLabel.ForeColor = $bad
        $play.Enabled = $false
        return
    }

    if (-not (Get-FieldText -Tag "install-root") -and $info.defaultInstallRoot) {
        Set-FieldText -Tag "install-root" -Value $info.defaultInstallRoot
    }
    if (-not (Get-FieldText -Tag "bfme2-install") -and $info.detectedBfme2) {
        Set-FieldText -Tag "bfme2-install" -Value $info.detectedBfme2
    }
    if (-not (Get-FieldText -Tag "rotwk-install") -and $info.detectedRotwk) {
        Set-FieldText -Tag "rotwk-install" -Value $info.detectedRotwk
    }
    if (-not (Get-FieldText -Tag "patch202-root") -and $info.detectedPatch202) {
        Set-FieldText -Tag "patch202-root" -Value $info.detectedPatch202
    }
    if (-not (Get-FieldText -Tag "seed") -and $info.seed) {
        Set-FieldText -Tag "seed" -Value $info.seed
    }

    $full.Visible = [bool]$info.canFullRotwk

    if ($info.ready) {
        $statusLabel.Text = "Готово к игре. Seed: $($info.seed). Пак: $($info.activePack)"
        $statusLabel.ForeColor = $good
        $play.Enabled = $true
        $setup.Text = "Пересобрать контент"
    } else {
        $notes = @($info.notes) -join " "
        $statusLabel.Text = if ($notes) { $notes } else { "Нужна первичная настройка." }
        $statusLabel.ForeColor = $muted
        $play.Enabled = $false
        $setup.Text = "Настроить всё за меня"
    }
}

function Save-Fields {
    $arguments = @("set")
    $map = @{
        "install-root"   = "--install-root"
        "bfme2-install"  = "--bfme2-install"
        "rotwk-install"  = "--rotwk-install"
        "patch202-root"  = "--patch202-root"
        "seed"           = "--seed"
    }
    foreach ($tag in $map.Keys) {
        $value = Get-FieldText -Tag $tag
        if ($value) { $arguments += @($map[$tag], $value) }
    }
    return (Invoke-Engine -Arguments $arguments)
}

$quit.Add_Click({ $form.Close() })

$play.Add_Click({
    if ((Save-Fields) -ne 0) { Refresh-Status; return }
    $code = Invoke-Engine -Arguments @("launch")
    if ($code -ne 0) { Write-Log "Игра не запустилась (код $code)." }
    Refresh-Status
})

$setup.Add_Click({
    if ((Save-Fields) -ne 0) { Refresh-Status; return }
    $code = Invoke-Engine -Arguments @("autopilot")
    if ($code -eq 0) {
        Write-Log "Готово."
    } else {
        Write-Log "Настройка остановилась (код $code). Исправьте причину выше и нажмите кнопку снова."
    }
    Refresh-Status
})

$full.Add_Click({
    if ((Save-Fields) -ne 0) { Refresh-Status; return }
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "Полная конвертация RotWK (7 фракций и 10 карт) занимает от 40 минут до нескольких часов и требует около 20 ГБ свободного места. Продолжить?",
        "Advanced Randomizer",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    $code = Invoke-Engine -Arguments @("full")
    if ($code -eq 0) {
        Write-Log "Полный контент RotWK готов."
    } else {
        Write-Log "Полная конвертация остановилась (код $code). Причина — в логе выше."
    }
    Refresh-Status
})

$form.Add_Shown({
    Write-Log "Advanced Randomizer. Это окно можно свернуть: процесс продолжится."
    Refresh-Status
})

try {
    [void]$form.ShowDialog()
} catch {
    $message = $_.Exception.Message
    [System.Windows.Forms.MessageBox]::Show("Лаунчер столкнулся с ошибкой:`n$message", "Advanced Randomizer") | Out-Null
    exit 1
}
