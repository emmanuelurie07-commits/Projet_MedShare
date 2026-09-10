from django.contrib import messages
from django.contrib.auth.decorators import login_required
from users.decorators import admin_etablissement_required_strict, block_superadmin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.generateurs import generer_matricule, generer_mot_de_passe_provisoire
from users.models import Personnel, Role

from .forms import CandidatureDecisionForm, CandidatureForm
from .models import Candidature


# ──────────────────────────────────────────────
# Soumission de candidature (publique)
# ──────────────────────────────────────────────
def soumettre_candidature(request):
    if request.method == 'POST':
        form = CandidatureForm(request.POST)
        if form.is_valid():
            candidature = form.save()
            messages.success(request,
                f'Candidature soumise avec succès ! Référence : #{candidature.idCandidature}. '
                f'Vous recevrez une réponse par e-mail.')
            return redirect('candidature_confirmation', pk=candidature.pk)
    else:
        form = CandidatureForm()
    return render(request, 'establishments/soumettre_candidature.html', {'form': form})


def candidature_confirmation(request, pk):
    candidature = get_object_or_404(Candidature, pk=pk)
    return render(request, 'establishments/candidature_confirmation.html',
                  {'candidature': candidature})


def consulter_candidature(request):
    """Rechercher une candidature par email pour consulter son statut."""
    candidature = None
    email = request.GET.get('email', '')
    if email:
        candidatures = Candidature.objects.filter(email=email).order_by('-dateSoumission')
        if candidatures.exists():
            candidature = candidatures.first()
    return render(request, 'establishments/consulter_candidature.html',
                  {'candidature': candidature, 'email': email})


# ──────────────────────────────────────────────
# Gestion des candidatures (admin établissement)
# ──────────────────────────────────────────────
@login_required
@admin_etablissement_required_strict
def gestion_candidatures(request):
    etablissement = getattr(request.user, 'etablissement', None)
    if etablissement:
        candidatures = Candidature.objects.filter(
            etablissement=etablissement, statut='EN_ATTENTE'
        ).order_by('-dateSoumission')
    else:
        candidatures = Candidature.objects.filter(statut='EN_ATTENTE').order_by('-dateSoumission')
    return render(request, 'establishments/gestion_candidatures.html',
                  {'candidatures': candidatures})


@login_required
@admin_etablissement_required_strict
def detail_candidature(request, pk):
    candidature = get_object_or_404(Candidature, pk=pk)
    if request.method == 'POST':
        form = CandidatureDecisionForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            if decision == 'ACCEPTEE':
                personnel, mode = _accepter_candidature(request, candidature, form.cleaned_data)
                if personnel is not None:
                    suffixe = ('Compte personnel créé.' if mode == 'cree'
                               else 'Compte rattaché à son nouvel établissement (mutation).')
                    messages.success(request,
                        f'Candidature de {candidature.prenom} {candidature.nom} '
                        f'acceptée. {suffixe}')
            else:
                motif = form.cleaned_data.get('motifRefus', '')
                candidature.refuser(motif)
                _notifier_refus(candidature, motif)
                messages.warning(request,
                    f'Candidature de {candidature.prenom} {candidature.nom} refusée.')
            return redirect('gestion_candidatures')
    else:
        form = CandidatureDecisionForm()
    return render(request, 'establishments/detail_candidature.html',
                  {'candidature': candidature, 'form': form})


