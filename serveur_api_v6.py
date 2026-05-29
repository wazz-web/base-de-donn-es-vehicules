from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATABASE_URL = os.environ.get("DATABASE_URL")

# ─── Identifiants autorisés ───────────────────────────────────────────────────
USERS = {
    "wasim": "stagiaire"
}

# ─── Connexion base de données ────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)

# ─── Vérification du token X-Auth ─────────────────────────────────────────────
def verifier_token(token):
    """
    Le token attendu est au format "username:password".
    On vérifie que le couple correspond à un utilisateur valide.
    """
    if not token or ':' not in token:
        return False
    parts = token.split(':', 1)
    username = parts[0]
    password = parts[1]
    return USERS.get(username) == password

# ─── Middleware global : toutes les routes sauf /login sont protégées ──────────
@app.before_request
def check_auth():
    # OPTIONS est ignoré (pré-flight CORS)
    if request.method == 'OPTIONS':
        return
    # La route /login ne nécessite pas d'authentification
    if request.endpoint == 'login':
        return
    token = request.headers.get('X-Auth', '')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé. Veuillez vous connecter."}), 401

# ─── Initialisation des tables ────────────────────────────────────────────────
def initialiser_base_de_donnees():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicules (
        id SERIAL PRIMARY KEY,
        immatriculation VARCHAR(50) UNIQUE,
        vin VARCHAR(100),
        marque VARCHAR(100),
        modele VARCHAR(100),
        prix_achat NUMERIC
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contrats_location (
        id SERIAL PRIMARY KEY,
        vehicule_id INT REFERENCES vehicules(id) ON DELETE CASCADE,
        proprietaire VARCHAR(100),
        client_locataire VARCHAR(100),
        etat VARCHAR(50) DEFAULT 'Disponible',
        montant_loyer NUMERIC,
        date_debut DATE,
        date_restitution DATE
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contrats_financement (
        id SERIAL PRIMARY KEY,
        vehicule_id INT REFERENCES vehicules(id) ON DELETE CASCADE,
        organisme VARCHAR(100),
        montant_financement NUMERIC,
        duree_mois INT
    );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Base de données vérifiée et initialisée.")

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Corps de requête invalide."}), 400
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({"success": False, "message": "Identifiant et mot de passe requis."}), 400
    if USERS.get(username) == password:
        return jsonify({
            "success": True,
            "message": "Connexion réussie !",
            "token": f"{username}:{password}"
        })
    return jsonify({"success": False, "message": "Identifiants incorrects."}), 401


@app.route('/stats', methods=['GET'])
def stats():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vehicules")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM contrats_location WHERE etat ILIKE '%lou%'")
        loue = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM contrats_location WHERE etat ILIKE '%vol%'")
        vole = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM contrats_location WHERE etat ILIKE '%dispo%'")
        dispo = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({"total": total, "loue": loue, "vole": vole, "disponible": dispo})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/search', methods=['GET'])
def search():
    type_ = request.args.get('type')
    q = request.args.get('q', '')
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        base = """
            SELECT v.id, v.immatriculation, v.marque, v.modele,
                   c.id as contrat_id, c.client_locataire, c.proprietaire, c.etat,
                   c.montant_loyer, c.date_debut, c.date_restitution
            FROM vehicules v
            LEFT JOIN contrats_location c ON v.id = c.vehicule_id
        """
        if type_ == 'immat':
            cur.execute(base + " WHERE v.immatriculation ILIKE %s ORDER BY v.immatriculation", (f'%{q}%',))
        elif type_ == 'client':
            cur.execute(base + " WHERE c.client_locataire ILIKE %s ORDER BY v.immatriculation", (f'%{q}%',))
        elif type_ == 'marque':
            cur.execute(base + " WHERE v.marque ILIKE %s ORDER BY v.marque", (f'%{q}%',))
        elif type_ == 'etat':
            cur.execute(base + " WHERE c.etat ILIKE %s ORDER BY v.immatriculation", (f'%{q}%',))
        elif type_ == 'tous':
            cur.execute(base + " ORDER BY v.immatriculation")
        else:
            return jsonify([])
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/ajouter', methods=['POST'])
def ajouter():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Corps de requête invalide."}), 400
    champs_requis = ['immatriculation', 'marque', 'modele']
    for champ in champs_requis:
        if not data.get(champ):
            return jsonify({"success": False, "message": f"Le champ '{champ}' est obligatoire."}), 400
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vehicules (immatriculation, marque, modele, vin)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (
            data['immatriculation'].upper(),
            data['marque'].upper(),
            data['modele'].upper(),
            data.get('vin')
        ))
        vid = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO contrats_location (vehicule_id, proprietaire, client_locataire, etat, montant_loyer, date_debut, date_restitution)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            vid,
            data.get('proprietaire'),
            data.get('client_locataire'),
            data.get('etat', 'Disponible'),
            data.get('montant_loyer') or None,
            data.get('date_debut') or None,
            data.get('date_restitution') or None
        ))
        conn.commit()
        return jsonify({"success": True, "message": f"Véhicule {data['immatriculation'].upper()} ajouté avec succès !"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"success": False, "message": f"L'immatriculation {data['immatriculation']} existe déjà."}), 409
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()


@app.route('/modifier', methods=['POST'])
def modifier():
    data = request.json
    if not data or not data.get('contrat_id'):
        return jsonify({"success": False, "message": "contrat_id manquant."}), 400
    try:
        conn = get_conn()
        cur = conn.cursor()
        updates = []
        values = []
        if data.get('etat'):
            updates.append("etat = %s")
            values.append(data['etat'])
        if data.get('client_locataire'):
            updates.append("client_locataire = %s")
            values.append(data['client_locataire'])
        if data.get('date_debut'):
            updates.append("date_debut = %s")
            values.append(data['date_debut'])
        if data.get('date_restitution'):
            updates.append("date_restitution = %s")
            values.append(data['date_restitution'])
        if not updates:
            return jsonify({"success": False, "message": "Aucun champ à modifier."}), 400
        values.append(data['contrat_id'])
        cur.execute(f"UPDATE contrats_location SET {', '.join(updates)} WHERE id = %s", values)
        conn.commit()
        return jsonify({"success": True, "message": "Véhicule modifié avec succès !"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route('/supprimer', methods=['POST'])
def supprimer():
    data = request.json
    if not data or not data.get('vehicule_id'):
        return jsonify({"success": False, "message": "vehicule_id manquant."}), 400
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM contrats_location WHERE vehicule_id = %s", (data['vehicule_id'],))
        cur.execute("DELETE FROM contrats_financement WHERE vehicule_id = %s", (data['vehicule_id'],))
        cur.execute("DELETE FROM vehicules WHERE id = %s", (data['vehicule_id'],))
        conn.commit()
        return jsonify({"success": True, "message": "Véhicule supprimé avec succès !"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cur.close()
        conn.close()


# ─── Point d'entrée ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    initialiser_base_de_donnees()
    print("🚀 Serveur démarré sur http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
