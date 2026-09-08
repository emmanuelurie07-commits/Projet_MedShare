"""Politique de clôture des DUT (addendum 4, T3).

Règle : après 72 h sans correspondance VALIDÉE, un DUT actif passe en statut
EN_ATTENTE_PROLONGEE — jamais de fermeture automatique (réversible). La
clôture définitive reste une décision MANUELLE d'un Médecin (vue cloturer_dut),
toujours journalisée avec un motif dans le JournalAudit.
"""
from datetime import timedelta

from django.utils import timezone


def appliquer_politique_cloture_dut():
    """Bascule en EN_ATTENTE_PROLONGEE les DUT actifs de plus de 72 h sans
    correspondance d'identité validée. Retourne le nombre de DUT basculés."""
    from .models import DossierUrgenceTemporaire, JournalAudit

    seuil = timezone.now() - timedelta(hours=72)
    duts = (
        DossierUrgenceTemporaire.objects
        .filter(
            statut=DossierUrgenceTemporaire.Statut.ACTIF,
            dateCreation__lt=seuil,
        )
        .exclude(recherches_identite__statut='CONFIRMEE')
        .distinct()
    )

    nb = 0
    for dut in duts:
        dut.statut = DossierUrgenceTemporaire.Statut.EN_ATTENTE_PROLONGEE
        dut.save(update_fields=['statut'])
        JournalAudit.objects.create(
            action='DUT_EN_ATTENTE_PROLONGEE',
            description=(
                f'DUT {dut.numeroDUT} sans correspondance validée depuis 72 h : '
                f'passé en EN_ATTENTE_PROLONGEE. Clôture définitive réservée '
                f'au médecin (jamais automatique).'
            ),
            etablissement=dut.etablissement,
        )
        nb += 1
    return nb