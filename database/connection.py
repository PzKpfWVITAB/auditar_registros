import pymysql
from pymysql.cursors import DictCursor
from config import settings

def get_raw_connection(include_database=True):
    """
    Retorna una conexión activa a MySQL.
    Si include_database=False, se conecta al servidor sin seleccionar base de datos (para crear la DB).
    """
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME if include_database else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5
    )

def test_connection():
    """
    Verifica si el servidor MySQL está accesible.
    """
    try:
        conn = get_raw_connection(include_database=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ping;")
            res = cursor.fetchone()
        conn.close()
        return True, "Conexión exitosa a MySQL."
    except Exception as e:
        return False, str(e)
