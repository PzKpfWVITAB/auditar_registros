"""
Convierte el archivo 'Total registros.txt' (NombrePDF\tPaginas) en un catálogo
compacto únicamente con los nombres de los PDFs, comprimido en .txt.gz
para poder subirlo al repositorio Git sin problemas de tamaño.
"""
import argparse
import gzip
from pathlib import Path


def convert_registros_txt(source_path: Path, output_path: Path) -> int:
    seen = set()
    names = []

    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            # Tomar primera columna (separada por tabulación o coma)
            col0 = raw.split("\t")[0].split(",")[0].strip().strip('"').strip("'")
            if not col0 or col0.lower() == "nombrepdf":
                continue
            key = col0.lower()
            if key not in seen:
                seen.add(key)
                names.append(col0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8", compresslevel=9) as gz:
        for name in names:
            gz.write(name + "\n")

    return len(names)


def main():
    default_out = Path(__file__).resolve().parent.parent / "database" / "registros_existentes.txt.gz"
    parser = argparse.ArgumentParser(description="Convierte Total registros.txt en catálogo compacto (.txt.gz).")
    parser.add_argument("source", help="Ruta al archivo Total registros.txt original.")
    parser.add_argument("--out", default=str(default_out), help="Ruta de salida (.txt.gz).")
    args = parser.parse_args()

    src = Path(args.source)
    out = Path(args.out)
    if not src.exists():
        raise FileNotFoundError(f"No se encontró el archivo origen: {src}")

    count = convert_registros_txt(src, out)
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"[OK] Se exportaron {count:,} nombres únicos de PDF a: {out} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
