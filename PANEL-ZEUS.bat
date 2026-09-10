@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\launch_zeus.py dashboard
pause
