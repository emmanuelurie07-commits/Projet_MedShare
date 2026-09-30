from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AccesDMP, DossierMedicalPartage


def creer_dmp_patient(patient):
    """Crée le DMP d'un patient et lui attribue un numéro unique.

    Point d'entrée UNIQUE de création d'un DMP : utilisé par la création de
    patient depuis l'application (dmp.views) comme par les commandes de
    remplissage (seed_patients), afin qu'aucun patient ne reste sans dossier.

    Le numéro ``DMP-<date>-<rang>`` étant unique, on réessaie avec un suffixe
    en cas de collision (deux créations quasi simultanées).
    """
    jour = timezone.now().strftime('%Y%m%d')
    for suffixe in range(0, 100):
        numero = f'DMP-{jour}-{DossierMedicalPartage.objects.count() + 1 + suffixe:04d}'
        if DossierMedicalPartage.objects.filter(numeroDMP=numero).exists():
            continue
        try:
            with transaction.atomic():
                return DossierMedicalPartage.objects.create(
                    patient=patient, numeroDMP=numero)
        except IntegrityError:
            # Collision sur la contrainte unique : on retente avec un autre rang.
            continue
    raise RuntimeError(
        f'Impossible d\'attribuer un numéro de DMP à {patient} '
        f'(trop de dossiers créés simultanément).')


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
