@echo off
cd /d "%~dp0"
echo ==============================================
echo   math_slide
echo ==============================================

rem Prefer a stable Python 3.10-3.13. (Python 3.14+ preview builds may not work with PyMuPDF)
set PYV=
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PYV (
    py -%%V -c "import sys" >nul 2>&1 && set PYV=%%V
  )
)
if defined PYV (
  set PYCMD=py -%PYV%
  echo Using Python %PYV%
) else (
  set PYCMD=python
  echo [info] Could not find Python 3.10-3.13 via the py launcher. Using default python.
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: installing. This can take a few minutes...
  %PYCMD% -m venv .venv
  if errorlevel 1 goto err
)

".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto err

echo.
echo The app window will open. To quit, click the Power button in the app (top right) or close this window.
".venv\Scripts\python.exe" mathslide\server.py %*
if errorlevel 1 pause
exit /b 0

:err
echo.
echo [ERROR] Installation failed.
echo  1) Install Python 3.12: https://www.python.org/downloads/release/python-3129/
echo     (check "Add python.exe to PATH" during setup)
echo  2) If it still fails, install the Microsoft Visual C++ Redistributable:
echo     https://aka.ms/vs/17/release/vc_redist.x64.exe
echo  3) Delete the .venv folder and run this file again.
pause
exit /b 1
