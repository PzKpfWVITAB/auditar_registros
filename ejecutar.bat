@echo off
chcp 65001 > nul
title Sistema de Auditoria de Registros OCR - Escritorio Windows

:: 1. Verificar si MySQL de Laragon esta activo; si no, levantarlo en segundo plano
powershell -Command "try { $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 3306); $client.Close(); exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    if exist "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" (
        start "" /B "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" --defaults-file="C:\laragon\bin\mysql\mysql-8.0.30-winx64\my.ini"
        timeout /t 3 /nobreak > nul
    )
)

:: 2. Lanzar aplicacion de formularios Windows sin ventana de consola
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw desktop\main.py
) else (
    start "" python desktop\main.py
)
