"""
extensions.py – Blueprint Flask pour les fonctionnalités avancées.

Ajouter dans app.py (AVANT `if __name__ == "__main__":`) :

    from extensions import ext_bp
    app.register_blueprint(ext_bp)
"""

import os, io, sqlite3
from functools import wraps
from datetime import datetime
from flask import (Blueprint, request, jsonify, session,
                   redirect, url_for, flash, render_template, send_file)

# Import la fonction Excel (même dossier)
from excel_export import build_excel

ext_bp = Blueprint("ext", __name__)

# ─── Helpers (indépendants de app.py pour éviter l'import circulaire) ────────

_DB = os.path.join(os.path.dirname(__file__), "irrigation.db")

def _db():
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def _q(sql, params=(), one=False):
    with _db() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()

def _ex(sql, params=()):
    with _db() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid

def _login(f):
    @wraps(f)
    def d(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return d

def _admin(f):
    @wraps(f)
    def d(*a, **kw):
        if session.get("role") != "super_admin":
            return jsonify({"error": "Accès non autorisé"}), 403
        return f(*a, **kw)
    return d

# ═══════════════════════════════════════════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/en-attente")
@_login
def pending_page():
    """Admin : liste des travaux en attente de validation."""
    if session.get("role") != "super_admin":
        flash("Accès réservé à l'administrateur.", "error")
        return redirect(url_for("map_screen"))
    count = _q("SELECT COUNT(*) c FROM work_done WHERE status='pending'", one=True)["c"]
    return render_template("pending.html", pending_count=count)

@ext_bp.route("/mes-travaux")
@_login
def mes_travaux_page():
    """Utilisateur : statut de ses propres travaux."""
    return render_template("mes_travaux.html")

# ═══════════════════════════════════════════════════════════════════════════════
# API : NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/api/notifications")
@_login
def api_notifications():
    """
    Admin  → { pending_count: N }
    User   → [ liste de ses travaux avec statut ]
    """
    if session["role"] == "super_admin":
        n = _q("SELECT COUNT(*) c FROM work_done WHERE status='pending'", one=True)["c"]
        return jsonify({"pending_count": n})
    else:
        rows = _q("""
            SELECT w.id, w.annee, w.agr, w.secteur, w.diametre,
                   w.quantite_ml, w.status, w.date,
                   r.name as reseau, p.reference as marche
            FROM work_done w
            JOIN reseaux    r ON r.id = w.reseau_id
            JOIN provenance p ON p.id = w.provenance_id
            WHERE w.user_id = ?
            ORDER BY w.date DESC
            LIMIT 100
        """, (session["user_id"],))
        return jsonify([dict(r) for r in rows])

# ═══════════════════════════════════════════════════════════════════════════════
# API : VALIDATION (APPROBATION / REJET)
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/api/admin/pending")
@_login
@_admin
def api_pending():
    """Retourne tous les travaux en attente pour l'admin."""
    rows = _q("""
        SELECT w.id, w.annee, w.agr, w.secteur, w.diametre,
               w.quantite_unite, w.quantite_ml, w.serie, w.status, w.date,
               r.name as reseau, p.reference as marche, u.username
        FROM work_done w
        JOIN reseaux    r ON r.id = w.reseau_id
        JOIN provenance p ON p.id = w.provenance_id
        JOIN users      u ON u.id = w.user_id
        WHERE w.status = 'pending'
        ORDER BY w.date ASC, w.id ASC
    """)
    return jsonify([dict(r) for r in rows])

@ext_bp.route("/api/work/<int:wid>/approve", methods=["POST"])
@_login
@_admin
def api_approve(wid):
    w = _q("SELECT id FROM work_done WHERE id=?", (wid,), one=True)
    if not w:
        return jsonify({"error": "Introuvable"}), 404
    _ex("UPDATE work_done SET status='approved' WHERE id=?", (wid,))
    return jsonify({"ok": True, "status": "approved"})

@ext_bp.route("/api/work/<int:wid>/reject", methods=["POST"])
@_login
@_admin
def api_reject(wid):
    w = _q("SELECT id FROM work_done WHERE id=?", (wid,), one=True)
    if not w:
        return jsonify({"error": "Introuvable"}), 404
    _ex("UPDATE work_done SET status='rejected' WHERE id=?", (wid,))
    return jsonify({"ok": True, "status": "rejected"})

# ═══════════════════════════════════════════════════════════════════════════════
# API : MISE À JOUR MARCHÉS (UPDATE, pas DELETE/recreate)
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/api/admin/provenance/<int:pid>", methods=["PUT"])
@_login
@_admin
def api_edit_provenance(pid):
    d   = request.get_json() or {}
    ref = d.get("reference", "").strip()
    if not ref:
        return jsonify({"error": "Référence requise"}), 400
    try:
        _ex("UPDATE provenance SET reference=? WHERE id=?", (ref, pid))
        return jsonify({"ok": True, "reference": ref})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ═══════════════════════════════════════════════════════════════════════════════
# API : MISE À JOUR TARIFS (UPDATE)
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/api/admin/prices/<int:pid>", methods=["PUT"])
@_login
@_admin
def api_edit_price(pid):
    d = request.get_json() or {}
    try:
        _ex("""
            UPDATE prices
            SET prix_fourniture = ?,
                prix_pose       = ?
            WHERE id = ?
        """, (float(d.get("prix_fourniture", 0)),
              float(d.get("prix_pose",       0)),
              pid))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ═══════════════════════════════════════════════════════════════════════════════
# API : DIAMÈTRES
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/api/diameters")
@_login
def api_diameters():
    rows = _q("SELECT * FROM diameters ORDER BY sort_order, value")
    return jsonify([dict(r) for r in rows])

@ext_bp.route("/api/admin/diameters", methods=["POST"])
@_login
@_admin
def api_add_diameter():
    d   = request.get_json() or {}
    val = d.get("value", "").strip()
    if not val:
        return jsonify({"error": "Valeur requise"}), 400
    max_order = (_q("SELECT MAX(sort_order) m FROM diameters", one=True)["m"] or 0)
    try:
        did = _ex("INSERT INTO diameters (value, sort_order) VALUES (?,?)",
                  (val, max_order + 1))
        return jsonify({"id": did, "value": val}), 201
    except Exception:
        return jsonify({"error": "Diamètre déjà existant"}), 400

@ext_bp.route("/api/admin/diameters/<int:did>", methods=["PUT"])
@_login
@_admin
def api_edit_diameter(did):
    val = (request.get_json() or {}).get("value", "").strip()
    if not val:
        return jsonify({"error": "Valeur requise"}), 400
    try:
        _ex("UPDATE diameters SET value=? WHERE id=?", (val, did))
        return jsonify({"ok": True, "value": val})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@ext_bp.route("/api/admin/diameters/<int:did>", methods=["DELETE"])
@_login
@_admin
def api_delete_diameter(did):
    _ex("DELETE FROM diameters WHERE id=?", (did,))
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT EXCEL
# ═══════════════════════════════════════════════════════════════════════════════

@ext_bp.route("/export/excel")
@_login
def export_excel():
    """
    Génère l'export Excel CPS (travaux APPROUVÉS uniquement).
    Admin → tout ; User → son AGR uniquement.
    """
    is_admin = session["role"] == "super_admin"

    base_sql = """
        SELECT w.annee, w.agr, w.secteur, w.diametre,
               r.name  as reseau,
               w.quantite_unite, w.quantite_ml,
               p.reference as marche, w.serie,
               COALESCE(pr.prix_fourniture, 0) as prix_four,
               COALESCE(pr.prix_pose,       0) as prix_pose_u
        FROM work_done w
        JOIN reseaux    r  ON r.id  = w.reseau_id
        JOIN provenance p  ON p.id  = w.provenance_id
        LEFT JOIN prices pr ON pr.provenance_id = w.provenance_id
                            AND pr.diametre      = w.diametre
        WHERE w.status = 'approved'
    """

    if is_admin:
        rows = _q(base_sql + " ORDER BY w.annee, w.agr, w.secteur, r.name, w.diametre")
    else:
        rows = _q(
            base_sql + " AND w.agr=? ORDER BY w.annee, w.secteur, r.name, w.diametre",
            (session["agr"],)
        )

    wb  = build_excel([dict(r) for r in rows])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f"export_CPS_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
