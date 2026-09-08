from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.views import LoginView
from django.contrib.auth import update_session_auth_hash
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.views import _contexte_patient

from .forms import (
    ChangerMotDePasseForm, MedShareAuthenticationForm, MotDePasseOublieForm,
    ReinitialiserMotDePasseForm,
)
from .models import Patient, Utilisateur
from .security import generer_jeton_reset, valider_jeton_reset


class MedShareLoginView(LoginView):
    """Login qui redirige chaque profil vers son tableau de bord sécurisé.
    Le jeton d'accès personnel est renouvelé dans le backend."""

    template_name = 'registration/login.html'
    authentication_form = MedShareAuthenticationForm

    def form_valid(self, form):
        # Expiration automatique des abonnements : c'est le moment le plus
        # sûr pour déclencher la vérification quotidienne (en complément de
        # la tâche planifiée ``expirer_abonnements``).
        from establishments.services import verifier_abonnements_expires
        verifier_abonnements_expires()
        # Politique de clôture des DUT (addendum 4, T3) : jamais de clôture
        # automatique, bascule EN_ATTENTE_PROLONGEE après 72 h sans
        # correspondance validée.
        from urgences.services import appliquer_politique_cloture_dut
        appliquer_politique_cloture_dut()

        user = form.get_user()
        # Un personnel d'un établissement suspendu ne peut pas se connecter.
        if hasattr(user, 'personnel_child'):
            etablissement = user.personnel_child.etablissement
            if etablissement is not None and etablissement.statut == 'SUSPENDU':
                messages.error(
                    self.request,
                    'Cet établissement est actuellement suspendu, '
                    'contactez votre administrateur.')
                return redirect('login')

        # Discriminant de modèle pour la session (multi-table inheritance) :
        # évite la collision de pk entre Personnel.idPersonnel et Patient.idPatient.
        response = super().form_valid(form)
        if hasattr(user, 'patient_child'):
            self.request.session['_auth_user_model'] = 'patient'
        elif hasattr(user, 'personnel_child'):
            self.request.session['_auth_user_model'] = 'personnel'
        else:
            self.request.session['_auth_user_model'] = 'utilisateur'

        # Addendum 4 (T4) : une seule session active par compte. Chaque
        # connexion émet une nouvelle clé, enregistrée sur le compte ET dans
        # la session fraîchement créée ; l'ancienne session déconnectera
        # l'ancien appareil à sa prochaine requête (SessionUniqueMiddleware)
        # avec un message explicite.
        import secrets
        ancienne_cle = user.session_active_key
        if not ancienne_cle:
            ancienne_cle = ''
        nouvelle_cle = secrets.token_urlsafe(32)
        user.session_active_key = nouvelle_cle
        user.save(update_fields=['session_active_key'])
        self.request.session['session_active_key'] = nouvelle_cle
        if ancienne_cle:
            try:
                from urgences.models import JournalAudit
                JournalAudit.objects.create(
                    action='SESSION_REMPLACEE',
                    description=f'Connexion plus récente sur ce compte '
                                f'({user.get_full_name() or user.email}) : une '
                                f'session active a été remplacée.',
                    utilisateur=user,
                    etablissement=getattr(user, 'etablissement', None),
                    adresseIP=self.request.META.get('REMOTE_ADDR'),
                )
            except Exception:
                pass

        # État de la double authentification pour cette session (addendum 3) :
        # chaque connexion exige un NOUVEAU code, envoyé par e-mail et jamais
        # affiché à l'écran. Le drapeau « 2fa_requise » n'est armé que par ce
        # formulaire de connexion — c'est le seul point d'entrée des comptes
        # réels en production.
        for cle in ('2fa_valide', '2fa_code_hash', '2fa_code_exp',
                    '2fa_renvois'):
            self.request.session.pop(cle, None)
        if user.is_superuser or getattr(user, 'est_admin_hospital', False):
            self.request.session['2fa_requise'] = True
        else:
            self.request.session.pop('2fa_requise', None)
        return response

    def get_success_url(self):
        user = self.request.user
        if hasattr(user, 'patient_child'):
            return reverse('dashboard_patient', kwargs={'jeton': user.jeton_acces})
        if user.is_superuser or getattr(user, 'est_admin_hospital', False):
            return reverse('superadmin_2fa')
        return reverse('dashboard')


