#!/bin/bash
set -euo pipefail

# Répertoires de données persistantes (montés par volumes, cf. docker-compose.yml)
mkdir -p "$MEDIA_ROOT" "$STATIC_ROOT"

echo "[1/3] migrations..."
python manage.py migrate --noinput

echo "[2/3] fichiers statiques..."
python manage.py collectstatic --noinput

echo "[3/3] démarrage gunicorn (mode réel dlib)..."
exec gunicorn medshare.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-180}" \
    --access-logfile -