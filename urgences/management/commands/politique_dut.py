"""Tâche planifiée quotidienne : politique de clôture des DUT (addendum 4, T3).

Usage (cron / Windows Task Scheduler) :
    python manage.py politique_dut
"""
from django.core.management.base import BaseCommand

from urgences.services import appliquer_politique_cloture_dut


class Command(BaseCommand):
    help = ('Passe en EN_ATTENTE_PROLONGEE les DUT actifs de plus de 72 h '
            'sans correspondance d\'identité validée (jamais de clôture auto).')

    def handle(self, *args, **options):
        bascules = appliquer_politique_cloture_dut()
        if bascules:
            self.stdout.write(self.style.WARNING(
                f'{bascules} DUT passé(s) en EN_ATTENTE_PROLONGEE.'))
        else:
            self.stdout.write(self.style.SUCCESS('Aucun DUT à basculer.'))