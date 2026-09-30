# Adds "Almanac" to the Start menu (runs launch-almanac.vbs, with Almanac's icon).
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Almanac.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = "$env:WINDIR\System32\wscript.exe"
$s.Arguments = "`"$here\launch-almanac.vbs`""
$s.WorkingDirectory = $here
$s.IconLocation = "$here\web\icons\almanac.ico"
$s.Description = "Almanac: your plan, calendar and assistant"
$s.Save()
Write-Host "Start menu entry created: $lnk"
