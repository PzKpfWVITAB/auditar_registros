import sys
import logging
import faulthandler
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_faulthandler_file = None


def setup_logging(process_name: str = "app"):
    """
    Configura logging persistente en logs/auditoria.log, redirige stdout/stderr
    cuando se ejecuta con pythonw.exe (donde son None) y activa faulthandler
    para capturar errores catastróficos (segfault / access violation).
    """
    global _faulthandler_file

    # 1. Redirigir stdout/stderr si son None (típico de pythonw.exe)
    console_log = LOGS_DIR / f"{process_name}_console.log"
    if sys.stdout is None:
        sys.stdout = open(console_log, "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(console_log, "a", encoding="utf-8", buffering=1)

    # 2. Activar faulthandler para fallos nativos C/WinRT
    if _faulthandler_file is None:
        crash_path = LOGS_DIR / "crash.log"
        _faulthandler_file = open(crash_path, "a", encoding="utf-8")
        faulthandler.enable(file=_faulthandler_file, all_threads=True)

    # 3. Configurar logger principal con rotación y flush inmediato
    logger = logging.getLogger("auditoria_ocr")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        handler = RotatingFileHandler(
            LOGS_DIR / "auditoria.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [PID:%(process)d TID:%(thread)d] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger():
    logger = logging.getLogger("auditoria_ocr")
    if not logger.handlers:
        return setup_logging()
    return logger
