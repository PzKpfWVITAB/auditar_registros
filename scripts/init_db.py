import sys
import argparse
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from database.connection import test_connection
from database.db_manager import init_database
from config import settings

def main():
    parser = argparse.ArgumentParser(description="Inicializador de Base de Datos MySQL para Auditoría OCR.")
    parser.add_argument("--clean", action="store_true", help="Elimina la base de datos previa y crea una limpia desde cero.")
    args = parser.parse_args()

    print("=" * 60)
    print("SISTEMA DE AUDITORÍA OCR - INICIALIZACIÓN DE BASE DE DATOS")
    print("=" * 60)
    print(f"Servidor: {settings.DB_HOST}:{settings.DB_PORT}")
    print(f"Usuario : {settings.DB_USER}")
    print(f"Base de Datos: {settings.DB_NAME}")
    print(f"Modo Limpio (--clean): {'SÍ' if args.clean else 'NO (Conservador)'}")
    print("-" * 60)

    # 1. Probar conexión
    ok, msg = test_connection()
    if not ok:
        print(f"[ERROR] No se pudo conectar a MySQL: {msg}")
        print("\nVerifica que MySQL esté iniciado en Laragon.")
        sys.exit(1)

    print("[OK] Conexión con el servidor MySQL establecida.")

    # 2. Inicializar DB y tablas
    ok, msg = init_database(clean=args.clean)
    if not ok:
        print(f"[ERROR] {msg}")
        sys.exit(1)

    print(f"[OK] {msg}")
    print("=" * 60)
    print("Base de datos y tablas listas para usar.")
    print("=" * 60)

if __name__ == "__main__":
    main()
