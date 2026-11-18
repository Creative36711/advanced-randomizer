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

# ---------------------------------------------------------------------------
# Crash log FIRST: until this file exists, nothing below can report anything,
# and a windowed process has no console to print to.
# ---------------------------------------------------------------------------
$stateDir = Join-Path $env:LOCALAPPDATA "AdvancedRandomizer"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$script:crashLog = Join-Path $stateDir "launcher.log"
$script:readyFile = Join-Path $stateDir "launcher-ready"

# StrictMode Latest refuses to READ an undefined variable, so every flag this
# script tests must exist before the first test.  "$script:busy" was added
# without this line, and Refresh-Status died on its first read: the window
# opened, then said nothing at all about the install.
$script:busy = $false

try {
    Remove-Item -LiteralPath $script:crashLog -Force -ErrorAction SilentlyContinue
} catch { }

function Write-CrashLog {
    param([string]$Text)
    try {
        # UTF-8 with BOM so Notepad and `type` both show Cyrillic correctly.
        $encoding = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::AppendAllText($script:crashLog, $Text + [Environment]::NewLine, $encoding)
    } catch { }
}

# WinForms and System.Drawing are ASSEMBLIES, not namespaces: on Windows
# PowerShell 5.1 `[System.Windows.Forms.Form]` and `[System.Drawing.Color]`
# do not resolve until they are loaded.  Loading them was missing here, so the
# very first form line threw and the window never appeared.
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
} catch {
    Write-CrashLog "Не удалось загрузить System.Windows.Forms/System.Drawing: $($_.Exception.Message)"
    exit 1
}

[System.Windows.Forms.Application]::EnableVisualStyles()

# Russian text out of Python must survive a redirected stream.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$engine = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "engine.py"))
# The launcher's own Python goes INSIDE the install folder the player chose, so
# the whole game stays in one place and can be moved or deleted as a unit.  It
# is a downloaded interpreter, never an installation into Windows: no PATH
# entry, no registry key, no system Python touched.
$settingsPath = Join-Path $env:APPDATA "AdvancedRandomizer\settings.json"

function Get-StateRoot {
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $document = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            if ($document.installRoot) { return $document.installRoot }
        } catch { }
    }
    return (Join-Path $env:LOCALAPPDATA "AdvancedRandomizer")
}

$bootstrapRoot = Join-Path (Get-StateRoot) "launcher-python"

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

function Get-PythonVersion {
    param([string]$Exe)
    $result = Invoke-Quiet -Exe $Exe -CommandArguments @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    if ($result.Code -ne 0) { return "" }
    return $result.Stdout
}

function Invoke-Quiet {
    # Runs a command line with output to temp files and returns its exit code,
    # the stdout text and the stderr text.  Never throws.
    param([string]$Exe, [string[]]$CommandArguments)
    $handle = [Guid]::NewGuid().ToString("N")
    $out = Join-Path ([IO.Path]::GetTempPath()) "$handle.txt"
    $err = Join-Path ([IO.Path]::GetTempPath()) "$handle.err"
    try {
        $arguments = @{
            FilePath = $Exe
            # Same quoting rule as Invoke-Engine: python.exe lives under a path
            # that can contain spaces.
            ArgumentList = (Join-Arguments $CommandArguments)
            WindowStyle = "Hidden"
            Wait = $true
            RedirectStandardOutput = $out
            RedirectStandardError = $err
        }
        Start-Process @arguments | Out-Null
        $stdout = if (Test-Path -LiteralPath $out -PathType Leaf) { (Get-Content -LiteralPath $out -Raw) } else { "" }
        $stderr = if (Test-Path -LiteralPath $err -PathType Leaf) { (Get-Content -LiteralPath $err -Raw) } else { "" }
        return @{ Code = 0; Stdout = ([string]$stdout).Trim(); Stderr = ([string]$stderr).Trim() }
    } catch {
        return @{ Code = -1; Stdout = ""; Stderr = $_.Exception.Message }
    } finally {
        [void](Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue)
    }
}

function Test-InterpreterWorks {
    # The engine's CLI prints `{}`-parseable JSON for `status`; if `--help`
    # exits 0 the interpreter is usable, whatever its exact version.
    param([string]$Exe)
    if ([string]::IsNullOrWhiteSpace($Exe)) { return $false }
    $result = Invoke-Quiet -Exe $Exe -CommandArguments @("-E", "-s", "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)")
    return ($result.Code -eq 0)
}

