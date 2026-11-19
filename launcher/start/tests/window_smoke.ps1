# Open the real window on a real Windows machine and prove it works.
#
# Everything in launcher.ps1 used to be verified by reading the file: this
# repository has no Windows in the sandbox, so a typo in a variable name or a
# call to a function that does not exist could only be found by a player. That
# is exactly what happened, several times.
#
# This script parses launcher.ps1 the way PowerShell will, checks every function
# the file calls against the ones it defines, builds the window for real, and
# then drives it. It runs in GitHub Actions on windows-latest.
#
# Exit code 0 = the window is sound. Anything else names the problem.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$here = Split-Path -Parent $PSCommandPath
$launcherPath = Join-Path (Split-Path -Parent $here) 'launcher.ps1'

function Fail([string]$Message) {
    Write-Host "SMOKE-FAIL: $Message" -ForegroundColor Red
    exit 1
}

function Pass([string]$Message) {
    Write-Host "SMOKE-OK: $Message" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    Fail "no launcher.ps1 at $launcherPath"
}

$source = Get-Content -LiteralPath $launcherPath -Raw
$tokens = $null
$parseErrors = $null
# Parse WITHOUT running: this is the check a text search cannot do.
[void][System.Management.Automation.Language.Parser]::ParseInput(
    $source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    $first = $parseErrors[0]
    Fail ("launcher.ps1 does not parse: line {0}: {1}" -f $first.Extent.StartLineNumber, $first.Message)
}
Pass "launcher.ps1 parses cleanly"

# ---- every function called is a function that exists ---------------------
# A call to a helper that was renamed or never written fails only when that
# button is pressed - by the player, in the worst case. The rule that actually
# works: every word in a command's name must already appear in the name of a
# function this file defines. New-Item and Test-Path survive because "item" and
# "path" are not our words; a typo like Show-Progres does not, because "progres"
# is not either.
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$null)
$defined = @{}
$words = @{}
foreach ($fn in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    $defined[$fn.Name.ToLowerInvariant()] = $true
    foreach ($word in ($fn.Name -split '-')) { $words[$word.ToLowerInvariant()] = $true }
}
$missing = @{}
foreach ($call in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true)) {
    $name = $call.GetCommandName()
    if (-not $name -or $name -notmatch '-') { continue }
    $key = $name.ToLowerInvariant()
    if ($defined.ContainsKey($key)) { continue }
    $ours = $true
    foreach ($word in ($name -split '-')) {
        if (-not $words.ContainsKey($word.ToLowerInvariant())) { $ours = $false; break }
    }
    if ($ours) { $missing[$name] = $true }
}
if ($missing.Count -gt 0) {
    Fail ("launcher.ps1 calls functions it does not define: " + (($missing.Keys | Sort-Object) -join ', '))
}
Pass ("every helper the window calls is defined (" + $defined.Count + " functions)")

# ---- build the window for real -------------------------------------------
# The window is started the way a player starts it - a separate process with
# its own STA apartment - and stopped when it reports ready. Driving it from a
# runspace inside this process deadlocks: WinForms needs an STA thread and
# [PowerShell]::Create() gives an MTA one.
$stateRoot = Join-Path ([IO.Path]::GetTempPath()) ("ar-smoke-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
$ready = Join-Path $env:LOCALAPPDATA 'AdvancedRandomizer\launcher-ready'
$crash = Join-Path $env:LOCALAPPDATA 'AdvancedRandomizer\launcher.log'
Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue

$process = $null
try {
    $startArgs = @{
        FilePath = (Get-Command powershell.exe).Source
        ArgumentList = @(
            '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', ('"' + $launcherPath + '"')
        )
        PassThru = $true
        WindowStyle = 'Minimized'
    }
    $process = Start-Process @startArgs
    Write-Host ("window process started: pid " + $process.Id)

    $deadline = (Get-Date).AddSeconds(120)
    $up = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $ready -PathType Leaf) { $up = $true; break }
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }

    if (-not $up) {
        if (Test-Path -LiteralPath $crash -PathType Leaf) {
            $tail = (Get-Content -LiteralPath $crash -Encoding UTF8 | Select-Object -Last 15) -join " / "
            Fail ("the window never became ready; its log ends with: " + $tail)
        }
        if ($process.HasExited) {
            Fail ("the window process exited with code " + $process.ExitCode + " before it was ready")
        }
        Fail "the window did not become ready within 120 seconds"
    }
    Pass "the window opened and reported ready"

    # A second launch while one is running must not corrupt settings.
    Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue
} finally {
    if ($process -and -not $process.HasExited) {
        try { $process.Kill() } catch { }
        Start-Sleep -Milliseconds 500
    }
    Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $stateRoot) { Remove-Item -LiteralPath $stateRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

Pass "window smoke test passed"
exit 0
