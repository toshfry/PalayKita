@echo off
TITLE Build PalayKita Desktop EXE
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller palaykita_desktop.spec --clean --noconfirm
pause
