"""
Pré-calcule les empreintes faciales (PatientEncodage) des patients ayant une
photo de profil, pour le moteur réel ONNX (YuNet + ArcFace 512-d).

Usage :
    python manage.py calculer_encodages [--force]

- Lit les photos quelle que soit leur persistance (disque local ou Supabase
  Storage S3) via le champ Django (FieldFile).
- Enregistre un vecteur 512-d par patient (liste de float, JSONField).
- Idempotent : les patients déjà encodés sont ignorés sauf avec ``--force``.
- Les photos sans visage exploitable sont signalées et ignorées (le repli à
  la demande du service essaiera de nouveau au prochain DUT).
"""

import sys
from django.core.management.base import BaseCommand

from users.models import Patient, PatientEncodage


class Command(BaseCommand):
    help = 'Pré-calcule les encodages faciaux 512-d (ONNX) des patients.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Re-calcule même si une empreinte existe déjà.')

    def handle(self, *args, **options):
        from facial_recognition.backend_onnx import est_disponible, encoder_octets

        if not est_disponible():
            self.stderr.write('Le moteur ONNX n\u2019est pas disponible (modèles manquants).')
            sys.exit(1)

        patients = (
            Patient.objects.exclude(photoProfil='')
            .exclude(photoProfil__isnull=True)
            .order_by('numeroPatient')
        )
        existants = {
            e.patient_id for e in PatientEncodage.objects.filter(moteur='onnx').only('patient_id')
        }

        fait = ignores = echecs = 0
        for patient in patients:
            if not options['force'] and patient.pk in existants:
                ignores += 1
                continue
            try:
                octets = patient.photoProfil.read()
                vecteurs = encoder_octets(octets)
            except Exception as exc:
                echecs += 1
                self.stderr.write(f'[{patient.numeroPatient}] échec : {exc}')
                continue
            if len(vecteurs) != 1:
                echecs += 1
                self.stderr.write(
                    f'[{patient.numeroPatient}] aucun visage exploitable'
                    f' ({len(vecteurs)} visage(s)).')
                continue

            vecteur = [float(v) for v in vecteurs[0].tolist()]
            PatientEncodage.objects.update_or_create(
                patient=patient,
                defaults={
                    'moteur': 'onnx',
                    'dimension': len(vecteur),
                    'vecteur': vecteur,
                    'nb_visages': 1,
                },
            )
            fait += 1
            self.stdout.write(f'[{patient.numeroPatient}] {len(vecteur)}-d encodé.')

        self.stdout.write(self.style.SUCCESS(
            f'Terminé : {fait} encodé(s), {ignores} inchangé(s), {echecs} échec(s).'))