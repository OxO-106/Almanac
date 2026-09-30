@echo off
rem Stops the Almanac server (whatever listens on port 8001). The tray icon turns grey.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo Almanac stopped.
