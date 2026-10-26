@echo off
chcp 65001 >nul
title Detener Bot Denzer 24/7
color 0C

echo ===================================================================
echo               DETENIENDO BOT DE DISCORD 24/7
echo ===================================================================
echo.

:: Cerrar procesos de python que ejecuten bot.py
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

:: Cerrar la ventana del batch si está en loop
powershell -Command "Get-Process cmd -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*Denzer Bot 24/7*' } | Stop-Process -Force"

echo.
echo [OK] El bot y los procesos guardianes se han detenido exitosamente.
echo.
pause
