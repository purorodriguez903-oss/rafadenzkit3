@echo off
chcp 65001 >nul
title Denzer Bot 24/7 - Canal de Voz Permanente
color 0A

cd /d "%~dp0"

:loop
cls
echo ===================================================================
echo               DENZER BOT 24/7 - MODO INMORTAL
echo               Canal de Voz: 1543395577289777202
echo ===================================================================
echo.
echo Presiona Ctrl+C en esta ventana si deseas cerrar el bot manualmente.
echo.

python bot.py

echo.
echo ===================================================================
echo [ALERTA] El proceso del bot finalizo o se cerro.
echo Reiniciando automaticamente en 3 segundos para mantenerlo 24/7...
echo ===================================================================
timeout /t 3 /nobreak >nul
goto loop
