from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os
import csv

app = Flask(__name__)
# Configuration CORS professionnelle (autorise les requêtes de ton front-end)
CORS(app, resources={r"/*": {"origins": "*"}})

DATABASE_URL = os.environ.get("DATABASE_URL")
CSV_FILENAME = "BDD FINALE.csv"

# ─── Identifiants autorisés ───────────────────────────────────────────────────
USERS = {
    "wasim": "stagiaire"
}

# ─── Connexion base de données ────────────────────────────────────────────────
def get_conn():
    """Crée et renvoie une connexion à PostgreSQL."""
    if not DATABASE_URL:
        raise ValueError("La variable d'environnement 'DATABASE_URL' n'est pas configurée.")
    return psycopg2.connect(DATABASE_URL)

# ─── Vérification du token X-Auth ─────────────────────────────────────────────
def verifier_token(token):
    if not token or ':' not in token:
        return False
    parts = token.split(':', 1)
    username = parts[0]
    password = parts[1]
    return USERS.get(username) == password

# ─── Middleware global : protection des routes ─────────────────────────────────
@app.before_request
def check_auth():
    if request.method == 'OPTIONS':
        return
    if request.endpoint == 'login':
        return
    token = request.headers.get('X-Auth', '')
    if not verifier_token(token):
        return jsonify({"error": "Non autorisé. Veuillez vous connecter."}), 401

# ─── Initialisation et Importation Automatique du CSV ─────────────────────────
def initialiser_base_de_donnees():
    """Crée les tables et injecte le CSV si la base est vide au démarrage."""
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        # 1. Création sécurisée des tables
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
            proprietaire VARCHAR(255),
            client_locataire VARCHAR(255),
            etat VARCHAR(100) DEFAULT 'Disponible',
            montant_loyer NUMERIC,
            date_debut VARCHAR(50),
            date_restitution VARCHAR(50)
        );
        """)
        conn.commit()

        # 2. Remplissage automatique uniquement si la base est vide
        cur.execute("SELECT COUNT(*) FROM vehicules;")
        if cur.fetchone()[0] == 0:
            print("🔄 Base PostgreSQL vide détectée. Lancement de l'import du fichier CSV...")
            
            if os.path.exists(CSV_FILENAME):
                def nettoyer_numerique(val):
                    if not val or str(val).strip() == '' or 'VALEUR' in str(val):
                        return None
                    clean = val.replace('€', '').replace(' ', '').replace('\xa0', '').replace(',', '.').strip()
                    try:
                        return float(clean)
                    except ValueError:
                        return None

                with open(CSV_FILENAME, mode="r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f, delimiter=";")
                    for row in reader:
                        immat = row.get('Immatriculation')
                        if not immat or immat.strip() == '':
                            continue
                        immat = immat.strip().upper()

                        # Insertion ou récupération du véhicule
                        cur.execute("""
                            INSERT INTO vehicules (immatriculation, marque, modele, vin, prix_achat)
                            VALUES (%s, %s, %s, %s, %s) 
                            ON CONFLICT (immatriculation) DO NOTHING RETURNING id;
                        """, (
                            immat,
                            (row.get('Marque') or '').strip().upper(),
                            (row.get('Modèle (D.3)') or '').strip().upper(),
                            row.get('N° de serie (E.)'),
                            nettoyer_numerique(row.get("Prix d'achat €"))
                        ))
                        res = cur.fetchone()
                        vid = res[0] if res else None
                        
                        if not vid:
                            cur.execute("SELECT id FROM vehicules WHERE immatriculation = %s;", (immat,))
                            vid = cur.fetchone()[0]

                        # Insertion du contrat de location lié
                        cur.execute("""
                            INSERT INTO contrats_location (vehicule_id, proprietaire, client_locataire, etat, montant_loyer, date_debut, date_restitution)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """, (
                            vid,
                            row.get('Propriétaire du véhicule'),
                            row.get('Localisation du véhicule'),
                            row.get('Etat', 'Disponible'),
                            nettoyer_numerique(row.get('Montant du loyer ')),
                            row.get('Date de début de contrat client / Reception'),
                            row.get('Date de restitution')
                        ))
                conn.commit()
                print("✅ Toutes les données du CSV ont été injectées avec succès dans PostgreSQL !")
            else:
                print(f"⚠️ Fichier {CSV_FILENAME} absent à la racine du projet. Aucun import effectué.")
        else:
            print("ℹ️ La base de données contient déjà des données. Étape d'importation ignorée.")

    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de la BDD : {e}")
        if conn:
            conn.rollback()
    finally:
        # Fermeture propre et professionnelle des curseurs et connexions
        if cur: cur.close()
        if conn: conn.close()

# ─── ROUTES API ───────────────────────────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Corps de requête invalide."}), 400
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if USERS.get(username) == password:
        return jsonify({
            "success": True,
            "message": "Connexion réussie !",
            "token": f"{username}:{password}"
        })
    return jsonify({"success": False, "message": "Identifiants incorrects."}), 401


@app.route('/stats', methods=['GET'])
def stats():
    conn = None
    cur = None
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
        return jsonify({"total": total, "loue": loue, "vole": vole, "disponible": dispo})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route('/search', methods=['GET'])
def search():
    type_ = request.args.get('type')
    q = request.args.get('q', '')
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        base = """
            SELECT v.id, v.immatriculation, v.marque, v.modele, v.vin, v.prix_achat,
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
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route('/ajouter', methods=['POST'])
def ajouter():
    data = request.json
    if not data:
        return jsonify({"success": False, "message": "Corps de requête invalide."}), 400
    champs_requis = ['immatriculation', 'marque', 'modele']
    for champ in champs_requis:
        if not data.get(champ):
            return jsonify({"success": False, "message": f"Le champ '{champ}' est obligatoire."}), 400
            
    conn = None
    cur = None
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
            data.get('date_debut'),
            data.get('date_restitution')
        ))
        conn.commit()
        return jsonify({"success": True, "message": f"Véhicule {data['immatriculation'].upper()} ajouté avec succès !"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"success": False, "message": f"L'immatriculation {data['immatriculation']} existe déjà."}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route('/modifier', methods=['POST'])
def modifier():
    data = request.json
    if not data or not data.get('contrat_id'):
        return jsonify({"success": False, "message": "contrat_id manquant."}), 400
    
    conn = None
    cur = None
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
        if conn: conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        if cur: cur.close()
        if conn: conn.close()


@app.route('/supprimer', methods=['POST'])
def supprimer():
    data = request.json
    if not data or not data.get('vehicule_id'):
        return jsonify({"success": False, "message": "vehicule_id manquant."}), 400
    
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM contrats_location WHERE vehicule_id = %s", (data['vehicule_id'],))
        cur.execute("DELETE FROM vehicules WHERE id = %s", (data['vehicule_id'],))
        conn.commit()
        return jsonify({"success": True, "message": "Véhicule supprimé avec succès !"})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ─── Point d'entrée ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    initialiser_base_de_donnees()
    app.run(host='0.0.0.0', port=5000, debug=False)
