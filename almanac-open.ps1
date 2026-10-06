# Open the installed Almanac app with its Start menu identity and icon.
function Open-Almanac {
    $shell = New-Object -ComObject Shell.Application
    $installed = $shell.Namespace('shell:AppsFolder').Items() |
        Where-Object { $_.Name -eq 'Almanac' -and $_.Path -like 'localhost-*!App' } |
        Select-Object -First 1
    if ($installed) {
        $installed.InvokeVerb('open')
        return
    }
    # Fallback for PCs where Almanac has not been installed through Edge.
    $edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge) { Start-Process $edge -ArgumentList "--app=http://localhost:8001" }
    else { Start-Process "http://localhost:8001" }
}
