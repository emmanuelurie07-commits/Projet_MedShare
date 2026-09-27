"""Diagnostic temporaire de déploiement (Vercel/Render) — à retirer ensuite.

Accessible uniquement avec le jeton SUPERADMIN_INITIAL_PASSWORD (non logué).
Vérifie : connexion BDD (comptages), moteur facial réel ONNX, variables clés.
"""
import json
import os

from django.db import connection
from django.http import JsonResponse


def verif(request):
    if request.GET.get('jeton', '') != os.getenv('SUPERADMIN_INITIAL_PASSWORD', ''):
        return JsonResponse({'erreur': 'acces refuse'}, status=403)

    rapport = {'hote': request.get_host(), 'debug': os.getenv('DEBUG'), 'db': os.getenv('DB_ENGINE')}

    try:
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM users_utilisateur')
            rapport['utilisateurs'] = c.fetchone()[0]
            c.execute('SELECT count(*) FROM users_patientencodage')
            rapport['patientencodages'] = c.fetchone()[0]
    except Exception as e:
        rapport['db_erreur'] = f'{type(e).__name__}: {e}'

    try:
        from facial_recognition import MODE_RECHERCHE, MOTEUR_ACTIF, backend_onnx
        rapport['moteur_actif'] = MOTEUR_ACTIF
        rapport['mode'] = MODE_RECHERCHE
        rapport['onnx_disponible'] = bool(backend_onnx.est_disponible())
    except Exception as e:
        rapport['onnx_erreur'] = f'{type(e).__name__}: {e}'

    return JsonResponse(rapport)