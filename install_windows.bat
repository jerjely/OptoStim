@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title OptoStim - install from source
echo.
echo  OptoStim - install from source (Windows)
echo  ----------------------------------------
echo  Most people should use the installer from the Releases page instead.
echo.

rem ---- look for conda (PATH first, then the usual install folders)
set "CONDA_BAT="
for /f "delims=" %%i in ('where conda 2^>nul') do if /i "%%~xi"==".bat" if not defined CONDA_BAT set "CONDA_BAT=%%i"
if defined CONDA_BAT goto have_conda
for %%P in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3") do if exist "%%~P\condabin\conda.bat" if not defined CONDA_BAT set "CONDA_BAT=%%~P\condabin\conda.bat"
if defined CONDA_BAT goto have_conda
goto no_conda

:have_conda
echo Found conda: %CONDA_BAT%
echo Creating a conda environment in the folder .conda_env (Python 3.12, conda-forge)...
call "%CONDA_BAT%" create -y -p "%~dp0.conda_env" -c conda-forge --override-channels python=3.12 pip
if errorlevel 1 goto fail
call "%CONDA_BAT%" activate "%~dp0.conda_env"
if errorlevel 1 goto fail
> "%~dp0.conda_bat" echo %CONDA_BAT%
goto install_packages

:no_conda
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD goto no_python
echo conda not found - using a Python virtual environment in the folder .venv ...
%PYCMD% -m venv "%~dp0.venv"
if errorlevel 1 goto fail
call "%~dp0.venv\Scripts\activate.bat"
goto install_packages

:no_python
echo Neither conda nor Python was found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), then run this file again.
goto fail

:install_packages
echo.
echo Installing the packages OptoStim needs...
python -m pip install --upgrade pip
if errorlevel 1 goto fail
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
python -m optostim --version
if errorlevel 1 goto fail

echo.
echo Creating a desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\OptoStim.lnk'); $s.TargetPath='%~dp0start_optostim.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\OptoStim.ico'; $s.WindowStyle=7; $s.Save()"

echo.
echo Done. Start OptoStim with the desktop shortcut or with start_optostim.bat.
echo.
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
echo.
pause
exit /b 1
