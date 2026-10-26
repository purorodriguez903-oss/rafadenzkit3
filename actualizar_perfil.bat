@echo off
chcp 65001 >nul
title Actualizar Perfil del Bot en Discord
color 0A

cd /d "%~dp0"
echo ===================================================================
echo     ACTUALIZANDO AVATAR ANIMADO, BANNER Y DESCRIPCION
echo ===================================================================
echo.
python actualizar_perfil.py
echo.
pause