def _accepter_candidature(request, candidature, data):
    """Accepte une candidature.

    - Si la personne n'a encore aucun compte Personnel : on crée le compte
      (identifiants envoyés par e-mail uniquement).
    - Si la personne est déjà membre du personnel d'un autre établissement :
      MUTATION. La candidature acceptée par l'établissement B ne crée JAMAIS
      un second compte : le compte existant est réassigné à B, son rôle est
      mis à jour et il devient actif pour B (donc plus rattaché à A). La
      mutation est journalisée dans le JournalAudit des deux établissements.

    Retourne (personnel, mode) avec mode ∈ {'cree', 'mute'} ; (None, mode)
    si l'opération est bloquée (doublon dans le même établissement).
    """
    from urgences.models import JournalAudit

    role_nom = data['role']
    role, _ = Role.objects.get_or_create(nomRole=role_nom)
    mot_de_passe = generer_mot_de_passe_provisoire()

    existant = Personnel.objects.filter(email__iexact=candidature.email).first()

    # ── Cas 2 : mutation d'un membre du personnel existant ────────────────
    if existant is not None:
        if existant.etablissement_id == candidature.etablissement.pk:
            messages.error(request,
                f'Un compte Personnel existe déjà pour {candidature.email} '
                f'dans cet établissement — candidature refusée.')
            return None, 'existant'

        ancien_etablissement = existant.etablissement

        # Réassignation du compte : un e-mail ne correspond qu'à un seul
        # compte actif à un instant donné, tous établissements confondus.
        # Le compte devient actif pour B et n'est donc plus rattaché à A.
        existant.etablissement = candidature.etablissement
        existant.role = role
        existant.statutProfessionnel = 'ACTIF'
        existant.save(update_fields=['etablissement', 'role', 'statutProfessionnel'])
        candidature.accepter()

        # Journalisation dans l'établissement d'origine (A) et d'arrivée (B).
        if ancien_etablissement is not None:
            JournalAudit.objects.create(
                action='MUTATION_PERSONNEL',
                description=(f'Mutation de {existant.get_full_name()} de '
                             f'{ancien_etablissement.nom} vers '
                             f'{candidature.etablissement.nom} (candidature '
                             f'acceptée par {request.user.get_full_name()}).'),
                utilisateur=request.user, etablissement=ancien_etablissement,
                adresseIP=request.META.get('REMOTE_ADDR'))
        JournalAudit.objects.create(
            action='MUTATION_PERSONNEL',
            description=(f'Mutation de {existant.get_full_name()} de '
                         f'{ancien_etablissement.nom if ancien_etablissement else "—"} '
                         f'vers {candidature.etablissement.nom} (candidature '
                         f'acceptée par {request.user.get_full_name()}).'),
            utilisateur=request.user, etablissement=candidature.etablissement,
            adresseIP=request.META.get('REMOTE_ADDR'))

        sujet = 'Votre mutation MedShare a été prise en compte'
        corps = (
            f'Bonjour {existant.prenom} {existant.nom},\n\n'
            f'Votre candidature auprès de {candidature.etablissement} '
            f'a été acceptée.\n'
            f'Votre compte MedShare est désormais rattaché à cet établissement'
            f' (mutation depuis '
            f'{ancien_etablissement.nom if ancien_etablissement else "votre ancien établissement"}).\n\n'
            f'  • E-mail : {existant.email}\n'
            f'  • Matricule : {existant.matricule} (inchangé)\n'
            f'  • Rôle : {role.nomRole}\n\n'
            f'Vos identifiants de connexion restent valides.\n'
            f'Cordialement,\nMedShare'
        )
        from core.notifications import envoyer_email
        envoyer_email(request, existant.email, sujet, corps)

        messages.success(request,
            f'Mutation de {existant.prenom} {existant.nom} actée : le compte est '
            f'désormais actif dans {candidature.etablissement.nom}.')
        return existant, 'mute'

    # ── Cas 1 : création d'un nouveau compte Personnel ─────────────────────
    matricule = generer_matricule()

    personnel = Personnel.objects.create_user(
        email=candidature.email,
        nom=candidature.nom,
        prenom=candidature.prenom,
        password=mot_de_passe,
        matricule=matricule,
        etablissement=candidature.etablissement,
        doitChangerMotDePasse=True,
        telephone=candidature.telephone,
    )
    personnel.role = role
    personnel.save()
    candidature.accepter()

    sujet = 'Votre compte MedShare a été créé'
    corps = (
        f'Bonjour {personnel.prenom} {personnel.nom},\n\n'
        f'Votre candidature auprès de {candidature.etablissement} a été acceptée.\n\n'
        f'Voici vos identifiants :\n'
        f'  • E-mail : {personnel.email}\n'
        f'  • Matricule : {matricule}\n'
        f'  • Rôle : {role.nomRole}\n'
        f'  • Mot de passe provisoire : {mot_de_passe}\n\n'
        f'À la première connexion, vous devez changer le mot de passe.\n'
        f'Cordialement,\nMedShare'
    )
    from core.notifications import envoyer_email
    envoyer_email(request, personnel.email, sujet, corps)

    messages.success(request,
        f'Compte créé pour {personnel.prenom} {personnel.nom} — '
        f'il a reçu ses identifiants par e-mail.')

    return personnel, 'cree'


def _notifier_refus(candidature, motif):
    """Prévient le candidat du rejet de sa candidature par e-mail.
    L'admin vérifie au préalable la présence du membre dans le registre
    de l'hôpital avant de refuser."""
    sujet = 'Mise à jour de votre candidature MedShare'
    raison = f'\nMotif : {motif}' if motif.strip() else '\nAucun motif fourni.'
    corps = (
        f'Bonjour {candidature.prenom} {candidature.nom},\n\n'
        f'Nous avons examiné votre candidature auprès de '
        f'{candidature.etablissement}.\n'
        f'Malheureusement, votre candidature a été refusée, car '
        f'vos informations n\'ont pas pu être confirmées dans le registre '
        f'du personnel de l\'établissement.{raison}\n\n'
        f'Vous pouvez vérifier le statut de votre candidature et contacter '
        f'l\'établissement pour toute précision.\n'
        f'Cordialement,\nL\'équipe MedShare'
    )
    from core.notifications import envoyer_email
    envoyer_email(None, candidature.email, sujet, corps)


