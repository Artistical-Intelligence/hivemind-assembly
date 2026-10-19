@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_app\Start.ps1"
if errorlevel 1 pause
