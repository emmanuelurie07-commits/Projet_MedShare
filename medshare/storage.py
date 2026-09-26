"""
Stockage média S3-compatible (Supabase Storage) pour la production.

Activé par `MEDIA_STORAGE=s3` dans l'environnement. Sans cette variable,
Django utilise FileSystemStorage (développement, Render sur volume Docker).

Configuration attendue dans l'environnement (Dashboard Vercel / Render) :
- AWS_S3_ENDPOINT_URL    ex. https://<project-ref>.supabase.co/storage/v1/s3
- AWS_ACCESS_KEY_ID      (clé S3 Supabase — Project Settings → Storage)
- AWS_SECRET_ACCESS_KEY
- AWS_STORAGE_BUCKET_NAME
- AWS_S3_REGION_NAME     région du projet (ou eu-central-1 par défaut)
"""

from storages.backends.s3 import S3Boto3Storage


class MedShareS3Storage(S3Boto3Storage):
    """Médias privés (avatars patients, photos DUT) servis en URL signées."""

    default_acl = None            # pas d'ACL (bucket privé)
    file_overwrite = False        # un nouveau contenu → un nouveau nom
    querystring_auth = True       # URLs signées (lecture privée)
    querystring_expire = 3600     # validité 1 heure