"""Briques de sécurité de l'authentification MedShare (itération 3, tâche T8).

- Verrouillage temporaire du compte après 5 échecs de connexion consécutifs
  (15 minutes) — protège Personnel, Patient et Utilisateur « pur ».
- Réinitialisation du mot de passe « oublié » : lien signé (TimestampSigner)
  à usage unique et limité à 24 h, lié au hachage courant du mot de passe
  (tout changement de mot de passe invalide les liens non utilisés).
"""
from datetime import timedelta
import hashlib

from django.core import signing
from django.utils import timezone

NB_ECHECS_MAX = 5
DUREE_VERROUILLAGE = timedelta(minutes=15)
DUREE_VALIDITE_LIEN_RESET = 60 * 60 * 24  # 24 heures

_SEL_LIEN_RESET = 'medshare.reinitialisation-mot-de-passe'


# ──────────────────────────────────────────────
# Verrouillage après échecs successifs
# ──────────────────────────────────────────────
def est_compte_verrouille(utilisateur):
    """Un compte est verrouillé tant que verrouillageJusqua est dans le futur."""
    if utilisateur.verrouillageJusqua is None:
        return False
    return timezone.now() < utilisateur.verrouillageJusqua


def enregistrer_echec_connexion(utilisateur):
    """Compte un échec ; au 5e échec, verrouille le compte 15 minutes."""
    utilisateur.nbEchecsConnexion += 1
    if utilisateur.nbEchecsConnexion >= NB_ECHECS_MAX:
        utilisateur.verrouillageJusqua = timezone.now() + DUREE_VERROUILLAGE
        utilisateur.nbEchecsConnexion = 0
    utilisateur.save(update_fields=['nbEchecsConnexion', 'verrouillageJusqua'])


def reinitialiser_echecs_connexion(utilisateur):
    """Après une connexion réussie (ou une réinitialisation de mot de passe),
    efface le compteur d'échecs et tout verrouillage en cours."""
    if utilisateur.nbEchecsConnexion or utilisateur.verrouillageJusqua:
        utilisateur.nbEchecsConnexion = 0
        utilisateur.verrouillageJusqua = None
        utilisateur.save(update_fields=['nbEchecsConnexion', 'verrouillageJusqua'])


# ──────────────────────────────────────────────
# Réinitialisation du mot de passe « oublié »
# ──────────────────────────────────────────────
def _signer():
    return signing.TimestampSigner(salt=_SEL_LIEN_RESET)


def _empreinte_mot_de_passe(utilisateur):
    """Empreinte courte du hachage courant du mot de passe (SHA-256)."""
    return hashlib.sha256(utilisateur.password.encode('utf-8')).hexdigest()[:12]


def _valeur_jeton(utilisateur):
    """Valeur signée : identité + empreinte du hachage actuel du mot de passe.
    L'empreinte lie le lien au mot de passe courant : dès qu'il change,
    les liens précédents deviennent invalides (usage unique de fait)."""
    return f'{utilisateur.pk}:{utilisateur.email}:{_empreinte_mot_de_passe(utilisateur)}'


def generer_jeton_reset(utilisateur):
    """Produit le jeton pour l'URL `/compte/reinitialiser/<jeton>/`."""
    return _signer().sign(_valeur_jeton(utilisateur))


def valider_jeton_reset(jeton, max_age=DUREE_VALIDITE_LIEN_RESET):
    """Reconstitue l'utilisateur depuis un jeton valide, sinon None.

    Le lien est rejeté si la signature est altérée, si plus de 24 h se sont
    écoulées, ou si le mot de passe a changé depuis l'envoi du lien."""
    from .models import Utilisateur

    try:
        valeur = _signer().unsign(jeton, max_age=max_age)
        pk, email, empreinte = valeur.rsplit(':', 2)
        utilisateur = Utilisateur.objects.get(pk=pk, email__iexact=email)
    except (signing.BadSignature, signing.SignatureExpired, ValueError, OverflowError):
        return None
    except Utilisateur.DoesNotExist:
        return None
    if _empreinte_mot_de_passe(utilisateur) != empreinte:
        return None
    return utilisateur