@echo off
setlocal
set "ELECTRON_RUN_AS_NODE=1"
set "ZEUS_DESKTOP_RESOURCES=%~dp0..\resources"
"%~dp0..\ZeusAgent.exe" "%~dp0..\resources\cli\zeus.mjs" %*
exit /b %errorlevel%
