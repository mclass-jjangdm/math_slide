@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1" %*
echo.
echo Done. A shortcut was added to the Desktop and the Start menu.
echo To pin it to the taskbar: right-click the Desktop shortcut and choose "Pin to taskbar".
pause
