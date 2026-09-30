# Almanac's icon in the notification area (system tray).
#   coloured = server running, grey = stopped (checked every 5 seconds).
#   Almanac's notifications (briefing, check-ins, timer, overviews) pop up as
#   Windows notifications from here, so they arrive even with no window open.
# Double-click opens Almanac; right-click for more. One copy runs at a time.

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$created = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\AlmanacTray", [ref]$created)
if (-not $created) { exit 0 }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = "http://127.0.0.1:8001"
. "$here\almanac-open.ps1"

$size = [System.Windows.Forms.SystemInformation]::SmallIconSize
$onIcon = New-Object System.Drawing.Icon("$here\web\icons\almanac.ico", $size)
$bmp = $onIcon.ToBitmap()
$grey = New-Object System.Drawing.Bitmap($bmp.Width, $bmp.Height)
$g = [System.Drawing.Graphics]::FromImage($grey)
[System.Windows.Forms.ControlPaint]::DrawImageDisabled($g, $bmp, 0, 0, [System.Drawing.Color]::Transparent)
$g.Dispose()
$offIcon = [System.Drawing.Icon]::FromHandle($grey.GetHicon())

$remote = $null
try {
    $ts = & "C:\Program Files\Tailscale\tailscale.exe" status --json | ConvertFrom-Json
    if ($ts.BackendState -eq "Running") { $remote = "https://" + $ts.Self.DNSName.TrimEnd(".") + ":8443" }
} catch {}

function Get-Json($path) {
    try { Invoke-RestMethod -Uri "$base$path" -TimeoutSec 3 } catch { $null }
}

$tray = New-Object System.Windows.Forms.NotifyIcon
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$status = $menu.Items.Add("Almanac"); $status.Enabled = $false
[void]$menu.Items.Add("-")
$open = $menu.Items.Add("Open Almanac")
$open.Font = New-Object System.Drawing.Font($open.Font, [System.Drawing.FontStyle]::Bold)
$open.add_Click({ Open-Almanac })
if ($remote) {
    $copy = $menu.Items.Add("Copy laptop link"); $copy.ToolTipText = $remote
    $copy.add_Click({ [System.Windows.Forms.Clipboard]::SetText($remote) })
}
[void]$menu.Items.Add("-")
$start = $menu.Items.Add("Start Almanac")
$start.add_Click({ Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$here\start-almanac.ps1`" -App" })
$stop = $menu.Items.Add("Stop Almanac")
$stop.add_Click({ & "$here\stop-almanac.bat" | Out-Null; Update-Status })
[void]$menu.Items.Add("-")
$quit = $menu.Items.Add("Hide this icon")
$quit.add_Click({ $tray.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$tray.ContextMenuStrip = $menu
$tray.add_DoubleClick({ Open-Almanac })
$tray.add_BalloonTipClicked({ Open-Almanac })

$script:running = $null
$seenFile = "$here\data\.tray-seen"  # last notification shown by this icon
function Update-Status {
    $health = Get-Json "/api/health"
    $up = $null -ne $health
    if ($up -ne $script:running) {
        $script:running = $up
        $tray.Icon = if ($up) { $onIcon } else { $offIcon }
        $tray.Text = if ($up) { "Almanac: running" } else { "Almanac: stopped" }
        $status.Text = if ($up) { "Almanac is running" } else { "Almanac is stopped" }
        $open.Enabled = $up; $start.Visible = -not $up; $stop.Visible = $up
    }
    if (-not $up) { return }
    $seen = if (Test-Path $seenFile) { [int](Get-Content $seenFile) } else { -1 }
    $new = @(Get-Json "/api/notifications?after=$([Math]::Max($seen, 0))")
    if ($seen -lt 0) {  # first run: start from now, don't replay history
        $last = @(Get-Json "/api/notifications?after=0") | Select-Object -Last 1
        Set-Content $seenFile ($(if ($last) { $last.id } else { 0 })); return
    }
    foreach ($n in $new) {
        if ($null -eq $n) { continue }
        $tray.ShowBalloonTip(10000, $n.title, $(if ($n.body) { $n.body } else { " " }), [System.Windows.Forms.ToolTipIcon]::None)
        Set-Content $seenFile $n.id
    }
}

$tray.Visible = $true
Update-Status
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.add_Tick({ Update-Status })
$timer.Start()
[System.Windows.Forms.Application]::Run()
$tray.Dispose()
