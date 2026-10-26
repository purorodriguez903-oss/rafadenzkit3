@echo off
chcp 65001 >nul
title Activar Inicio Automatico con Windows
color 0B

echo ===================================================================
echo     CONFIGURAR BOT PARA INICIAR AUTOMATICAMENTE CON WINDOWS
echo ===================================================================
echo.

set SCRIPT_DIR=%~dp0
set VBS_TARGET=%SCRIPT_DIR%iniciar_oculto.vbs
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP_DIR%\DenzerBot247.lnk'); $Shortcut.TargetPath = '%VBS_TARGET%'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.Save()"

echo.
echo [EXITO] Acceso directo creado en la carpeta de Inicio de Windows.
echo A partir de ahora, cada vez que enciendas tu PC el bot se iniciara
echo automaticamente en segundo plano 24/7 sin que tengas que hacer nada.
echo.
pause
