from django.utils import timezone

from .models import AccesDMP


def _a_accès_actif(patient, etablissement):
    """Retourne True si le patient dispose d'une approbation ACCORDE (non
    expirée, non révoquée) pour l'établissement donné."""
    if etablissement is None:
        return False
    return AccesDMP.objects.filter(
        patient=patient,
        etablissement=etablissement,
        statut=AccesDMP.Statut.ACCORDE,
    ).exists()


def verifier_ou_demander_acces(patient, etablissement, demandeur=None, motif=''):
    """Point d'entrée du consentement soignant avant un acte DMP.

    Retourne (autoriser: bool, acces: AccesDMP|None).
      - Si une approbation active existe → (True, celle-ci).
      - Sinon, crée une demande EN_ATTENTE que le patient devra approuver
        depuis son espace, et retourne (False, la demande).
    """
    actif = AccesDMP.objects.filter(
        patient=patient,
        etablissement=etablissement,
        statut=AccesDMP.Statut.ACCORDE,
    ).first()
    if actif:
        return True, actif

    demande, cree = AccesDMP.objects.get_or_create(
        patient=patient,
        etablissement=etablissement,
        statut=AccesDMP.Statut.EN_ATTENTE,
        defaults={
            'demandeur': demandeur,
            'motif': motif or '',
        },
    )
    if cree:
        # T2 — notifie le patient dès la création de la demande ; les renvois
        # sont limités (bouton « Renvoyer » sur l'écran du soignant).
        demande.notifier_patient()
    return False, demande


def acces_pour_dmp(dmp, etablissement):
    """Approbation active la plus récente du DMP pour un établissement."""
    if dmp is None or etablissement is None:
        return None
    return AccesDMP.objects.filter(
        patient=dmp.patient,
        etablissement=etablissement,
        statut=AccesDMP.Statut.ACCORDE,
    ).first()
