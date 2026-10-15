@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-Updater.ps1"
if errorlevel 1 pause
