import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# MySQL pur Python (PythonAnywhere et autres hébergeurs sans mysqlclient) :
# pymysql se fait passer pour MySQLdb, requis par django.db.backends.mysql.
if os.getenv('DB_ENGINE') == 'mysql':
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS:
    # En production, ne jamais laisser la liste vide : Django répondrait 400
    # (DisallowedHost) à chaque requête. Faute de variable ALLOWED_HOSTS, on
    # accepte tout hôte (parking derrière le proxy Render) pour ne pas bloquer.
    ALLOWED_HOSTS = ['*'] if not DEBUG else ['localhost', '127.0.0.1', 'testserver']


# ── Applications ──────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # MedShare applications
    'users.apps.UsersConfig',
    'core.apps.CoreConfig',
    'establishments.apps.EstablishmentsConfig',
    'dmp.apps.DmpConfig',
    'urgences.apps.UrgencesConfig',
]

AUTH_USER_MODEL = 'users.Personnel'

AUTHENTICATION_BACKENDS = [
    'users.backends.MedShareAuthBackend',
]

_MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'users.middleware.MedShareAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'users.middleware.SessionUniqueMiddleware',
    'users.middleware.InactiviteMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'users.middleware.DeuxFacteursMiddleware',
    'users.middleware.ChangerMotDePasseMiddleware',
    'users.middleware.RBACMiddleware',
    'users.middleware.MultiEtablissementMiddleware',
    'users.middleware.EtablissementSuspensionMiddleware',
]

# WhiteNoise (fichiers statiques + médias) uniquement en production :
# en développement (DEBUG=True), Django sert lui-même statique et médias via
# les finders / la vue static(). Le sous-type ``MedShareWhiteNoise`` ajoute
# MEDIA_ROOT à la racine MEDIA_URL.
if not DEBUG:
    # Monté juste après SecurityMiddleware, comme recommandé par WhiteNoise.
    _MIDDLEWARE.insert(1, 'medshare.whitenoise.MedShareWhiteNoise')

MIDDLEWARE = _MIDDLEWARE

ROOT_URLCONF = 'medshare.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'medshare.wsgi.application'


# ── Base de données ───────────────────────────────────────────────────────────
# Moteur piloté par la variable DB_ENGINE :
#   DB_ENGINE=sqlite      → SQLite (défaut en développement)
#   DB_ENGINE=postgresql  → PostgreSQL (défaut en production, sslmode=require)
#   DB_ENGINE=mysql       → MySQL / MariaDB (ex. PythonAnywhere)
# Si DB_ENGINE est absent : SQLite en mode DEBUG, sinon PostgreSQL.

def _config_bdd():
    engine = os.getenv('DB_ENGINE', '')
    if engine == 'sqlite' or (not engine and DEBUG):
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    if engine == 'mysql':
        return {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_NAME'),
            'USER': os.getenv('DB_USER'),
            'PASSWORD': os.getenv('DB_PASSWORD'),
            'HOST': os.getenv('DB_HOST'),
            'PORT': os.getenv('DB_PORT', '3306'),
            'OPTIONS': {},
        }
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'OPTIONS': {'sslmode': 'require'},
        # Réutiliser la connexion ouverte entre les requêtes HTTP (au lieu de
        # la rouvrir ~1,7 s à chaque fois) — indispensable sur base distante.
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        # Ne pas servir une connexion morte (ex. base mise en pause).
        'CONN_HEALTH_CHECKS': True,
    }


DATABASES = {'default': _config_bdd()}


# ── Validation des mots de passe ─────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ── Internationalisation ──────────────────────────────────────────────────────

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Douala'
USE_I18N = True
USE_TZ = True


# ── Fichiers statiques & médias ──────────────────────────────────────────────

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = Path(os.getenv('STATIC_ROOT', str(BASE_DIR / 'staticfiles')))

MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', str(BASE_DIR / 'media')))

# En production, collectstatic génère des noms de fichiers hachés
# (CompressedManifestStaticFilesStorage) ; en développement on garde
# StaticFilesStorage (noms simples, finders).
if not DEBUG:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }


# ── Authentification ─────────────────────────────────────────────────────────

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Déconnexion automatique après inactivité (T8.3) — en minutes.
INACTIVITE_MINUTES = int(os.getenv('INACTIVITE_MINUTES', '30'))


# ── Email ────────────────────────────────────────────────────────────────────
# Canal d'envoi géré par core.mail_backend.EmailBackend :
#   1) EMAIL_PROVIDER=brevo + BREVO_API_KEY   → API Brevo  (HTTPS/443, jamais
#      bloqué — à utiliser en production Render, le SMTP sortant y est bloqué).
#   2) EMAIL_PROVIDER=resend + RESEND_API_KEY → API Resend (HTTPS/443).
#   3) sinon : SMTP si EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD
#      (variables du .env, fonctionne en local), sinon console (démo).

EMAIL_BACKEND = 'core.mail_backend.EmailBackend'

# Variables SMTP (utilisées par le repli 3) — toujours déclarées, sans effet
# si une API HTTPS est configurée.
EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 'yes')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '30'))

# Garde-fou production : sans API HTTPS ni SMTP, les e-mails (2FA,
# candidatures, réinitialisation…) ne sont JAMAIS livrés en production
# (le SMTP sortant de Render est bloqué → Errno 101). On prévient au démarrage.
if not DEBUG and EMAIL_PROVIDER not in ('brevo', 'resend') \
        and not all(os.getenv(k) for k in ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD')):
    import logging
    logging.getLogger('medshare.config').warning(
        'AUCUN canal e-mail fiable en production : EMAIL_PROVIDER non défini '
        'et SMTP sortant bloqué sur Render (Errno 101). Configurez un compte '
        'Brevo ou Resend (gratuit), puis renseignez EMAIL_PROVIDER et '
        'BREVO_API_KEY/RESEND_API_KEY dans le Dashboard Render -> Environment.')

DEFAULT_FROM_EMAIL = os.getenv(
    'DEFAULT_FROM_EMAIL',
    # Fallback : si EMAIL_HOST_USER est défini (Gmail, etc.), on l'utilise
    # comme adresse d'envoi sinon Gmail rejette le message (adresse non autorisée).
    'MedShare <{}>'.format(os.getenv('EMAIL_HOST_USER', 'no-reply@medshare.com'))
)
EMAIL_SUBJECT_PREFIX = os.getenv('EMAIL_SUBJECT_PREFIX', '[MedShare] ')


# ── Sécurité (production) ────────────────────────────────────────────────────

if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = 'DENY'

    # Durcissement HTTPS / cookies (T8.4).
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.getenv(
        'SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 'yes')
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '7200'))
    SESSION_EXPIRE_AT_BROWSER_CLOSE = os.getenv(
        'SESSION_EXPIRE_AT_BROWSER_CLOSE', 'False').lower() in ('true', '1', 'yes')
