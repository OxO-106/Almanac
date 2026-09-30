# Start everything Almanac needs: Ollama, the Almanac server, the tray icon and
# Tailscale Serve (Almanac's private HTTPS address for the laptop), then open it.
# Safe to run again: anything already running is left as it is.
#
#   -App     used by the Start menu entry (launch-almanac.vbs): silent, opens
#            Almanac in its own window, shows a message box only on failure.
#   -NoOpen  used by the tray icon to restart a stopped server.
#   (none)   run from a console: shows progress and both addresses.

param([switch]$App, [switch]$NoOpen)
$Silent = $App -or $NoOpen

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tailscale = "C:\Program Files\Tailscale\tailscale.exe"
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$port = 8001        # Papercut uses 8000
$httpsPort = 8443   # Papercut has the tailnet's default https port

function Say($text, $color = "Gray") { if (-not $Silent) { Write-Host $text -ForegroundColor $color } }
function Fail($text) {
    if ($Silent) { (New-Object -ComObject WScript.Shell).Popup($text, 0, "Almanac", 0x10) | Out-Null }
    else { Write-Host $text -ForegroundColor Red; Read-Host "Press Enter to close" }
    exit 1
}
function Warn($text) {
    if ($Silent) { (New-Object -ComObject WScript.Shell).Popup($text, 8, "Almanac", 0x30) | Out-Null }
    else { Write-Host $text -ForegroundColor Yellow }
}
function Test-Url($url) { try { Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5 | Out-Null; $true } catch { $false } }
function Wait-Url($url, $seconds) { for ($i = 0; $i -lt $seconds; $i++) { if (Test-Url $url) { return $true }; Start-Sleep 1 }; $false }

Say "Almanac: starting..." Cyan

# 1. Ollama (the local AI, shared with Papercut)
if (Test-Url "http://127.0.0.1:11434/api/version") { Say "  Ollama         already running" }
elseif (Test-Path $ollama) {
    Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
    if (Wait-Url "http://127.0.0.1:11434/api/version" 20) { Say "  Ollama         started" }
    else { Warn "Ollama did not start, so the assistant can't answer. Your plan and calendar still work." }
} else { Warn "Ollama is not installed, so the assistant can't answer. Your plan and calendar still work." }

# 2. Almanac server (hidden, this PC only; output to almanac.log, previous run kept)
if (Test-Url "http://127.0.0.1:$port/api/health") { Say "  Almanac        already running" }
else {
    if (Test-Path "$here\almanac.log") { Move-Item "$here\almanac.log" "$here\almanac.prev.log" -Force -ErrorAction SilentlyContinue }
    $python = "$here\.venv\Scripts\python.exe"
    $cmd = "/c `"`"$python`" -m uvicorn --factory app.main:create_app --host 127.0.0.1 --port $port > `"$here\almanac.log`" 2>&1`""
    Start-Process cmd -ArgumentList $cmd -WorkingDirectory $here -WindowStyle Hidden
    if (Wait-Url "http://127.0.0.1:$port/api/health" 60) { Say "  Almanac        started" }
    else { Fail "The Almanac server did not start. See almanac.log in $here." }
}

# Tray icon: shows whether it's running, and pops Windows notifications (one copy only).
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$here\almanac-tray.ps1`""

# 3. Tailscale Serve: https://<this PC>.<tailnet>.ts.net:8443 for the laptop
$remote = $null
if (-not (Test-Path $tailscale)) { Warn "Tailscale is not installed, so the laptop can't reach Almanac." }
else {
    $state = (& $tailscale status --json | ConvertFrom-Json)
    if ($state.BackendState -eq "Stopped") { & $tailscale up | Out-Null; $state = (& $tailscale status --json | ConvertFrom-Json) }
    if ($state.BackendState -ne "Running") {
        $gui = "C:\Program Files\Tailscale\tailscale-ipn.exe"
        if (Test-Path $gui) { Start-Process $gui }
        Warn "Tailscale needs you to sign in (the Tailscale app is open). Until then, the laptop can't reach Almanac."
    } else {
        $serve = Start-Process $tailscale -ArgumentList "serve --bg --https=$httpsPort $port" -WindowStyle Hidden -PassThru
        if ($serve.WaitForExit(20000)) {
            $remote = "https://" + $state.Self.DNSName.TrimEnd(".") + ":$httpsPort"
            Say "  Tailscale      serving on $remote"
        } else { $serve.Kill(); Warn "Tailscale Serve didn't start. Run start-almanac.ps1 from a console to see why." }
    }
}

# 4. Open Almanac in its own window
if ($NoOpen) { exit 0 }
. "$here\almanac-open.ps1"
if ($App) { Open-Almanac; exit 0 }
Write-Host ""
Write-Host "Almanac is ready." -ForegroundColor Green
Write-Host "  On this PC:     http://localhost:$port"
if ($remote) { Write-Host "  On the laptop:  $remote   (copied to clipboard)"; Set-Clipboard -Value $remote }
Write-Host ""
Write-Host "To stop Almanac, run stop-almanac.bat or use the tray icon."
Open-Almanac
