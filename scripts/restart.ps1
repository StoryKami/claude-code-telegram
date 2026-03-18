param(
    [ValidateSet("start", "stop", "restart", "run")]
    [string]$Action = "restart"
)

$ProjectDir = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $ProjectDir "data"
$PidFile = Join-Path $DataDir ".bot.pid"
$LogFile = Join-Path $DataDir "bot.log"

Set-Location $ProjectDir

function Find-BotProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'python3.12.exe'" 2>$null |
        Where-Object { $_.CommandLine -match "claude-telegram-bot|src\.main" }
}

function Stop-Bot {
    Write-Host "Stopping bot..."

    # Try PID file first
    if (Test-Path $PidFile) {
        $botPid = [int](Get-Content $PidFile -Raw).Trim()
        $proc = Get-Process -Id $botPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Killing PID $botPid..."
            Stop-Process -Id $botPid -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host "Stale PID file."
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    # Also kill any remaining bot processes
    $procs = Find-BotProcesses
    foreach ($p in $procs) {
        Write-Host "Killing process $($p.ProcessId)..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }

    # Wait briefly and verify
    Start-Sleep -Seconds 1
    $remaining = Find-BotProcesses
    if ($remaining) {
        Write-Host "Warning: some processes still running, force killing..."
        foreach ($p in $remaining) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "Stopped."
}

function Start-Bot {
    if (-not (Test-Path $DataDir)) {
        New-Item -ItemType Directory -Path $DataDir | Out-Null
    }

    Write-Host "Starting bot..."

    # Unset CLAUDECODE to avoid nested session error
    $env:CLAUDECODE = $null

    $proc = Start-Process -FilePath "poetry" `
        -ArgumentList "run", "claude-telegram-bot" `
        -WorkingDirectory $ProjectDir `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError (Join-Path $DataDir "bot.err.log") `
        -WindowStyle Hidden `
        -PassThru

    $proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
    Write-Host "Bot started (PID $($proc.Id))."
    Write-Host "Log: $LogFile"
}

function Run-Bot {
    Write-Host "Running bot in foreground (Ctrl+C to stop)..."
    $env:CLAUDECODE = $null
    poetry run claude-telegram-bot
}

switch ($Action) {
    "stop"    { Stop-Bot }
    "start"   { Start-Bot }
    "restart" { Stop-Bot; Start-Bot }
    "run"     { Stop-Bot; Run-Bot }
}