@login_required
@admin_etablissement_required_strict
def supprimer_candidature(request, pk):
    candidature = get_object_or_404(Candidature, pk=pk)
    candidature.annuler()
    messages.info(request, f'Candidature #{pk} annulée.')
    return redirect('gestion_candidatures')


# ──────────────────────────────────────────────
# Vues distinctes pour sidebar Admin Hôpital (éviter statique)
# ──────────────────────────────────────────────
@login_required
@admin_etablissement_required_strict
def mon_etablissement(request):
    etab = getattr(request.user, 'etablissement', None)
    if not etab:
        messages.error(request, "Aucun établissement associé.")
        return redirect('dashboard')
    from .models import Formule
    try:
        abonnement = etab.abonnement
    except Exception:
        abonnement = None
    return render(request, 'establishments/mon_etablissement.html',
                  {'etablissement': etab, 'abonnement': abonnement,
                   'formules': Formule.objects.all()})


@login_required
@admin_etablissement_required_strict
def liste_personnel(request):
    from users.models import Personnel
    etab = getattr(request.user, 'etablissement', None)
    qs = Personnel.objects.filter(etablissement=etab).select_related('role') if etab else Personnel.objects.none()
    from .models import Candidature
    candidatures = Candidature.objects.filter(
        etablissement=etab, statut='EN_ATTENTE'
    ).order_by('-dateSoumission') if etab else []
    return render(request, 'establishments/liste_personnel.html',
                  {'personnel': qs, 'etablissement': etab,
                   'candidatures': candidatures})


@login_required
@admin_etablissement_required_strict
def abonnement_detail(request):
    etab = getattr(request.user, 'etablissement', None)
    try:
        abonnement = etab.abonnement if etab else None
    except Exception:
        abonnement = None

    if request.method == 'POST' and request.POST.get('action') == 'renouveler':
        # Paiement simulé renouvelé : prolonge l'abonnement de la durée de la
        # formule ATRIBÉE par la plateforme, puis réactive l'établissement SI
        # celui-ci avait été suspendu pour abonnement expiré (jamais pour une
        # décision manuscrite). L'admin hôpital ne choisit plus sa formule :
        # seule le Super Admin peut la changer (super_abonnements).
        formule = abonnement.formule if abonnement is not None else None
        if abonnement is not None and formule is not None:
            du = timezone.now().date() + timezone.timedelta(days=30 * formule.dureeMois)
            abonnement.renouveler(du)
            etablissement = abonnement.etablissement
            from urgences.models import JournalAudit
            JournalAudit.objects.create(
                action='RENOUVELLEMENT_ABONNEMENT',
                description=(f'Renouvellement de l\'abonnement de '
                             f'{etablissement.nom} ({formule.nom}) jusqu\'au {du} — '
                             f'paiement simulé par {request.user.get_full_name()}.'),
                utilisateur=request.user, etablissement=etablissement,
                adresseIP=request.META.get('REMOTE_ADDR'))
            if etablissement.statut == 'SUSPENDU':
                if etablissement.motifSuspension == 'ABONNEMENT_EXPIRE':
                    etablissement.reactiver()
                    messages.success(request, 'Abonnement renouvelé — '
                                    f'{etablissement.nom} est de nouveau actif.')
                else:
                    messages.warning(request,
                        'Abonnement renouvelé, mais l\'établissement reste suspendu '
                        'car il l\'a été manuellement par le Super Admin.')
            else:
                messages.success(request, 'Abonnement renouvelé et à jour.')
        else:
            messages.error(request, 'Aucun abonnement actif à renouveler.')
        return redirect('abonnement_detail')

    from .models import Formule
    formules = Formule.objects.all()
    return render(request, 'establishments/abonnement_detail.html', {'abonnement': abonnement, 'formules': formules, 'etablissement': etab})


@login_required
@admin_etablissement_required_strict
def journal_audit(request):
    etab = getattr(request.user, 'etablissement', None)
    if not etab:
        messages.error(request, "Aucun établissement associé.")
        return redirect('dashboard')
    from urgences.models import JournalAudit
    logs = JournalAudit.objects.filter(etablissement=etab).order_by('-dateHeure')[:100]
    return render(request, 'establishments/journal_audit.html', {'logs': logs, 'etablissement': etab})
