import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Database configuration
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "auditoria_registros")

# Scan configuration
DEFAULT_SCAN_PATH = os.getenv("DEFAULT_SCAN_PATH", r"\\172.40.5.84\ssdirec\COPIA_REGISTROS")
SCAN_RECURSIVE = os.getenv("SCAN_RECURSIVE", "false").strip().lower() in ("true", "1", "yes", "si")

# Web configuration
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# OCR configuration
OCR_LANG = os.getenv("OCR_LANG", "es")
OCR_DPI = int(os.getenv("OCR_DPI", "150"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))

# Laragon MySQL paths
LARAGON_MYSQL_EXE = os.getenv("LARAGON_MYSQL_EXE", r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqld.exe")
LARAGON_MYSQL_INI = os.getenv("LARAGON_MYSQL_INI", r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\my.ini")
