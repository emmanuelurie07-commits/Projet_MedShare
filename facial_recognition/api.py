"""
API HTTP locale pour le service de reconnaissance faciale.
Lance un serveur Flask simple sur le port 8001 (si Flask est installé).

Usage :
  python -m facial_recognition.api

Endpoints :
  POST /api/match  — Body: { "photo": <base64>, "seuil": 60.0 (optionnel) }
  GET  /api/health — Vérification de santé
"""

import base64
import os
import tempfile

try:
    from flask import Flask, request, jsonify
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

from . import MODE_LIBELLE, MODE_RECHERCHE, ServiceReconnaissanceFaciale

service = ServiceReconnaissanceFaciale()


def _construire_app():
    """Construit l'application Flask (via une factory gardée par HAS_FLASK)."""
    app = Flask(__name__)

    @app.route('/api/health', methods=['GET'])
    def health():
        return jsonify({
            'status': 'ok',
            'service': 'reconnaissance_faciale',
            'mode': MODE_RECHERCHE,
            'mode_libelle': MODE_LIBELLE,
        })

    @app.route('/api/match', methods=['POST'])
    def match():
        data = request.get_json()
        if not data or 'photo' not in data:
            return jsonify({'error': 'Champ "photo" requis'}), 400

        photo_b64 = data['photo']
        # Seuil aligné sur l'application (60 %) : le seuil par défaut ne doit
        # jamais être plus permissif que le seuil métier du service.
        seuil = data.get('seuil', service.seuil_confiance)

        tmp_path = None
        try:
            photo_bytes = base64.b64decode(photo_b64)
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                f.write(photo_bytes)
                tmp_path = f.name

            resultats = service.rechercher_correspondance(tmp_path, seuil)
            return jsonify({
                'resultats': resultats,
                'mode': MODE_RECHERCHE,
                'mode_libelle': MODE_LIBELLE,
            })
        except (ValueError, TypeError) as e:
            return jsonify({'error': str(e)}), 422
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    return app


app = _construire_app() if HAS_FLASK else None


if __name__ == '__main__':
    if app is None:
        raise SystemExit("Flask n'est pas installé — impossible de lancer l'API.")
    print("Service de reconnaissance faciale sur http://localhost:8001")
    app.run(host='0.0.0.0', port=8001, debug=True)