"""WhiteNoise MedShare : sert les fichiers STATIC_ROOT ET le dossier MEDIA_ROOT
(photos des patients) lorsque DEBUG=False.

En production Django ne sert aucun fichier lui-même ; WhiteNoise, monté après
SecurityMiddleware, sert ``/static/`` (compilé par collectstatic) et, grâce à
ce sous-type, ``/media/`` directement depuis le disque de l'hébergeur, sans
collectstatic supplémentaire (les uploads apparaissent instantanément).
"""
from django.conf import settings

from whitenoise.middleware import WhiteNoiseMiddleware


class MedShareWhiteNoise(WhiteNoiseMiddleware):
    def __init__(self, get_response):
        super().__init__(get_response)
        # Sert aussi le dossier média configuré (MEDIA_ROOT), à la racine
        # MEDIA_URL — indispensable pour afficher les photos des Patients.
        self.add_files(settings.MEDIA_ROOT, prefix=settings.MEDIA_URL)