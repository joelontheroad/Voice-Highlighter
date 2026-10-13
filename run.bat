@echo off
cd /d "%~dp0"
set PATH=%~dp0bin;%PATH%
if not exist ".venv" (
    echo Virtual environment not found. Running installer...
    call install.bat
    exit /b
)
call .venv\Scripts\activate.bat
python desktop_launcher.py %*
