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

# ── Utilisateur applicatif (non root) + répertoires de données ─────────────
# L'utilisateur dédié exécute migrate/collectstatic/gunicorn. /data est créé
# dans CE MÊME RUN (objets nouveaux) : aucun chmod/chown n'est appliqué sur des
# fichiers copiés — ces opérations sont refusées par le système de fichiers de
# certains builders (ex. Render). Le bit +x de entrypoint.sh n'est pas requis :
# le conteneur démarre via `bash script`.
RUN useradd --create-home --uid 1001 medshare_app \
 && mkdir -p /data/media /data/static \
 && chown -R medshare_app:medshare_app /data

# ── Code application (copié en possédé par l'utilisateur applicatif) ───────
WORKDIR /srv/medshare
COPY --chown=medshare_app:medshare_app . .

USER medshare_app

EXPOSE 8000
ENTRYPOINT []
CMD ["bash", "/srv/medshare/entrypoint.sh"]