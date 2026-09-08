"""Générateurs unifiés MedShare (itération 3).

Deux familles de fonctions, cohérentes partout :

1. Mots de passe provisoires  — un seul format lisible, sans ponctuation et
   sans caractères ambigus (0/O, 1/l/I exclus), longueur aléatoire 10-12.
2. Identifiants « métier » — format lisible, mémorisable et professionnel :
   PRE-ANNEE-NNNN  (ex. PAT-2026-0143, PER-2026-0027, DUT-2026-0009).

Tout appel direct à ``secrets.token_urlsafe`` ou à ``string.punctuation``
pour générer un mot de passe provisoire doit passer par :
    from core.generateurs import generer_mot_de_passe_provisoire
"""
import secrets
from datetime import datetime

# Alphabet du mot de passe provisoire : minuscules + majuscules + chiffres,
# sans caractères ambigus (0/O et 1/l/I exclus) et sans ponctuation.
_MINUSCULES = 'abcdefghjkmnpqrstuvwxyz'      # exclut i, l, o
_MAJUSCULES = 'ABCDEFGHJKMNPQRSTUVWXYZ'      # exclut I, L, O
_CHIFFRES = '23456789'                        # exclut 0 et 1
_ALPHABET = _MINUSCULES + _MAJUSCULES + _CHIFFRES


def generer_mot_de_passe_provisoire(longueur=None):
    """Mot de passe provisoire lisible, sans caractères ambigus ni ponctuation.

    Par défaut la longueur est tirée aléatoirement entre 10 et 12 caractères
    (le paramètre accepte une valeur explicite pour les tests). Il contient
    toujours au moins une minuscule, une majuscule et un chiffre.
    """
    if longueur is None:
        longueur = secrets.choice(range(10, 13))
    if longueur < 8:
        raise ValueError('Longueur minimale : 8 caractères.')
    caracteres = [
        secrets.choice(_MINUSCULES),
        secrets.choice(_MAJUSCULES),
        secrets.choice(_CHIFFRES),
    ]
    caracteres += [secrets.choice(_ALPHABET) for _ in range(longueur - 3)]
    secrets.SystemRandom().shuffle(caracteres)
    return ''.join(caracteres)


def _prochain_numero_sequentiel(prefixe, queryset, champ):
    """Retourne ``PREFIXE-ANNEE-NNNN`` unique, séquence continue sur 4 chiffres.

    La séquence est basée sur les identifiants existants de la même année :
    si un numéro est déjà pris (suppression manuelle, collision), on avance
    jusqu'à trouver une valeur libre.
    """
    annee = datetime.now().year
    prefixe_annee = f'{prefixe}-{annee}-'
    existants = queryset.filter(**{f'{champ}__startswith': prefixe_annee}).count()
    while True:
        existants += 1
        numero = f'{prefixe_annee}{existants:04d}'
        if not queryset.filter(**{champ: numero}).exists():
            return numero


def generer_numero_patient():
    from users.models import Patient
    return _prochain_numero_sequentiel('PAT', Patient.objects.all(), 'numeroPatient')


def generer_matricule():
    from users.models import Personnel
    return _prochain_numero_sequentiel('PER', Personnel.objects.all(), 'matricule')


def generer_matricule_admin():
    from users.models import Personnel
    return _prochain_numero_sequentiel('ADM', Personnel.objects.all(), 'matricule')


def generer_numero_dut():
    from urgences.models import DossierUrgenceTemporaire
    return _prochain_numero_sequentiel('DUT', DossierUrgenceTemporaire.objects.all(), 'numeroDUT')