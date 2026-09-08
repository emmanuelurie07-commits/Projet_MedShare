from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.middleware import AuthenticationMiddleware as _AuthenticationMiddleware
from django.shortcuts import redirect
from django.utils import timezone
from datetime import datetime, timedelta

from .backends import set_auth_model


class MedShareAuthenticationMiddleware(_AuthenticationMiddleware):
    """AuthenticationMiddleware MedShare : rend le marqueur de modèle
    (_auth_user_model) disponible pour ``MedShareAuthBackend.get_user``.

    Sans ce marqueur, les pk de Personnel et de Patient (deux AutoField
    indépendants) peuvent coïncider et provoquer une erreur d'identification
    des sessions (multi-table inheritance).

    NB : le marqueur n'est PAS remis à None en fin de process_request : Django
    résout l'utilisateur paresseusement (SimpleLazyObject) à la première
    lecture de ``request.user``, c'est-à-dire après le process_request.
    L'instruction suivante du process_request réécrit (ou efface) toujours
    le marqueur, il ne peut donc pas fuir d'une requête à l'autre."""

    def process_request(self, request):
        set_auth_model(request.session.get('_auth_user_model', None))
        return super().process_request(request)


class InactiviteMiddleware:
    """Déconnecte automatiquement un utilisateur après une période d'inactivité
    (configurable via INACTIVITE_MINUTES, 30 minutes par défaut).

    Horodatage de la dernière activité conservé en session ; les actions de
    l'utilisateur (vues authentifiées) le rafraîchissent naturellement."""

    SEUIL = timedelta(minutes=getattr(settings, 'INACTIVITE_MINUTES', 30))
    EXEMPT_URLS = [
        '/accounts/login/', '/accounts/logout/', '/static/', '/media/',
        '/compte/changer-mot-de-passe/', '/compte/superadmin/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not any(
                request.path.startswith(url) for url in self.EXEMPT_URLS):
            try:
                derniere_activite = datetime.fromisoformat(
                    request.session.get('_derniere_activite', ''))
            except (TypeError, ValueError):
                derniere_activite = None
            if derniere_activite is not None and \
                    timezone.now() - derniere_activite > self.SEUIL:
                logout(request)
                messages.info(
                    request,
                    'Session expirée par inactivité. Connectez-vous à nouveau.')
                return redirect('login')
            request.session['_derniere_activite'] = timezone.now().isoformat()
        return self.get_response(request)


class SessionUniqueMiddleware:
    """Addendum 4 (T4) : une seule session active par compte.

    Chaque connexion (MedShareLoginView) génère une clé `session_active_key`
    : elle est enregistrée sur le compte utilisateur (DB) ET dans la session
    nouvellement créée. Si la clé conservée dans une session ne correspond
    plus à celle du compte, c'est qu'une connexion plus récente a eu lieu sur
    un autre appareil : cette session est alors déconnectée proprement avec
    un message explicite, puis l'appareil est redirigé vers le login.

    L'ancienne session n'est PAS détruite à la connexion : on laisse ce
    middleware déconnecter l'ancien appareil à sa prochaine requête, afin de
    lui afficher le message au lieu de le laisser « silencieusement » anonyme.
    """
    EXEMPT_URLS = [
        '/accounts/login/', '/accounts/logout/', '/static/', '/media/',
        '/compte/changer-mot-de-passe/', '/compte/superadmin/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (user.is_authenticated
                and not any(request.path.startswith(url)
                            for url in self.EXEMPT_URLS)):
            cle_compte = getattr(user, 'session_active_key', '')
            cle_session = request.session.get('session_active_key', '')
            if cle_compte and cle_session and cle_compte != cle_session:
                logout(request)
                messages.warning(
                    request,
                    'Votre session a été remplacée par une connexion plus '
                    'récente sur un autre appareil. Reconnectez-vous ici.')
                return redirect('login')
        return self.get_response(request)


class EtablissementSuspensionMiddleware:
    """Bloque l'accès de tout le personnel d'un établissement suspendu.

    Couvre les sessions déjà actives : dès qu'un établissement passe en
    SUSPENDU (expiration d'abonnement ou décision du Super Admin), chaque
    requête du personnel concerné est interrompue avec un message clair.
    Le super administrateur n'est jamais bloqué.
    """
    EXEMPT_URLS = ['/admin/', '/static/', '/media/', '/accounts/logout/',
                   '/compte/changer-mot-de-passe/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (user.is_authenticated
                and not getattr(user, 'is_superuser', False)
                and not any(request.path.startswith(url)
                            for url in self.EXEMPT_URLS)):
            etablissement = getattr(user, 'etablissement', None)
            if etablissement is not None and etablissement.statut == 'SUSPENDU':
                logout(request)
                messages.error(
                    request,
                    'Cet établissement est actuellement suspendu, '
                    'contactez votre administrateur.')
                return redirect('login')
        return self.get_response(request)


class ChangerMotDePasseMiddleware:
    """
    Redirige vers le changement de mot de passe si l'utilisateur doit le changer.
    Exclut les pages de changement de mot de passe, de 2FA et de déconnexion.
    """
    EXEMPT_URLS = ['/compte/changer-mot-de-passe/', '/accounts/logout/',
                    '/admin/', '/static/', '/media/', '/compte/superadmin/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and getattr(request.user, 'doitChangerMotDePasse', False):
            if not any(request.path.startswith(url) for url in self.EXEMPT_URLS):
                messages.warning(request, 'Vous devez changer votre mot de passe avant de continuer.')
                return redirect('changer_mot_de_passe')
        return self.get_response(request)


class RBACMiddleware:
    """
    Charge les rôles de l'utilisateur dans la requête.
    Ajoute request.user_roles pour faciliter les vérifications.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if hasattr(request.user, 'role'):
                request.user_roles = {request.user.role.nomRole} if request.user.role else set()
                request.user_role = request.user.role
            else:
                request.user_roles = set()
                request.user_role = None
            request.user_etablissement = getattr(request.user, 'etablissement', None)
        else:
            request.user_roles = set()
            request.user_etablissement = None
        return self.get_response(request)


class MultiEtablissementMiddleware:
    """
    Filtre les requêtes pour n'autoriser l'accès qu'aux données
    de l'établissement de l'utilisateur.
    Stocke l'établissement courant dans request.etablissement_courant.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.etablissement_courant = getattr(request.user, 'etablissement', None)
        else:
            request.etablissement_courant = None
        return self.get_response(request)


class DeuxFacteursMiddleware:
    """Impose la double authentification (2FA) après une connexion réelle par le
    formulaire ``MedShareLoginView`` — qui arme le drapeau de session
    ``2fa_requise`` — pour le Super Admin et l'Administrateur d'établissement.

    Le code étant envoyé par e-mail (jamais affiché à l'écran), la page 2FA
    (et la page de changement de mot de passe) sont exemptées pour éviter
    tout blocage. Les comptes connectés hors formulaire (ex. sessions de test)
    ne disposent pas du drapeau : ce middleware ne les concerne pas.
    """
    EXEMPT_URLS = [
        '/static/', '/media/', '/accounts/login/', '/accounts/logout/',
        '/compte/superadmin/', '/compte/changer-mot-de-passe/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (user.is_authenticated
                and (user.is_superuser or getattr(user, 'est_admin_hospital', False))
                and request.session.get('2fa_requise')
                and not request.session.get('2fa_valide')
                and not any(request.path.startswith(url)
                            for url in self.EXEMPT_URLS)):
            return redirect('superadmin_2fa')
        return self.get_response(request)