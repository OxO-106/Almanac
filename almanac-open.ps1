# Open-Almanac: an Edge app window (no tabs or address bar) on this PC.
function Open-Almanac {
    $edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge) { Start-Process $edge -ArgumentList "--app=http://localhost:8001" }
    else { Start-Process "http://localhost:8001" }
}
