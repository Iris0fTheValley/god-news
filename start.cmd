@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start.ps1"
if errorlevel 1 (
  echo.
  echo god-news failed to start. Check logs\dev for details.
  pause
)
