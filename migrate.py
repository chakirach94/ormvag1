"""
migrate.py – Exécuter UNE SEULE FOIS pour mettre à jour la base.
    python migrate.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "irrigation.db")

ORMVAG_DIAMETERS = [
    ("Ø 500 mm",  1), ("Ø 600 mm",  2), ("Ø 700 mm",  3),
    ("Ø 800 mm",  4), ("Ø 950 mm",  5), ("Ø 1100 mm", 6),
    ("Ø 1300 mm", 7), ("Ø 1500 mm", 8), ("Ø 1800 mm", 9),
    ("Ø 1850 mm", 10),
]

def run():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # ── 1. Colonne status ──────────────────────────────────────────────────────
    try:
        c.execute(
            "ALTER TABLE work_done ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
        print("✅  Colonne 'status' ajoutée à work_done")
    except sqlite3.OperationalError:
        print("ℹ️   Colonne 'status' déjà présente")

    # ── 2. Table diameters ────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS diameters (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            value      TEXT    NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        )
    """)
    print("✅  Table 'diameters' créée")

    # ── 3. Seed diamètres ORMVAG ──────────────────────────────────────────────
    inserted = 0
    for val, order in ORMVAG_DIAMETERS:
        try:
            c.execute(
                "INSERT OR IGNORE INTO diameters (value, sort_order) VALUES (?,?)",
                (val, order)
            )
            inserted += c.rowcount
        except Exception:
            pass
    print(f"✅  {inserted} diamètre(s) ORMVAG insérés ({len(ORMVAG_DIAMETERS)} total)")

    conn.commit()
    conn.close()
    print("\n🎉 Migration terminée avec succès.")

if __name__ == "__main__":
    run()
