"""Tâche planifiée quotidienne : expire les abonnements arrivés à date de fin.

Usage (cron / Windows Task Scheduler) :
    python manage.py expirer_abonnements
"""
from django.core.management.base import BaseCommand

from establishments.services import verifier_abonnements_expires


class Command(BaseCommand):
    help = 'Passe en EXPIRE les abonnements en retard et suspend les établissements concernés.'

    def handle(self, *args, **options):
        suspendus = verifier_abonnements_expires()
        if suspendus:
            self.stdout.write(self.style.WARNING(
                f'{suspendus} établissement(s) suspendu(s) pour abonnement expiré.'))
        else:
            self.stdout.write(self.style.SUCCESS('Aucun abonnement expiré.'))