"""
Módulo del catálogo oficial de Delegaciones del RPPC Chiapas y motor de
detección difusa a partir del texto OCR de la cabecera del documento.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

# Catálogo oficial de las 19 delegaciones
DELEGACIONES_CATALOGO = [
    {"id": 1, "nombre": "TUXTLA GUTIÉRREZ", "clave": "01", "aliases": ["TUXTLA GUTIERREZ", "TUXTLA"]},
    {"id": 2, "nombre": "SAN CRISTOBAL", "clave": "02", "aliases": ["SAN CRISTOBAL DE LAS CASAS", "SAN CRISTOBAL"]},
    {"id": 3, "nombre": "VENUSTIANO CARRANZA", "clave": "03", "aliases": ["VENUSTIANO CARRANZA", "CARRANZA"]},
    {"id": 4, "nombre": "COMITAN", "clave": "04", "aliases": ["COMITAN DE DOMINGUEZ", "COMITAN"]},
    {"id": 5, "nombre": "BOCHIL", "clave": "05", "aliases": ["BOCHIL"]},
    {"id": 6, "nombre": "COPAINALA", "clave": "06", "aliases": ["COPAINALA"]},
    {"id": 7, "nombre": "TONALA", "clave": "07", "aliases": ["TONALA"]},
    {"id": 8, "nombre": "TAPACHULA", "clave": "08", "aliases": ["TAPACHULA"]},
    {"id": 9, "nombre": "CHIAPA DE CORZO", "clave": "09", "aliases": ["CHIAPA DE CORZO"]},
    {"id": 10, "nombre": "HUIXTLA", "clave": "10", "aliases": ["HUIXTLA"]},
    {"id": 11, "nombre": "MOTOZINTLA", "clave": "11", "aliases": ["MOTOZINTLA"]},
    {"id": 12, "nombre": "CINTALAPA", "clave": "12", "aliases": ["CINTALAPA"]},
    {"id": 13, "nombre": "ACAPETAHUA", "clave": "13", "aliases": ["ACAPETAHUA"]},
    {"id": 14, "nombre": "PICHUCALCO", "clave": "14", "aliases": ["PICHUCALCO"]},
    {"id": 15, "nombre": "VILLAFLORES", "clave": "15", "aliases": ["VILLAFLORES"]},
    {"id": 16, "nombre": "SALTO DE AGUA", "clave": "16", "aliases": ["SALTO DE AGUA"]},
    {"id": 17, "nombre": "CATAZAJA", "clave": "17", "aliases": ["CATAZAJA"]},
    {"id": 18, "nombre": "OCOSINGO", "clave": "18", "aliases": ["OCOSINGO"]},
    {"id": 19, "nombre": "YAJALON", "clave": "19", "aliases": ["YAJALON"]}
]

# Diccionario rápido por clave normalizada (ej: '01' o '1' -> registro)
_CLAVE_MAP = {}
for d in DELEGACIONES_CATALOGO:
    c = d["clave"].zfill(2)
    _CLAVE_MAP[c] = d
    _CLAVE_MAP[str(int(c))] = d

def normalize_text(text: str) -> str:
    """Normaliza quitando acentos, caracteres especiales y mayúsculas."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    # Reemplazar ruidos de OCR habituales en texto de cabecera
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def get_delegacion_by_clave(clave: Optional[str]) -> Optional[Dict[str, Any]]:
    if not clave:
        return None
    c_clean = str(clave).strip()
    return _CLAVE_MAP.get(c_clean.zfill(2)) or _CLAVE_MAP.get(c_clean)

def get_delegacion_display(clave: Optional[str]) -> str:
    info = get_delegacion_by_clave(clave)
    if info:
        return f"{info['clave']} - {info['nombre']}"
    return str(clave or "-")

def detect_delegacion_from_lines(header_lines: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Busca la oficina registral en las líneas superiores (especialmente 'OFICINA REGISTRAL DE...').
    Retorna None si la confianza es < 65% o no se encuentra ninguna coincidencia clara.
    """
    best_match = None
    best_score = 0.0
    best_box = None
    best_raw_text = ""

    # Palabras a ignorar de la entidad general
    prefixes_to_strip = ["OFICINA", "REGISTRAL", "DE", "DISTRITO", "JUDICIAL", "LA"]

    for l in header_lines:
        raw_text = l.get("text", "")
        norm_line = normalize_text(raw_text)
        if not norm_line:
            continue
        rel_y = l.get("rel_y", 0.0)

        # La oficina registral típicamente está entre rel_y 0.08 y 0.28
        if rel_y > 0.35:
            continue

        # Extraer porción relevante si tiene "OFICINA" o "REGISTRAL"
        is_oficina_line = ("OFICINA" in norm_line or "REGISTRAL" in norm_line)

        # Candidato limpio sin prefijos
        tokens = [t for t in norm_line.split() if t not in prefixes_to_strip]
        cleaned_text = " ".join(tokens)

        for del_item in DELEGACIONES_CATALOGO:
            targets = [del_item["nombre"]] + del_item.get("aliases", [])
            for target in targets:
                target_norm = normalize_text(target)

                # 1. Búsqueda exacta de subcadena
                if target_norm in cleaned_text or target_norm in norm_line:
                    score = 100
                else:
                    # 2. Similaridad con fuzzy matching
                    sim_clean = SequenceMatcher(None, target_norm, cleaned_text).ratio() * 100
                    sim_line = SequenceMatcher(None, target_norm, norm_line).ratio() * 100
                    
                    # Checar también sub-bloques de tokens (por ejemplo 'YUXTLRGUTIERREZ' vs 'TUXTLA GUTIERREZ')
                    best_token_sim = 0.0
                    target_tokens_str = "".join(target_norm.split())
                    cleaned_tokens_str = "".join(tokens)
                    sim_condensed = SequenceMatcher(None, target_tokens_str, cleaned_tokens_str).ratio() * 100

                    score = max(sim_clean, sim_line, sim_condensed)

                # Si es la línea específica de la oficina registral, bonificamos
                if is_oficina_line and score > 55:
                    score = min(100.0, score + 15)

                if score > best_score:
                    best_score = score
                    best_match = del_item
                    best_box = l
                    best_raw_text = raw_text

    # Umbral de confianza mínimo de 65%
    if best_match and best_score >= 65.0:
        return {
            "clave": best_match["clave"],
            "nombre": best_match["nombre"],
            "confianza": int(round(best_score)),
            "raw_text": best_raw_text,
            "bounding_box": best_box
        }

    return None
