@echo off
rem Starts OptoStim from source (after install_windows.bat has been run).
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" goto venv
if exist "%~dp0.conda_bat" goto conda
echo OptoStim is not installed yet. Run install_windows.bat first.
pause
exit /b 1

:venv
start "" "%~dp0.venv\Scripts\pythonw.exe" -m optostim
exit /b 0

:conda
set /p CONDA_BAT=<"%~dp0.conda_bat"
call "%CONDA_BAT%" activate "%~dp0.conda_env"
if errorlevel 1 goto conda_fail
start "" pythonw -m optostim
exit /b 0

:conda_fail
echo Could not activate the conda environment. Run install_windows.bat again.
pause
exit /b 1