# ──────────────────────────────────────────────
# Double authentification (2FA) par e-mail
# Commune au Super Admin et à l'Administrateur d'établissement.
# Le code est TOUJOURS envoyé par e-mail, jamais affiché à l'écran.
# ──────────────────────────────────────────────
CODE_2FA_DUREE = timedelta(minutes=5)
CODE_2FA_RENVOIS_MAX = 3
# Délai de sécurité entre deux envois de code 2FA (anti-spam e-mail, addendum 4 / T2).
DELAI_2FA_RENVOI = timedelta(seconds=60)


def _generer_code_2fa():
    """Génère un code à 6 chiffres à usage unique."""
    import secrets
    return f'{secrets.randbelow(1_000_000):06d}'


def _est_sensible_2fa(user):
    """Comptes soumis à la double authentification (Super Admin + admin hospital)."""
    return bool(user.is_superuser or getattr(user, 'est_admin_hospital', False))


def _code_2fa_en_cours(request):
    """True si un code 2FA haché et non expiré est déjà en session."""
    hash_ = request.session.get('2fa_code_hash')
    expiration = request.session.get('2fa_code_exp')
    if not hash_ or not expiration:
        return False
    try:
        return timezone.now() <= datetime.fromisoformat(expiration)
    except (TypeError, ValueError):
        return False


def _code_2fa_renvoi_bloque(request):
    """True si un code 2FA a été émis il y a moins de DELAI_2FA_RENVOI
    (anti-spam e-mail : pas d'envoi tous les rafraîchissements)."""
    dernier = request.session.get('2fa_dernier_envoi')
    if not dernier:
        return False
    try:
        return timezone.now() < datetime.fromisoformat(dernier) + DELAI_2FA_RENVOI
    except (TypeError, ValueError):
        return False


def _emettre_code_2fa(request, utilisateur):
    """Génère un code et l'envoie par e-mail. Seul son hachage est conservé
    en session (comparaison seule, jamais réaffichable)."""
    from core.notifications import envoyer_email

    code = _generer_code_2fa()
    request.session['2fa_code_hash'] = make_password(code)
    request.session['2fa_code_exp'] = (
        timezone.now() + CODE_2FA_DUREE).isoformat()
    request.session['2fa_renvois'] = request.session.get('2fa_renvois', 0) + 1
    request.session['2fa_dernier_envoi'] = timezone.now().isoformat()

    sujet = 'Votre code de vérification MedShare'
    corps = (
        f'Bonjour {utilisateur.get_full_name()},\n\n'
        f'Voici votre code de vérification à 6 chiffres : {code}\n\n'
        f'Il reste valable 5 minutes. Si vous n\'êtes pas à l\'origine de '
        f'cette demande, ignorez cet e-mail : votre compte reste protégé.\n\n'
        f'Cordialement,\nL\'équipe MedShare'
    )
    envoyer_email(request, utilisateur.email, sujet, corps)


@login_required
def superadmin_2fa(request):
    """Étape de double authentification : affiche une saisie neutre.
    Le code est envoyé par e-mail à l'ouverture de la page (ou au renvoi),
    jamais présent dans le gabarit ni dans le contexte."""
    if not _est_sensible_2fa(request.user):
        raise Http404('Accès réservé.')
    if request.session.get('2fa_valide'):
        return redirect('dashboard')

    renvoyer = request.method == 'POST' and request.POST.get('renvoyer')
    if renvoyer:
        if _code_2fa_renvoi_bloque(request):
            messages.error(
                request,
                'Patientez une minute avant de demander un nouveau code.')
        elif request.session.get('2fa_renvois', 0) < CODE_2FA_RENVOIS_MAX:
            _emettre_code_2fa(request, request.user)
            messages.success(
                request,
                'Un nouveau code vous a été envoyé par e-mail.')
        else:
            messages.error(
                request,
                'Nombre maximal de renvois atteint. Réessayez dans quelques '
                'minutes.')
        return redirect('superadmin_2fa')

    # Émission initiale uniquement : la page posée puis rechargée ne renvoie
    # pas de code tant que le code précédent n'est pas expiré.
    if not _code_2fa_en_cours(request):
        _emettre_code_2fa(request, request.user)
    return render(request, 'users/superadmin_2fa.html')


@login_required
def superadmin_2fa_verifier(request):
    """Valide le code saisi et débloque l'accès au dashboard pour cette session."""
    if not _est_sensible_2fa(request.user):
        raise Http404('Accès réservé.')
    if request.session.get('2fa_valide'):
        return redirect('dashboard')

    hash_ = request.session.get('2fa_code_hash')
    saisie = (request.POST.get('code') or '').strip()
    if (request.method == 'POST' and hash_ and saisie
            and _code_2fa_en_cours(request)
            and check_password(saisie, hash_)):
        request.session['2fa_valide'] = True
        for cle in ('2fa_code_hash', '2fa_code_exp', '2fa_renvois',
                    '2fa_requise'):
            request.session.pop(cle, None)
        return redirect('dashboard')

    messages.error(request, 'Code invalide ou expiré. Demandez un nouveau code.')
    return render(request, 'users/superadmin_2fa.html', {'erreur': True})


