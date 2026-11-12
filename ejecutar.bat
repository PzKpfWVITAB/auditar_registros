@echo off
chcp 65001 > nul
title Sistema de Auditoria de Registros OCR - Servidor Activo
color 0a

echo ======================================================================
echo           SISTEMA DE AUDITORIA DE REGISTROS POR OCR (MYSQL)
echo ======================================================================
echo.

:: 1. Verificar si MySQL de Laragon esta activo; si no, levantarlo
powershell -Command "try { $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 3306); $client.Close(); exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo [INFO] Iniciando motor MySQL de Laragon en segundo plano...
    if exist "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" (
        start "" /B "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" --defaults-file="C:\laragon\bin\mysql\mysql-8.0.30-winx64\my.ini"
        timeout /t 3 /nobreak > nul
    )
)

echo [OK] Base de Datos MySQL verificada.
echo [OK] Iniciando Dashboard Web en: http://127.0.0.1:8000
echo.
echo Presiona Ctrl+C en esta ventana para detener el servidor cuando termines.
echo ======================================================================
echo.

:: Abrir navegador automaticamente tras 2 segundos
start "" powershell -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"

:: Lanzar servidor Uvicorn con FastAPI (lee WEB_HOST y WEB_PORT desde .env)
python -m web.app

if %errorlevel% neq 0 (
    color 0c
    echo [ERROR] El servidor se detuvo inesperadamente.
    pause
)
