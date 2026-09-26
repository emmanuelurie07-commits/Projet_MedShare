# Fichier d'entrée Serverless pour Vercel : expose le WSGI Django.
# Vercel routé toutes les requêtes vers /api/index via vercel.json,
# le middleware WhiteNoise sert ensuite les fichiers statiques.

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'medshare.settings')

application = get_wsgi_application()