@echo off
setlocal EnableDelayedExpansion

echo ==========================================================
echo  🎙️ Voice Highlighter Setup (Windows)
echo ==========================================================

cd /d "%~dp0"

echo [1/4] Checking Python installation...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Python was not found on your system.
    echo Attempting to install Python via Windows Package Manager (winget)...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% neq 0 (
        echo Please install Python 3.10-3.12 from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo [2/4] Verifying FFmpeg...
if not exist "bin" mkdir "bin"

where ffmpeg >nul 2>&1
if %ERRORLEVEL% neq 0 (
    if not exist "bin\ffmpeg.exe" (
        echo Downloading portable FFmpeg for Windows...
        powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg.zip'; Expand-Archive -Path '%TEMP%\ffmpeg.zip' -DestinationPath '%TEMP%\ffmpeg-unpack' -Force; Copy-Item '%TEMP%\ffmpeg-unpack\*\bin\ffmpeg.exe' -Destination 'bin\'; Copy-Item '%TEMP%\ffmpeg-unpack\*\bin\ffprobe.exe' -Destination 'bin\'; Remove-Item '%TEMP%\ffmpeg.zip'; Remove-Item '%TEMP%\ffmpeg-unpack' -Recurse"
        echo ✓ FFmpeg installed into bin\
    )
) else (
    echo ✓ FFmpeg detected in system PATH.
)

echo [3/4] Creating Python virtual environment...
if not exist ".venv" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

echo [4/4] Creating Desktop shortcut...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut([System.IO.Path]::Combine($desktop, 'Voice Highlighter.lnk')); $s.TargetPath = [System.IO.Path]::Combine('%~dp0', 'run.bat'); $s.WorkingDirectory = '%~dp0'; $s.Description = 'Voice Highlighter AI Studio'; $s.Save()"

echo ==========================================================
echo  🎉 Voice Highlighter installed successfully!
echo  Double-click the 'Voice Highlighter' icon on your Desktop.
echo ==========================================================
pause
