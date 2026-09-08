"""Réglages dédiés aux tests MedShare.

Utilisé pour exécuter la suite de tests localement et rapidement, sans
toucher à la base Supabase (pas de base `test_postgres` créée à distance) :

    python manage.py test --settings=medshare.settings_test

Hérite de tous les réglages de production/développement (medshare.settings)
et remplace uniquement la base de données par une SQLite en mémoire.
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Résout les différences SQLite/Supabase (aucun impact fonctionnel).
DATABASES['default']['TEST'] = {'NAME': ':memory:'}

# Les tests ne doivent rien envoyer : backend console.
if 'EMAIL_BACKEND' in globals():
    EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'