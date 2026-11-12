import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import time
from core.auditor import auditor_instance
from database import db_manager

def test_flow():
    test_dir = r"C:\laragon\www\auditar_registros\tests\muestra_directorio"
    print("Calling start_audit on:", test_dir)
    ok, msg = auditor_instance.start_audit(test_dir)
    print("start_audit returned:", ok, msg)

    for i in range(25):
        time.sleep(0.2)
        p = auditor_instance.get_progress()
        print(f"Check {i}: status={p['status']} processed={p['processed_files']}/{p['total_files']}")
        if p["status"] != "RUNNING":
            break

    results = db_manager.get_audit_results(page=1, page_size=10)
    print("Results in DB:", len(results["items"]))
    for r in results["items"]:
        print(f"  {r['nombre_archivo']} -> {r['estado']} -> {r['nombre_propuesto']} (Confianza: {r['confianza_score']}%)")

if __name__ == "__main__":
    test_flow()
