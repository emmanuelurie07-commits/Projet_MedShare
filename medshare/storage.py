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

IMPORTANT — et c'est un piège silencieux : Django n'expose PAS les variables
d'environnement comme settings. `django-storages` lit `settings.AWS_*`, il ne
lit pas `os.environ`. Si `medshare/settings.py` ne recopie pas ces variables,
`bucket_name`, `endpoint_url` et `region_name` restent à None et le backend se
connecte sans savoir quel bucket viser : aucun avertissement, seulement des
photos inaccessibles. La recopie est faite dans `medshare/settings.py`.
"""

try:
    # django-storages ≥ 1.14 : la classe s'appelle S3Storage.
    from storages.backends.s3 import S3Storage as _BaseS3Storage
except ImportError:  # pragma: no cover — django-storages < 1.14
    from storages.backends.s3 import S3Boto3Storage as _BaseS3Storage


class MedShareS3Storage(_BaseS3Storage):
    """Médias privés (avatars patients, photos DUT) servis en URL signées."""

    default_acl = None            # pas d'ACL (bucket privé)
    file_overwrite = False        # un nouveau contenu → un nouveau nom
    querystring_auth = True       # URLs signées (lecture privée)
    querystring_expire = 3600     # validité 1 heure