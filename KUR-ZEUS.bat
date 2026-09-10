@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\setup_zeus.py --web
if errorlevel 1 goto done
python scripts\launch_zeus.py setup
:done
pause
