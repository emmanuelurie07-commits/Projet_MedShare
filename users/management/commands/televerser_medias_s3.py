"""
Téléverse les médias existants (photos patients, photos DUT) vers Supabase
Storage (ou tout stockage par défaut configuré). Idempotent : le backend
S3Boto3Storage de django-storages ignore les fichiers déjà présents.

À exécuter UNE SEULE FOIS après avoir créé le bucket et posé les variables :
    MEDIA_STORAGE=s3
    AWS_S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_STORAGE_BUCKET_NAME, AWS_S3_REGION_NAME

Les lignes DB (photoProfil / DUT.photo) stockent déjà le nom relatif du
fichier — identique entre le disque local et le bucket : aucun UPDATE requis.
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Téléverse les photos patients/DUT existantes vers le stockage S3 configuré.'

    def handle(self, *args, **options):
        from users.models import Patient
        from urgences.models import DossierUrgenceTemporaire

        noms = set()

        champables = [p.photoProfil for p in Patient.objects.exclude(
            photoProfil='').exclude(photoProfil__isnull=True)]
        champables += [d.photo for d in DossierUrgenceTemporaire.objects.filter(
            photo='').exclude(photo__isnull=True)]

        envoyes, deja_presents, erreurs = 0, 0, 0
        for champ in champables:
            if champ.name in noms or not champ.name:
                continue
            noms.add(champ.name)
            try:
                if default_storage.exists(champ.name):
                    deja_presents += 1
                    continue
                champ.open('rb')
                default_storage.save(champ.name, champ)
                envoyes += 1
            except Exception as exc:
                erreurs += 1
                self.stderr.write(f'[{champ.name}] échec : {exc}')

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {envoyes} envoyé(s), {deja_presents} déjà présent(s), '
            f'{erreurs} échec(s).'))