function Ensure-BootstrapPython {
    # The launcher's own interpreter for running the engine before an install
    # root exists.  It is the same pinned build the importer demands, so the
    # engine never runs on a Python that would later be refused.
    # Setting PYTHONHOME or PYTHONPATH globally (some game mods do) breaks any
    # interpreter the launcher inherits, so both are cleared for the engine.
    [void](Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue)
    [void](Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue)

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

    # Any interpreter the engine can actually run on, before downloading one.
    # The engine is standard-library only on purpose, so pinning the launcher
    # itself to one exact build would buy nothing but a failure mode: the
    # download host is reachable for some players and not for others.
    $candidates = @()
    $system = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $system) { $candidates += $system.Source }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) { $candidates += $py.Source }
    foreach ($candidate in $candidates) {
        if (Test-InterpreterWorks -Exe $candidate) { return $candidate }
    }

    # Last resort: fetch the pinned build.  When this fails the message names
    # the URL and the folder, so the file can be brought by hand.
    [void](Write-Log "Python 3.9+ не найден. Скачиваю закреплённую сборку 3.12.13…")

    $script = Join-Path $PSScriptRoot "bootstrap-python.ps1"
    # The interpreter is installed INTO the launcher folder, not next to it:
    # a player who moves or copies that one folder keeps a working launcher,
    # and nothing is written outside it.
    $output = & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $script -Destination $bootstrapRoot -Quiet 2>&1
    foreach ($line in @($output)) {
        if ($line) { [void](Write-Log ([string]$line)) }
    }
    $installed = Get-PinnedPythonPath -Root $bootstrapRoot
    if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) {
        $message = "Не удалось получить Python, на котором работает лаунчер."
        [void](Write-Log $message)
        [void](Write-Log "Можно поставить Python 3.12 вручную с https://www.python.org/downloads/ и запустить лаунчер снова —")
        [void](Write-Log "он возьмёт системный Python, если тот 3.9 или новее.")
        throw $message
    }
    return $installed
}


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
try {
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
        # Start where the field already points, so re-picking a folder is one
        # click instead of navigating from "This PC" every time.
        $current = Get-FieldText -Tag $tag
        if ($current -and (Test-Path -LiteralPath $current)) { $dialog.SelectedPath = $current }
        $dialog.Description = "Выберите папку"
        $dialog.ShowNewFolderButton = $true
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            # Captured directly in the closure: a `param($tag)` would shadow the
            # outer variable and always be empty.
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
    # [void] everywhere, for the reason in Read-NewLogLines: AppendText returns
    # nothing useful, but ScrollToCaret and DoEvents can put values on the
    # pipeline, and a caller that captures this function's output would then be
    # capturing the wrong thing.
    param([string]$Text)
    [void]$log.AppendText($Text + [Environment]::NewLine)
    $log.SelectionStart = $log.TextLength
    [void]$log.ScrollToCaret()
    [void][System.Windows.Forms.Application]::DoEvents()
}

function Read-NewLogLines {
    # [void] on everything: this function is called inside Invoke-Engine, whose
    # return value is the exit code. A leaked string would turn that code into
    # an array, and `@(0) -ne 0` is true - every successful step would look
    # like a failure, which is exactly what happened.
    param($Reader)
    if ($null -eq $Reader) { return }
    while ($null -ne ($line = $Reader.ReadLine())) {
        if ($line.Trim().Length -gt 0) { [void](Write-Log $line) }
    }
}

