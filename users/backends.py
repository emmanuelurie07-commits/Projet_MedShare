"""Backend d'authentification MedShare.

L'auth Django ne porte que sur AUTH_USER_MODEL = Personnel.
Ce backend permet en plus l'authentification d'un Patient et vérifie
que le compte est actif avant d'autoriser la connexion.

Identité des sessions (multi-table inheritance) :
Patient.idPatient et Personnel.idPersonnel sont deux AutoField indépendants
qui peuvent TOUS deux valoir 1. Sans discrimination, ``get_user`` rechargerait
parfois un Personnel pour la session d'un Patient (collision de pk). On stocke
donc, lors du login (``MedShareLoginView``), un marqueur de modèle dans la
session (``_auth_user_model``) ; un middleware dédié le rend disponible à
``get_user`` via un stockage local au thread.
"""
import threading

from django.contrib.auth.backends import ModelBackend

from .models import Patient, Personnel, Utilisateur


_auth_user_model_local = threading.local()


def set_auth_model(marker):
    """Marqueur seul (patient/personnel/utilisateur) ou None."""
    _auth_user_model_local.model = marker


class MedShareAuthBackend(ModelBackend):
    """Authentifie soit un Personnel (via l'auth standard), soit un Patient,
    soit un Utilisateur « pur » (super administrateur de la plateforme)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email')
        if username is None or password is None:
            return None

        from .security import (enregistrer_echec_connexion, est_compte_verrouille,
                               reinitialiser_echecs_connexion)

        # Compte cible résolu sur la table commune Utilisateur (sert au
        # verrouillage ; Personnel, Patient et Utilisateur partagent cette lignée).
        try:
            cible = Utilisateur.objects.get(email__iexact=username)
        except Utilisateur.DoesNotExist:
            cible = None

        # Compte verrouillé : aucun mot de passe n'est accepté, on n'expose
        # même pas la possibilité de tenter le moindre hachage.
        if cible is not None and est_compte_verrouille(cible):
            return None

        # Tentative privilégiée : le personnel (sujet de l'auth Django)
        result = super().authenticate(request, username=username, password=password, **kwargs)
        if result is not None:
            reinitialiser_echecs_connexion(result)
            result.regenerer_jeton()
            return result

        # Sinon, tente le patient
        try:
            patient = Patient.objects.get(email__iexact=username)
        except Patient.DoesNotExist:
            patient = None
        if patient is not None and patient.check_password(password) and self.user_can_authenticate(patient):
            reinitialiser_echecs_connexion(patient)
            patient.regenerer_jeton()
            return patient

        # Enfin, tente un utilisateur « pur » (ex. super administrateur SaaS)
        try:
            utilisateur = Utilisateur.objects.get(email__iexact=username)
        except Utilisateur.DoesNotExist:
            utilisateur = None
        if (utilisateur is not None
                and utilisateur.check_password(password)
                and self.user_can_authenticate(utilisateur)):
            reinitialiser_echecs_connexion(utilisateur)
            utilisateur.regenerer_jeton()
            return utilisateur

        # Échec : seuls les comptes existants alimentent le compteur de verrouillage.
        if cible is not None:
            enregistrer_echec_connexion(cible)
        return None

    def get_user(self, user_id):
        """Recharge l'utilisateur depuis la session. Le marqueur de modèle
        stocké au login (via MedShareAuthenticationMiddleware) lève
        l'ambiguïté des pk entre Personnel/Patient (multi-table)."""
        marker = getattr(_auth_user_model_local, 'model', None)

        if marker == 'patient':
            try:
                user = Patient._default_manager.get(pk=user_id)
            except Patient.DoesNotExist:
                return None
            return user if self.user_can_authenticate(user) else None

        if marker == 'personnel':
            try:
                user = Personnel._default_manager.get(pk=user_id)
            except Personnel.DoesNotExist:
                return None
            return user if self.user_can_authenticate(user) else None

        if marker == 'utilisateur':
            try:
                user = Utilisateur._default_manager.get(pk=user_id)
            except Utilisateur.DoesNotExist:
                return None
            return user if self.user_can_authenticate(user) else None

        # Comportement historique (sans marqueur) : on essaie Personnel,
        # puis Patient, puis Utilisateur pur.
        for model in (Personnel, Patient, Utilisateur):
            try:
                user = model._default_manager.get(pk=user_id)
            except model.DoesNotExist:
                continue
            if self.user_can_authenticate(user):
                return user
            return None
        return None

    def user_can_authenticate(self, user):
        # réutilise le comportement standard (statutCompte/is_active)
        return super().user_can_authenticate(user)