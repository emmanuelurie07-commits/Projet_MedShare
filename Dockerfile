# MedShare — image SaaS (Django + moteur réel dlib/face_recognition)
# Base micromamba (sans racine pré-existante, aucun MSI, dlib précompilé conda-forge).
FROM mambaorg/micromamba:2.9.0-debian13

# ── Environnement ─────────────────────────────────────────────────────────
ENV MAMBA_ROOT_PREFIX=/opt/conda \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=medshare.settings \
    PATH="/opt/conda/envs/medshare/bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    MEDIA_ROOT=/data/media \
    STATIC_ROOT=/data/static

# ── Moteur réel : Python 3.14 + dlib 20.0.1 précompilé (conda-forge) ──────
# Reproduit À L'IDENTIQUE sur tout poste serveur — aucune compilation MSVC.
RUN micromamba create -y -n medshare -c conda-forge python=3.14 dlib=20.0.1

# ── Dépendances application (pip dans l'env) ──────────────────────────────
# face-recognition SANS ses dépendances (le paquet PyPI face-recognition-models
# est un STUB) ; on installe ensuite les vrais modèles depuis le dépôt GitHub
# et setuptools<81 (pkg_resources requis par face_recognition_models).
RUN micromamba run -n medshare python -m pip install --no-deps face-recognition \
 && micromamba run -n medshare python -m pip install \
        "face_recognition_models @ https://github.com/ageitgey/face_recognition_models/archive/refs/heads/master.tar.gz" \
        scipy Pillow click Django==6.1 python-dotenv setuptools==80.9.0 \
        gunicorn whitenoise "psycopg[binary]"

# ── Code application ──────────────────────────────────────────────────────
WORKDIR /srv/medshare
COPY . .
COPY entrypoint.sh /srv/medshare/entrypoint.sh
RUN chmod +x /srv/medshare/entrypoint.sh

# ── Sécurité (durcissement) : exécution NON root ──────────────────────────
# Un utilisateur applicatif dédié exécute migrate/collectstatic/gunicorn.
# /data (monté par volumes nommés) est pré-créé et appartient à cet
# utilisateur : les volumes nommés héritent de cette propriété à la création.
RUN useradd --create-home --uid 1001 medshare_app \
 && mkdir -p /data/media /data/static \
 && chown -R medshare_app:medshare_app /srv/medshare /data

USER medshare_app

EXPOSE 8000
ENTRYPOINT []
CMD ["bash", "/srv/medshare/entrypoint.sh"]