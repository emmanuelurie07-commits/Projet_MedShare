"""Logique métier interservices (itération 3, addendum 2).

Concentre les vérifications transverses qui doivent pouvoir être déclenchées
aussi bien par une tâche planifiée quotidienne que par la connexion d'un
utilisateur.
"""


def verifier_abonnements_expires():
    """Expiration automatique des abonnements.

    Tout abonnement ACTIF dont la date de fin est dépassée (sans
    renouvellement enregistré) passe à EXPIRE, puis l'établissement
    concerné est suspendu avec le motif ABONNEMENT_EXPIRE.
    Retourne le nombre d'établissements suspendus.
    """
    from django.utils import timezone

    from urgences.models import JournalAudit

    from .models import Abonnement, Etablissement

    today = timezone.now().date()
    suspendus = 0
    abonnements = Abonnement.objects.select_related('etablissement').filter(
        statut='ACTIF', dateFin__lt=today)
    for abonnement in abonnements:
        abonnement.expirer()
        etablissement = abonnement.etablissement
        if etablissement.statut != 'SUSPENDU':
            etablissement.suspendre(motif='ABONNEMENT_EXPIRE')
            JournalAudit.objects.create(
                action='SUSPENSION_AUTO_ABONNEMENT',
                description=(f'Abonnement de {etablissement.nom} expiré '
                             f'le {abonnement.dateFin} — établissement '
                             f'suspendu automatiquement.'),
                etablissement=etablissement,
            )
            suspendus += 1
    return suspendus