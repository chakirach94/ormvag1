"""
Irrigation Network Work Tracker  –  app.py
Flask backend with SQLite, session-based auth, role management.
"""

import os, json
from datetime import date
from functools import wraps
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash)
import sqlite3

app = Flask(__name__)
app.secret_key = "irrigation-secret-2024"

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "irrigation.db")
GEOJSON_DIR = os.path.join(BASE_DIR, "static", "geojson")
CONV_FACTOR = 6.81   # 1 unité → 6.81 ml

DIAMETRES = ["63mm","90mm","110mm","125mm","140mm","160mm","180mm","200mm","250mm","315mm"]
AGRS      = ["TAZI","SEA","BEHT","KSIRI"]
SECTEURS  = ["Secteur 1","Secteur 2","Secteur 3","Secteur 4","Secteur 5",
             "Secteur 6","Secteur 7","Secteur 8","Secteur 9","Secteur 10"]

# ─── DB helpers ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def query(sql, params=(), one=False):
    with get_db() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()

def execute(sql, params=()):
    with get_db() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    NOT NULL UNIQUE,
                password TEXT    NOT NULL,
                role     TEXT    NOT NULL DEFAULT 'user',
                agr      TEXT
            );
            CREATE TABLE IF NOT EXISTS reseaux (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL,
                geojson_file TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provenance (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS prices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                provenance_id   INTEGER NOT NULL,
                diametre        TEXT    NOT NULL,
                prix_fourniture REAL    NOT NULL DEFAULT 0,
                prix_pose       REAL    NOT NULL DEFAULT 0,
                FOREIGN KEY (provenance_id) REFERENCES provenance(id),
                UNIQUE(provenance_id, diametre)
            );
            CREATE TABLE IF NOT EXISTS work_done (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                annee           INTEGER NOT NULL,
                reseau_id       INTEGER NOT NULL,
                agr             TEXT    NOT NULL,
                secteur         TEXT    NOT NULL,
                diametre        TEXT    NOT NULL,
                quantite_unite  REAL    NOT NULL,
                quantite_ml     REAL    NOT NULL,
                provenance_id   INTEGER NOT NULL,
                serie           TEXT,
                date            TEXT    NOT NULL,
                FOREIGN KEY (user_id)       REFERENCES users(id),
                FOREIGN KEY (reseau_id)     REFERENCES reseaux(id),
                FOREIGN KEY (provenance_id) REFERENCES provenance(id)
            );
        """)
        conn.commit()
        _seed(conn)

def _seed(conn):
    users = [
        ("TAZI",  "TAZI",  "user",        "TAZI"),
        ("SEA",   "SEA",   "user",        "SEA"),
        ("BEHT",  "BEHT",  "user",        "BEHT"),
        ("KSIRI", "KSIRI", "user",        "KSIRI"),
        ("admin", "admin", "super_admin", None),
    ]
    for u, p, r, a in users:
        conn.execute(
            "INSERT OR IGNORE INTO users (username,password,role,agr) VALUES (?,?,?,?)",
            (u, p, r, a))
    for p in ["M13/23","M11/22","M14/24","M15/24"]:
        conn.execute("INSERT OR IGNORE INTO provenance (reference) VALUES (?)", (p,))
    conn.execute("""
        INSERT OR IGNORE INTO reseaux (id,name,geojson_file)
        VALUES (1,'Réseau C1 – Exemple','reseau_c1.geojson')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO reseaux (id,name,geojson_file)
        VALUES (2,'Réseau Nord','reseau_nord.geojson')
    """)
    conn.commit()

# ─── Auth ─────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "super_admin":
            flash("Accès réservé à l'administrateur.", "error")
            return redirect(url_for("map_screen"))
        return f(*args, **kwargs)
    return decorated

# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("map_screen"))
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        user = query("SELECT * FROM users WHERE username=? AND password=?",
                     (u, p), one=True)
        if user:
            session.update(user_id=user["id"], username=user["username"],
                           role=user["role"], agr=user["agr"])
            return redirect(url_for("map_screen"))
        flash("Identifiants incorrects.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def map_screen():
    reseaux = query("SELECT * FROM reseaux ORDER BY name")
    return render_template("map.html", reseaux=reseaux)

@app.route("/saisie")
@login_required
def saisie():
    reseaux     = query("SELECT * FROM reseaux ORDER BY name")
    provenances = query("SELECT * FROM provenance ORDER BY reference")
    diams_db    = query("SELECT value FROM diameters ORDER BY sort_order")
    diametres   = [d["value"] for d in diams_db] if diams_db else DIAMETRES
    return render_template("saisie.html",
                           reseaux=reseaux, provenances=provenances,
                           diametres=diametres, agrs=AGRS, secteurs=SECTEURS)

@app.route("/stats")
@login_required
def stats():
    return render_template("stats.html")

@app.route("/admin")
@login_required
@admin_required
def admin():
    users       = query("SELECT * FROM users ORDER BY username")
    reseaux     = query("SELECT * FROM reseaux ORDER BY name")
    provenances = query("SELECT * FROM provenance ORDER BY reference")
    prices      = query("""
        SELECT pr.id, pv.reference, pr.diametre,
               pr.prix_fourniture, pr.prix_pose, pr.provenance_id
        FROM prices pr JOIN provenance pv ON pv.id=pr.provenance_id
        ORDER BY pv.reference, pr.diametre
    """)
    # Charger les diamètres depuis la DB (ORMVAG), fallback sur la liste statique
    diams_db  = query("SELECT value FROM diameters ORDER BY sort_order")
    diametres = [d["value"] for d in diams_db] if diams_db else DIAMETRES
    return render_template("admin.html",
                           users=users, reseaux=reseaux,
                           provenances=provenances, prices=prices,
                           diametres=diametres, agrs=AGRS)

# ─── API: map popup data ──────────────────────────────────────────────────────

@app.route("/api/map/reseaux")
@login_required
def api_map_reseaux():
    is_admin  = session["role"] == "super_admin"
    agr_cond  = "AND w.status='approved'" if is_admin else "AND w.agr=? AND w.status='approved'"
    agr_p     = () if is_admin else (session["agr"],)

    reseaux = query("SELECT * FROM reseaux ORDER BY name")
    out = []
    for r in reseaux:
        total = query(
            f"SELECT COALESCE(SUM(quantite_ml),0) t FROM work_done w WHERE reseau_id=? {agr_cond}",
            (r["id"],)+agr_p, one=True)["t"]
        breakdown = query(f"""
            SELECT p.reference, SUM(w.quantite_ml) ml
            FROM work_done w JOIN provenance p ON p.id=w.provenance_id
            WHERE w.reseau_id=? {agr_cond}
            GROUP BY p.id ORDER BY p.reference
        """, (r["id"],)+agr_p)
        out.append({
            "id": r["id"], "name": r["name"],
            "geojson_file": r["geojson_file"],
            "total_ml": round(total,2),
            "breakdown": [{"ref": b["reference"],"ml": round(b["ml"],2)} for b in breakdown]
        })
    return jsonify(out)

# ─── API: travaux ─────────────────────────────────────────────────────────────

@app.route("/api/work", methods=["POST"])
@login_required
def api_add_work():
    d = request.get_json()
    required = ["annee","reseau_id","secteur","diametre","quantite_unite","provenance_id"]
    if not all(str(d.get(k,"")).strip() for k in required):
        return jsonify({"error":"Champs obligatoires manquants"}), 400

    agr = session["agr"] if session["role"] != "super_admin" else d.get("agr","")
    if not agr:
        return jsonify({"error":"AGR requis"}), 400

    qml = round(float(d["quantite_unite"]) * CONV_FACTOR, 4)
    wid = execute("""
        INSERT INTO work_done
          (user_id,annee,reseau_id,agr,secteur,diametre,
           quantite_unite,quantite_ml,provenance_id,serie,date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (session["user_id"], int(d["annee"]), int(d["reseau_id"]),
          agr, d["secteur"], d["diametre"],
          float(d["quantite_unite"]), qml,
          int(d["provenance_id"]), d.get("serie",""),
          date.today().isoformat()))
    return jsonify({"id":wid,"quantite_ml":qml}), 201

@app.route("/api/work/<int:wid>", methods=["DELETE"])
@login_required
def api_delete_work(wid):
    w = query("SELECT * FROM work_done WHERE id=?", (wid,), one=True)
    if not w:
        return jsonify({"error":"Introuvable"}), 404
    if session["role"] != "super_admin":
        if w["user_id"] != session["user_id"]:
            return jsonify({"error":"Non autorisé"}), 403
        if w["status"] != "pending":
            return jsonify({"error":"Impossible de supprimer un travail déjà validé ou rejeté"}), 403
    execute("DELETE FROM work_done WHERE id=?", (wid,))
    return jsonify({"ok":True})

@app.route("/api/work/reseau/<int:rid>")
@login_required
def api_work_reseau(rid):
    is_admin = session["role"] == "super_admin"
    cond     = "" if is_admin else "AND w.agr=?"
    params   = (rid,) if is_admin else (rid, session["agr"])
    rows = query(f"""
        SELECT w.id, w.annee, w.agr, w.secteur, w.diametre,
               w.quantite_unite, w.quantite_ml, w.serie, w.date,
               w.status, p.reference as marche, u.username
        FROM work_done w
        JOIN provenance p ON p.id=w.provenance_id
        JOIN users u ON u.id=w.user_id
        WHERE w.reseau_id=? {cond}
        ORDER BY w.date DESC
    """, params)
    return jsonify([dict(r) for r in rows])

# ─── API: stats ───────────────────────────────────────────────────────────────

@app.route("/api/stats")
@login_required
def api_stats():
    is_admin = session["role"] == "super_admin"
    wh       = "WHERE w.status='approved'" if is_admin else "WHERE w.agr=? AND w.status='approved'"
    p        = () if is_admin else (session["agr"],)

    cost_join = "LEFT JOIN prices pr ON pr.provenance_id=w.provenance_id AND pr.diametre=w.diametre"

    totals = query(f"""
        SELECT COALESCE(SUM(w.quantite_ml),0)                              as total_ml,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_fourniture,0)),0) as fourniture,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_pose,0)),0)       as pose
        FROM work_done w {cost_join} {wh}
    """, p, one=True)

    def grp(col, tbl="work_done w", extra_join=""):
        return query(f"""
            SELECT {col} as label,
                   COALESCE(SUM(w.quantite_ml),0) as total_ml,
                   COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_fourniture,0)),0) as fourniture,
                   COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_pose,0)),0)       as pose
            FROM {tbl} {extra_join} {cost_join}
            {wh} GROUP BY {col} ORDER BY {col}
        """, p)

    par_reseau  = query(f"""
        SELECT r.name as label,
               COALESCE(SUM(w.quantite_ml),0) as total_ml,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_fourniture,0)),0) as fourniture,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_pose,0)),0)       as pose
        FROM reseaux r LEFT JOIN work_done w ON w.reseau_id=r.id AND w.status='approved'
        {cost_join}
        {"" if is_admin else "AND w.agr=?"}
        GROUP BY r.id ORDER BY r.name
    """, p)

    par_marche = query(f"""
        SELECT pv.reference as label,
               COALESCE(SUM(w.quantite_ml),0) as total_ml,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_fourniture,0)),0) as fourniture,
               COALESCE(SUM(w.quantite_ml*COALESCE(pr.prix_pose,0)),0)       as pose
        FROM provenance pv LEFT JOIN work_done w ON w.provenance_id=pv.id AND w.status='approved'
        {cost_join}
        {"" if is_admin else "AND w.agr=?"}
        GROUP BY pv.id ORDER BY pv.reference
    """, p)

    par_agr     = grp("w.agr")
    par_secteur = grp("w.secteur")

    return jsonify({
        "totals":      dict(totals),
        "par_reseau":  [dict(r) for r in par_reseau],
        "par_agr":     [dict(r) for r in par_agr],
        "par_marche":  [dict(r) for r in par_marche],
        "par_secteur": [dict(r) for r in par_secteur],
    })

# ─── API: admin – utilisateurs ───────────────────────────────────────────────

@app.route("/api/admin/users", methods=["POST"])
@login_required
@admin_required
def api_add_user():
    d = request.get_json()
    try:
        uid = execute(
            "INSERT INTO users (username,password,role,agr) VALUES (?,?,?,?)",
            (d["username"], d["password"], d.get("role","user"), d.get("agr") or None))
        return jsonify({"id":uid}), 201
    except Exception as e:
        return jsonify({"error":str(e)}), 400

@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_user(uid):
    if uid == session["user_id"]:
        return jsonify({"error":"Impossible de supprimer votre propre compte"}), 400
    execute("DELETE FROM users WHERE id=?", (uid,))
    return jsonify({"ok":True})

# ─── API: admin – réseaux ────────────────────────────────────────────────────

@app.route("/api/admin/reseaux", methods=["POST"])
@login_required
@admin_required
def api_add_reseau():
    name = request.form.get("name","").strip()
    f    = request.files.get("geojson_file")
    if not name or not f:
        return jsonify({"error":"Nom et fichier GeoJSON requis"}), 400
    fname = f.filename.replace(" ","_")
    f.save(os.path.join(GEOJSON_DIR, fname))
    rid = execute("INSERT INTO reseaux (name,geojson_file) VALUES (?,?)", (name, fname))
    return jsonify({"id":rid,"name":name,"geojson_file":fname}), 201

@app.route("/api/admin/reseaux/<int:rid>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_reseau(rid):
    r = query("SELECT * FROM reseaux WHERE id=?", (rid,), one=True)
    if not r:
        return jsonify({"error":"Introuvable"}), 404
    fp = os.path.join(GEOJSON_DIR, r["geojson_file"])
    if os.path.exists(fp):
        os.remove(fp)
    execute("DELETE FROM work_done WHERE reseau_id=?", (rid,))
    execute("DELETE FROM reseaux WHERE id=?", (rid,))
    return jsonify({"ok":True})

# ─── API: admin – marchés ────────────────────────────────────────────────────

@app.route("/api/admin/provenance", methods=["POST"])
@login_required
@admin_required
def api_add_prov():
    ref = (request.get_json() or {}).get("reference","").strip()
    if not ref:
        return jsonify({"error":"Référence requise"}), 400
    try:
        pid = execute("INSERT INTO provenance (reference) VALUES (?)", (ref,))
        return jsonify({"id":pid,"reference":ref}), 201
    except:
        return jsonify({"error":"Référence déjà existante"}), 400

@app.route("/api/admin/provenance/<int:pid>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_prov(pid):
    execute("DELETE FROM prices WHERE provenance_id=?", (pid,))
    execute("DELETE FROM provenance WHERE id=?", (pid,))
    return jsonify({"ok":True})

# ─── API: admin – tarifs ─────────────────────────────────────────────────────

@app.route("/api/admin/prices", methods=["POST"])
@login_required
@admin_required
def api_upsert_price():
    d = request.get_json()
    execute("""
        INSERT INTO prices (provenance_id,diametre,prix_fourniture,prix_pose)
        VALUES (?,?,?,?)
        ON CONFLICT(provenance_id,diametre)
        DO UPDATE SET prix_fourniture=excluded.prix_fourniture,
                      prix_pose=excluded.prix_pose
    """, (int(d["provenance_id"]), d["diametre"],
          float(d["prix_fourniture"]), float(d["prix_pose"])))
    return jsonify({"ok":True})

@app.route("/api/admin/prices/<int:pid>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_price(pid):
    execute("DELETE FROM prices WHERE id=?", (pid,))
    return jsonify({"ok":True})

# ─── Entry point ─────────────────────────────────────────────────────────────

# ─── Extension Blueprint ──────────────────────────────────────────────────────
from extensions import ext_bp
app.register_blueprint(ext_bp)

if __name__ == "__main__":
    os.makedirs(GEOJSON_DIR, exist_ok=True)
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