function Quote-Argument {
    # Start-Process -ArgumentList joins an array with single spaces and adds NO
    # quoting, so a path such as C:\Users\Creative\Advanced Randomizer becomes
    # two arguments ("unrecognized arguments: Randomizer" was exactly this).
    # ProcessStartInfo.ArgumentList is not available in .NET Framework 4.8
    # either, so the quoting has to be done here, following the same rules
    # CommandLineToArgvW uses to split it again.
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]'\') {
            $backslashes += 1
            continue
        }
        if ($character -eq [char]'"') {
            # 2n+1 backslashes then a quote -> n backslashes and a literal quote.
            [void]$builder.Append([string]::new([char]'\', 2 * $backslashes + 1))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append([string]::new([char]'\', $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append([string]::new([char]'\', 2 * $backslashes))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Join-Arguments {
    param([string[]]$Values)
    return (($Values | ForEach-Object { Quote-Argument $_ }) -join ' ')
}

function Invoke-Engine {
    param([string[]]$Arguments)

    # Re-entrancy guard: DoEvents inside the wait loop can deliver another
    # click, and two engines writing the same settings would corrupt them.
    if ($script:busy) {
        [void](Write-Log "Ещё идёт предыдущий шаг — дождитесь его окончания.")
        return 1
    }
    $script:busy = $true
    $play.Enabled = $false
    $setup.Enabled = $false
    $progress.Visible = $true
    $logFile = Join-Path ([IO.Path]::GetTempPath()) ("advanced-randomizer-" + [Guid]::NewGuid().ToString("N") + ".log")
    $errFile = "$logFile.err"
    $stream = $null
    $reader = $null

    try {
        $python = Ensure-BootstrapPython
        $argumentLine = Join-Arguments (@($engine) + $Arguments)
        [void](Write-Log ("> " + $python + " " + $argumentLine))

        # -ArgumentList takes ONE string and joins arrays without quoting, so the
        # string is built here with explicit quoting instead.
        $startArgs = @{
            FilePath = $python
            ArgumentList = $argumentLine
            WorkingDirectory = $repoRoot
            WindowStyle = "Hidden"
            PassThru = $true
            RedirectStandardOutput = $logFile
            RedirectStandardError = $errFile
        }
        $process = Start-Process @startArgs

        # The child may not have created its log yet; wait for it instead of
        # letting FileMode::Open throw while the console window is hidden.
        $waited = 0
        while (-not (Test-Path -LiteralPath $logFile -PathType Leaf) -and -not $process.HasExited -and $waited -lt 100) {
            Start-Sleep -Milliseconds 100
            [System.Windows.Forms.Application]::DoEvents()
            $waited += 1
        }
        if (-not (Test-Path -LiteralPath $logFile -PathType Leaf)) { New-Item -ItemType File -Path $logFile -Force | Out-Null }

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
        return [int]$process.ExitCode
    } catch {
        [void](Write-Log ("Ошибка: " + $_.Exception.Message))
        Write-CrashLog ("Ошибка движка: " + $_.Exception.Message)
        Write-CrashLog ($_.ScriptStackTrace)
        return 1
    } finally {
        if ($reader) { $reader.Dispose() }
        if ($stream) { $stream.Dispose() }
        Remove-Item -LiteralPath $logFile, $errFile -Force -ErrorAction SilentlyContinue
        $progress.Visible = $false
        $script:busy = $false
        $setup.Enabled = $true
        $play.Enabled = $true
    }
}

function Read-Status {
    try {
        $python = Ensure-BootstrapPython
    } catch {
        [void](Write-Log ("Нет Python для лаунчера: " + $_.Exception.Message))
        return $null
    }
    $logFile = Join-Path ([IO.Path]::GetTempPath()) ("advanced-randomizer-status-" + [Guid]::NewGuid().ToString("N") + ".json")
    try {
        # Ask about the folders ON SCREEN, not only the saved ones: the status
        # line said "install folder not chosen" while the field showed a path.
        $argumentList = @($engine, "status")
        $fieldMap = @(
            @("install-root", "--install-root"),
            @("bfme2-install", "--bfme2-install"),
            @("rotwk-install", "--rotwk-install"),
            @("patch202-root", "--patch202-root")
        )
        foreach ($field in $fieldMap) {
            $value = Get-FieldText -Tag $field[0]
            if ($value) { $argumentList += @($field[1], $value) }
        }
        $statusArgs = @{
            FilePath = $python
            ArgumentList = (Join-Arguments $argumentList)
            WorkingDirectory = $repoRoot
            WindowStyle = "Hidden"
            Wait = $true
            RedirectStandardOutput = $logFile
            RedirectStandardError = "$logFile.err"
        }
        Start-Process @statusArgs | Out-Null
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

    $full.Visible = $info.canFullRotwk

    # PLAY is clickable in every state.  A disabled button with no explanation
    # is exactly what the player reported as "does not react"; when the install
    # is not ready yet the same button prepares everything and then launches.
    if ($info.ready) {
        $statusLabel.Text = "Готово к игре. Seed: $($info.seed). Пак: $($info.activePack)"
        $statusLabel.ForeColor = $good
        $play.Text = "ИГРАТЬ"
        $setup.Text = "Пересобрать контент"
    } else {
        $notes = @($info.notes) -join " "
        if (-not $notes) { $notes = "Игра ещё не собрана." }
        $statusLabel.Text = "$notes Нажмите ИГРАТЬ — лаунчер подготовит всё сам."
        $statusLabel.ForeColor = $muted
        $play.Text = "ИГРАТЬ (подготовить и запустить)"
        $setup.Text = "Настроить всё за меня"
    }
    $play.Enabled = -not $script:busy
    $setup.Enabled = -not $script:busy
}

function Get-ExitCode {
    # Defensive: take the LAST value a function emitted and coerce it to a
    # number. PowerShell turns "a string and a number" into an array, and
    # @(0) -ne 0 is true, so a leaked log line used to make every successful
    # step look like a failure and the autopilot never started.
    param($Value)
    if ($null -eq $Value) { return 1 }
    if ($Value -is [array]) {
        if ($Value.Count -eq 0) { return 1 }
        $Value = $Value[-1]
    }
    $number = 0
    if ([int]::TryParse([string]$Value, [ref]$number)) { return $number }
    return 1
}

function Save-Fields {
    $arguments = @("set")
    # An ordered array of pairs, not a hashtable: in PowerShell 5.1 neither
    # `.Keys` nor `.Count` on a hashtable survives StrictMode.
    $fields = @(
        @("install-root", "--install-root"),
        @("bfme2-install", "--bfme2-install"),
        @("rotwk-install", "--rotwk-install"),
        @("patch202-root", "--patch202-root"),
        @("seed", "--seed")
    )
    foreach ($field in $fields) {
        $value = Get-FieldText -Tag $field[0]
        if ($value) { $arguments += @($field[1], $value) }
    }
    return (Get-ExitCode (Invoke-Engine -Arguments $arguments))
}

$quit.Add_Click({ $form.Close() })

$play.Add_Click({
    if (-not (Get-FieldText -Tag "install-root")) {
        [System.Windows.Forms.MessageBox]::Show(
            "Сначала выберите папку лаунчера — в неё будут скачаны движок и контент.",
            "Advanced Randomizer") | Out-Null
        return
    }
    # A failed save is reported, not swallowed: silently returning is what made
    # four "set" runs in a row look like nothing happening.
    if ((Get-ExitCode (Save-Fields)) -ne 0) {
        [void](Write-Log "Не удалось сохранить настройки. Причина — в логе выше.")
        Refresh-Status
        return
    }
    # One button for the player: prepare whatever is missing, then launch.
    # Before this, PLAY silently refused until a separate setup run finished,
    # and the refusal was a disabled button - invisible.
    $code = Get-ExitCode (Invoke-Engine -Arguments @("autopilot"))
    if ($code -ne 0) {
        Write-Log "Подготовка остановилась (код $code). Причина — в логе выше."
    }
    Refresh-Status
})

$setup.Add_Click({
    if ((Get-ExitCode (Save-Fields)) -ne 0) { Refresh-Status; return }
    $code = Get-ExitCode (Invoke-Engine -Arguments @("autopilot"))
    if ($code -eq 0) {
        Write-Log "Готово."
    } else {
        Write-Log "Настройка остановилась (код $code). Исправьте причину выше и нажмите кнопку снова."
    }
    Refresh-Status
})

$full.Add_Click({
    if ((Get-ExitCode (Save-Fields)) -ne 0) { Refresh-Status; return }
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "Полная конвертация RotWK (7 фракций и 10 карт) занимает от 40 минут до нескольких часов и требует около 20 ГБ свободного места. Продолжить?",
        "Advanced Randomizer",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    $code = Get-ExitCode (Invoke-Engine -Arguments @("full"))
    if ($code -eq 0) {
        Write-Log "Полный контент RotWK готов."
    } else {
        Write-Log "Полная конвертация остановилась (код $code). Причина — в логе выше."
    }
    Refresh-Status
})

$form.Add_Shown({
    Write-Log "Advanced Randomizer. Это окно можно свернуть: процесс продолжится."
    # The .cmd waits for this file; creating it means "the window is really up".
    try { Set-Content -LiteralPath $script:readyFile -Value "ok" -Encoding ASCII } catch { }
    try {
        Refresh-Status
    } catch {
        Write-Log ("Не удалось прочитать состояние: " + $_.Exception.Message)
    }
})

try {
    [void]$form.ShowDialog()
} catch {
    Write-CrashLog ("Ошибка окна: " + $_.Exception.Message)
    Write-CrashLog ($_.ScriptStackTrace)
    [System.Windows.Forms.MessageBox]::Show("Лаунчер столкнулся с ошибкой:`n$($_.Exception.Message)`n`nПодробности: $script:crashLog", "Advanced Randomizer") | Out-Null
    exit 1
}
} catch {
    Write-CrashLog ("Ошибка при создании окна: " + $_.Exception.Message)
    Write-CrashLog ($_.ScriptStackTrace)
    Write-CrashLog ""
    Write-CrashLog ("Строка: " + $_.InvocationInfo.PositionMessage)
    exit 1
}
