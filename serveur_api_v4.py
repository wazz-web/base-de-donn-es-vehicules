from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import psycopg2.extras

app = Flask(__name__)
CORS(app)

DB = {
    "host": "localhost",
    "database": "donnee_vehicules",
    "user": "postgres",
    "password": "sonic",
    "port": "5432"
}

# Identifiants de connexion
USERS = {
    "wasim": "stagiaire"
}

def get_conn():
    return psycopg2.connect(**DB)

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if USERS.get(username) == password:
        return jsonify({"success": True, "message": "Connexion réussie !"})
    return jsonify({"success": False, "message": "Identifiants incorrects."}), 401

@app.route('/stats')
def stats():
    token = request.headers.get('X-Auth')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé"}), 401
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
    cur.close(); conn.close()
    return jsonify({"total": total, "loue": loue, "vole": vole, "disponible": dispo})

@app.route('/search')
def search():
    token = request.headers.get('X-Auth')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé"}), 401
    type_ = request.args.get('type')
    q = request.args.get('q', '')
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    base = """
        SELECT v.id, v.immatriculation, v.marque, v.modele,
               c.id as contrat_id, c.client_locataire, c.proprietaire, c.etat, c.montant_loyer
        FROM vehicules v
        LEFT JOIN contrats_location c ON v.id = c.vehicule_id
    """
    if type_ == 'immat':
        cur.execute(base + " WHERE v.immatriculation ILIKE %s", (f'%{q}%',))
    elif type_ == 'client':
        cur.execute(base + " WHERE c.client_locataire ILIKE %s", (f'%{q}%',))
    elif type_ == 'marque':
        cur.execute(base + " WHERE v.marque ILIKE %s", (f'%{q}%',))
    elif type_ == 'etat':
        cur.execute(base + " WHERE c.etat ILIKE %s", (f'%{q}%',))
    elif type_ == 'tous':
        cur.execute(base + " ORDER BY v.immatriculation")
    else:
        return jsonify([])
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/ajouter', methods=['POST'])
def ajouter():
    token = request.headers.get('X-Auth')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé"}), 401
    data = request.json
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vehicules (immatriculation, marque, modele, vin)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (data['immatriculation'], data['marque'], data['modele'], data.get('vin')))
        vid = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO contrats_location (vehicule_id, proprietaire, client_locataire, etat, montant_loyer, date_debut, date_restitution)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (vid, data.get('proprietaire'), data.get('client_locataire'), data.get('etat', 'Disponible'), data.get('montant_loyer'), data.get('date_debut'), data.get('date_restitution')))
        conn.commit()
        return jsonify({"success": True, "message": "Véhicule ajouté avec succès !"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cur.close(); conn.close()

@app.route('/modifier', methods=['POST'])
def modifier():
    token = request.headers.get('X-Auth')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé"}), 401
    data = request.json
    conn = get_conn()
    cur = conn.cursor()
    try:
        if data.get('etat'):
            cur.execute("UPDATE contrats_location SET etat = %s WHERE id = %s", (data['etat'], data['contrat_id']))
        if data.get('client_locataire'):
            cur.execute("UPDATE contrats_location SET client_locataire = %s WHERE id = %s", (data['client_locataire'], data['contrat_id']))
        conn.commit()
        return jsonify({"success": True, "message": "Modifié avec succès !"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cur.close(); conn.close()

@app.route('/supprimer', methods=['POST'])
def supprimer():
    token = request.headers.get('X-Auth')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé"}), 401
    data = request.json
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM contrats_location WHERE vehicule_id = %s", (data['vehicule_id'],))
        cur.execute("DELETE FROM contrats_financement WHERE vehicule_id = %s", (data['vehicule_id'],))
        cur.execute("DELETE FROM vehicules WHERE id = %s", (data['vehicule_id'],))
        conn.commit()
        return jsonify({"success": True, "message": "Véhicule supprimé avec succès !"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        cur.close(); conn.close()

def verifier_token(token):
    return token == "wasim:stagiaire"

if __name__ == '__main__':
    print("Serveur démarré sur http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
