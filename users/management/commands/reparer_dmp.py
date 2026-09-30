"""Répare les patients dépourvus de Dossier Médical Partagé.

Usage :
    python manage.py reparer_dmp [--apercu]

Pourquoi : la commande ``seed_patients`` créait les comptes patients sans leur
ouvrir de DMP (alors que la création de patient depuis l'application le fait).
Résultat : 101 patients sur 102 n'avaient aucun dossier, leur espace affiche
« Dossier non disponible » et le partage entre établissements est impossible.

La commande est idempotente : elle ne touche que les patients réellement
dépourvus de DMP.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from dmp.services import creer_dmp_patient
from users.models import Patient


class Command(BaseCommand):
    help = ('Crée le DMP manquant des patients qui n\'en ont pas '
            '(répare les comptes créés par seed_patients).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--apercu', action='store_true',
            help='Liste les patients concernés sans rien écrire.')

    def handle(self, *args, **options):
        sans_dmp = (Patient.objects
                    .annotate(nb_dmp=Count('dmp'))
                    .filter(nb_dmp=0)
                    .order_by('pk'))
        total = sans_dmp.count()

        if options['apercu']:
            self.stdout.write(f'{total} patient(s) sans DMP :')
            for patient in sans_dmp[:50]:
                self.stdout.write(f'  - {patient.numeroPatient} '
                                  f'{patient.nom} {patient.prenom} '
                                  f'<{patient.email}>')
            if total > 50:
                self.stdout.write(f'  … et {total - 50} autre(s).')
            return

        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                'Aucun patient sans DMP — rien à réparer.'))
            return

        crees = 0
        echecs = []
        for patient in sans_dmp:
            try:
                creer_dmp_patient(patient)
                crees += 1
            except Exception as e:  # noqa: BLE001 — on continue le reste
                echecs.append(f'{patient.numeroPatient} : {e}')

        self.stdout.write(self.style.SUCCESS(
            f'{crees} DMP créé(s) pour {crees} patient(s) sans dossier.'))
        for ligne in echecs:
            self.stdout.write(self.style.ERROR(f'  ÉCHEC {ligne}'))
        if echecs:
            raise SystemExit(1)
