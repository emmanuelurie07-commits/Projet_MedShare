"""
Téléverse les médias existants (photos patients, photos DUT) vers Supabase
Storage (ou tout stockage par défaut configuré). Idempotent : un fichier déjà
présent dans le bucket n'est pas renvoyé.

À exécuter UNE SEULE FOIS après avoir créé le bucket et posé les variables :
    MEDIA_STORAGE=s3
    AWS_S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_STORAGE_BUCKET_NAME, AWS_S3_REGION_NAME

Les lignes DB (photoProfil / DUT.photo) stockent déjà le nom relatif du
fichier — identique entre le disque local et le bucket : aucun UPDATE requis.

ATTENTION — pourquoi on lit explicitement le disque local :
`MEDIA_ROOT` désigne le dossier local (BASE_DIR/media en développement) et la
source des fichiers à envoyer. On ne peut pas utiliser `champ.open()` ici :
une fois `MEDIA_STORAGE=s3` activé, le champ pointe lui aussi vers S3, où le
fichier n'existe pas encore — la commande echouerait donc systematiquement
avec « File does not exist ».
"""

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Téléverse les photos patients/DUT existantes vers le stockage S3 configuré.'

    def handle(self, *args, **options):
        from users.models import Patient
        from urgences.models import DossierUrgenceTemporaire

        racine = Path(settings.MEDIA_ROOT)
        if settings.STORAGES['default']['BACKEND'] == \
                'django.core.files.storage.FileSystemStorage':
            self.stderr.write(
                'MEDIA_STORAGE n\'est pas sur s3 : cible et source seraient le '
                'même dossier, rien à téléverser. Posez MEDIA_STORAGE=s3 et '
                'les variables AWS_*, puis relancez.')
            return

        noms = set()
        envoyes, deja_presents, absents, erreurs = 0, 0, 0, 0

        sources = [p.photoProfil for p in Patient.objects.exclude(
            photoProfil='').exclude(photoProfil__isnull=True)]
        sources += [d.photo for d in DossierUrgenceTemporaire.objects.filter(
            photo='').exclude(photo__isnull=True)]

        for champ in sources:
            nom = champ.name
            if not nom or nom in noms:
                continue
            noms.add(nom)
            try:
                if default_storage.exists(nom):
                    deja_presents += 1
                    continue
            except Exception as exc:
                erreurs += 1
                self.stderr.write(f'[{nom}] vérification impossible : {exc}')
                continue

            chemin_local = racine / nom
            if not chemin_local.is_file():
                absents += 1
                self.stderr.write(f'[{nom}] absent du dossier local '
                                  f'{racine} — ignoré')
                continue
            try:
                donnees = chemin_local.read_bytes()
                default_storage.save(nom, ContentFile(donnees))
                envoyes += 1
            except Exception as exc:
                erreurs += 1
                self.stderr.write(f'[{nom}] échec : {exc}')

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {envoyes} envoyé(s), {deja_presents} déjà présent(s), '
            f'{absents} absent(s) du disque local, {erreurs} échec(s).'))