@login_required
def changer_mot_de_passe(request):
    user = request.user
    # Tous les comptes (personnel, patient, superadmin) disposent du champ
    # doitChangerMotDePasse : la vue est libre d'accès pour un changement
    # volontaire, mais le middleware redirige de force à la première connexion.

    if request.method == 'POST':
        form = ChangerMotDePasseForm(user, request.POST)
        if form.is_valid():
            form.save()
            # CRITIQUE : le hash de session dépend du mot de passe. Sans cette
            # mise à jour, Django invalide la session à la requête suivante et
            # l'utilisateur est renvoyé au login juste après avoir changé son
            # mot de passe.
            update_session_auth_hash(request, request.user)
            return redirect('changer_mot_de_passe_succes')
    else:
        form = ChangerMotDePasseForm(user)

    return render(request, 'users/changer_mot_de_passe.html', {'form': form})


@login_required
def changer_mot_de_passe_succes(request):
    """Page de succès après changement obligatoire du mot de passe : gros tick
    vert + bouton direct vers le tableau de bord (plus de retour au login)."""
    return render(request, 'users/changer_mot_de_passe_succes.html')


def _recuperer_patient_par_jeton(jeton):
    """Retourne le patient dont le jeton correspond, ou None.
    La vérification est faite côté requête : jamais d'URL publiquement prévisible."""
    try:
        return Patient.objects.get(jeton_acces=jeton)
    except (Patient.DoesNotExist, ValueError):
        return None


@login_required
def dashboard_patient(request, jeton):
    """Dashboard isolé du patient, accessible UNIQUEMENT via son jeton
    personnel renouvelé au login. Tout autre accès croisé est refusé."""
    patient = _recuperer_patient_par_jeton(jeton)
    if patient is None or request.user.pk != patient.pk:
        raise Http404('Accès refusé.')
    context = _contexte_patient(request.user)
    return render(request, 'core/dashboard_patient.html', context)


# ──────────────────────────────────────────────
# Réinitialisation du mot de passe « oublié »
# ──────────────────────────────────────────────
def mot_de_passe_oublie(request):
    """Demande un lien de réinitialisation par e-mail.

    La réponse est volontairement identique que le compte existe ou non
    (anti-énumération des comptes)."""
    if request.method == 'POST':
        form = MotDePasseOublieForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            utilisateur = Utilisateur.objects.filter(email__iexact=email).first()
            if utilisateur is not None:
                jeton = generer_jeton_reset(utilisateur)
                lien = request.build_absolute_uri(reverse(
                    'reinitialiser_mot_de_passe', kwargs={'jeton': jeton}))
                send_mail(
                    'Réinitialisation de votre mot de passe MedShare',
                    f'Bonjour {utilisateur.get_full_name()},\n\n'
                    'Vous (ou quelqu\'un utilisant votre adresse) venez de '
                    'demander la réinitialisation de votre mot de passe.\n\n'
                    'Cliquez sur le lien ci-dessous pour en choisir un nouveau '
                    f'(valable 24 heures) :\n\n{lien}\n\n'
                    'Si vous n\'êtes pas à l\'origine de cette demande, ignorez '
                    'simplement cet e-mail : votre mot de passe reste inchangé.',
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
            messages.success(
                request,
                'Si cette adresse est associée à un compte MedShare, '
                'un lien de réinitialisation vient d\'être envoyé.')
            return redirect('login')
    else:
        form = MotDePasseOublieForm()
    return render(request, 'users/mot_de_passe_oublie.html', {'form': form})


def reinitialiser_mot_de_passe(request, jeton):
    """Choix du nouveau mot de passe une fois le lien signé validé."""
    utilisateur = valider_jeton_reset(jeton)
    if utilisateur is None:
        messages.error(
            request,
            'Ce lien est invalide ou a expiré (24 h). '
            'Merci de refaire une demande de réinitialisation.')
        return redirect('login')

    if request.method == 'POST':
        form = ReinitialiserMotDePasseForm(utilisateur, request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Votre mot de passe a été réinitialisé. Vous pouvez '
                'maintenant vous connecter.')
            return redirect('login')
    else:
        form = ReinitialiserMotDePasseForm(utilisateur)
    return render(request, 'users/reinitialiser_mot_de_passe.html', {'form': form})
