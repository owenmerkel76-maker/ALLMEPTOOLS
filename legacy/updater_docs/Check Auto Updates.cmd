@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Check-Updater.ps1" -RepairTask -RunUpdate
pause
