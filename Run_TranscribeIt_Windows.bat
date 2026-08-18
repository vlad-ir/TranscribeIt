@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title TranscribeIt

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "RUNTIME=%ROOT%\.runtime"
set "ENV=%ROOT%\.venv"
set "CACHE=%ROOT%\.cache\pip"
set "MINICONDA_EXE=%RUNTIME%\miniforge-installer.exe"
set "MINICONDA_URL=https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"

if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "%CACHE%" mkdir "%CACHE%"

call :discover_conda
if not defined CONDA_CMD (
    echo [1/4] Downloading the private Python runtime...
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%MINICONDA_URL%' -OutFile '%MINICONDA_EXE%' } catch { exit 1 }"
    if errorlevel 1 goto :download_error
    echo [2/4] Installing the private Python runtime...
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& $env:MINICONDA_EXE /S ('/D=' + $env:RUNTIME + '\miniforge3'); exit $LASTEXITCODE"
    if errorlevel 1 goto :runtime_error
    del /q "%MINICONDA_EXE%" >nul 2>&1
    call :wait_for_conda
)
if not defined CONDA_CMD goto :runtime_path_error

if not exist "%ENV%\python.exe" (
    echo [3/4] Creating the local TranscribeIt environment...
    call "%CONDA_CMD%" create -p "%ENV%" --override-channels -c conda-forge python=3.10 -y
    if errorlevel 1 (
        echo Direct conda-forge installation failed. Configuring the local channel and retrying...
        call "%CONDA_CMD%" config --add channels conda-forge
        if errorlevel 1 goto :environment_error
        call "%CONDA_CMD%" create -p "%ENV%" -c conda-forge python=3.10 -y
        if errorlevel 1 goto :environment_error
    )
)

if not exist "%ENV%\python.exe" goto :environment_path_error

set "NVIDIA_CUBLAS_BIN=%ENV%\Lib\site-packages\nvidia\cublas\bin"
set "NVIDIA_CUDNN_BIN=%ENV%\Lib\site-packages\nvidia\cudnn\bin"
set "PATH=%NVIDIA_CUBLAS_BIN%;%NVIDIA_CUDNN_BIN%;%PATH%"

if not exist "%ROOT%\.deps-ready-v3" (
    echo [4/4] Installing TranscribeIt dependencies, including PyAV and FFmpeg libraries...
    set "PIP_CACHE_DIR=%CACHE%"
    "%ENV%\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :dependency_error
    "%ENV%\python.exe" -m pip install --upgrade --force-reinstall --only-binary=:all: "av>=14.0,<15.0"
    if errorlevel 1 goto :media_dependency_error
    "%ENV%\python.exe" -m pip install -r "%ROOT%\requirements.txt"
    if errorlevel 1 goto :dependency_error
    type nul > "%ROOT%\.deps-ready-v3"
) else (
    echo [4/4] TranscribeIt dependencies are already installed.
)

"%ENV%\python.exe" -c "import av; print('PyAV/FFmpeg runtime: OK')"
if errorlevel 1 goto :media_runtime_error

if not exist "%ROOT%\models\whisper" mkdir "%ROOT%\models\whisper"
if not exist "%ROOT%\models\argos" mkdir "%ROOT%\models\argos"
if not exist "%ROOT%\output" mkdir "%ROOT%\output"
if not exist "%ROOT%\temp" mkdir "%ROOT%\temp"
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
if not exist "%ROOT%\bin" mkdir "%ROOT%\bin"

echo.
echo Starting TranscribeIt. Models will be downloaded into this folder on first use.
cd /d "%ROOT%"
"%ENV%\python.exe" "%ROOT%\main.py"
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%

:discover_conda
set "CONDA_CMD="
set "CONDA_ROOT="
if exist "%RUNTIME%\miniforge3\condabin\conda.bat" (
    set "CONDA_ROOT=%RUNTIME%\miniforge3"
    set "CONDA_CMD=%RUNTIME%\miniforge3\condabin\conda.bat"
    exit /b 0
)
if exist "%RUNTIME%\miniforge3\Scripts\conda.exe" (
    set "CONDA_ROOT=%RUNTIME%\miniforge3"
    set "CONDA_CMD=%RUNTIME%\miniforge3\Scripts\conda.exe"
    exit /b 0
)
if exist "%RUNTIME%\miniforge3\Scripts\conda.bat" (
    set "CONDA_ROOT=%RUNTIME%\miniforge3"
    set "CONDA_CMD=%RUNTIME%\miniforge3\Scripts\conda.bat"
    exit /b 0
)
if exist "%RUNTIME%\condabin\conda.bat" (
    set "CONDA_ROOT=%RUNTIME%"
    set "CONDA_CMD=%RUNTIME%\condabin\conda.bat"
    exit /b 0
)
if exist "%RUNTIME%\Scripts\conda.exe" (
    set "CONDA_ROOT=%RUNTIME%"
    set "CONDA_CMD=%RUNTIME%\Scripts\conda.exe"
    exit /b 0
)
for /d %%D in ("%RUNTIME%\*") do if not defined CONDA_CMD (
    if exist "%%~fD\condabin\conda.bat" (
        set "CONDA_ROOT=%%~fD"
        set "CONDA_CMD=%%~fD\condabin\conda.bat"
    ) else if exist "%%~fD\Scripts\conda.exe" (
        set "CONDA_ROOT=%%~fD"
        set "CONDA_CMD=%%~fD\Scripts\conda.exe"
    )
)
exit /b 0

:wait_for_conda
for /l %%N in (1,1,15) do (
    call :discover_conda
    if defined CONDA_CMD exit /b 0
    timeout /t 1 /nobreak >nul
)
exit /b 1

:download_error
echo Could not download the private Python runtime. Check the internet connection.
goto :fail
:runtime_error
echo Could not install the private Python runtime.
goto :fail
:runtime_path_error
echo Miniforge installation completed, but no usable conda launcher appeared.
echo Expected a Miniforge folder under .runtime with condabin\conda.bat or Scripts\conda.exe.
echo Files found under .runtime:
dir /s /b "%RUNTIME%\conda*" 2^>nul
goto :fail
:environment_error
echo Could not create the local Python environment.
goto :fail
:environment_path_error
echo The local Python environment was not created correctly.
goto :fail
:dependency_error
echo Could not install TranscribeIt dependencies.
goto :fail
:media_dependency_error
echo Could not install the Windows PyAV binary with bundled FFmpeg libraries.
goto :fail
:media_runtime_error
echo PyAV could not load its bundled FFmpeg libraries. Remove .venv and run this launcher again.
goto :fail
:fail
pause
exit /b 1
