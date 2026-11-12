@echo off
chcp 65001 > nul
title Instalador 1-Clic: Sistema de Auditoria OCR
color 0b

echo ======================================================================
echo           INSTALADOR 1-CLIC: SISTEMA DE AUDITORIA OCR (MYSQL)
echo ======================================================================
echo.

:: 1. Verificar Python
echo [1/4] Verificando entorno de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0c
    echo [ERROR] Python no esta instalado o no se encuentra en el PATH del sistema.
    echo Por favor instala Python 3.10+ o verificalo antes de continuar.
    echo.
    pause
    exit /b 1
)
python --version
echo [OK] Python detectado correctamente.
echo.

:: 2. Verificar archivo .env
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" > nul
        echo [OK] Archivo .env creado desde .env.example.
    )
)

:: 3. Instalar / Verificar dependencias
echo [2/4] Instalando paquetes de Python (requirements.txt)...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    color 0c
    echo [ERROR] Hubo un problema al instalar las dependencias con pip.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas y actualizadas.
echo.

:: 3. Verificar y arrancar MySQL de Laragon si esta detenido
echo [3/4] Verificando servicio de Base de Datos MySQL...
powershell -Command "try { $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 3306); $client.Close(); exit 0 } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo [AVISO] MySQL no responde en el puerto 3306. Intentando iniciar servicio de Laragon...
    if exist "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" (
        start "" /B "C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe" --defaults-file="C:\laragon\bin\mysql\mysql-8.0.30-winx64\my.ini"
        timeout /t 3 /nobreak > nul
    ) else (
        echo [AVISO] Inicia MySQL desde el panel de control de Laragon (Boton Start All).
    )
)
echo [OK] MySQL listo.
echo.

:: 4. Inicializar Base de Datos y Tablas en MySQL
echo [4/4] Inicializando base de datos y creando tablas en MySQL...
python scripts\init_db.py
if %errorlevel% neq 0 (
    color 0c
    echo [ERROR] No se pudo inicializar la base de datos MySQL.
    echo Asegurate de que MySQL este iniciado en Laragon.
    pause
    exit /b 1
)
echo.
color 0a
echo ======================================================================
echo       INSTALACION COMPLETADA CON EXITO (TODO LISTO EN 1-CLIC)
echo ======================================================================
echo.
echo Ahora puedes hacer doble clic en 'ejecutar.bat' para abrir el Dashboard.
echo.
set /p launch="¿Deseas iniciar la aplicacion ahora mismo? (S/N): "
if /i "%launch%"=="s" (
    call ejecutar.bat
)
