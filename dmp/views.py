from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Q
from core.generateurs import (
    generer_mot_de_passe_provisoire,
    generer_numero_patient,
)
from users.decorators import block_superadmin, role_required, role_required_strict
from users.models import Personnel, Patient

from .forms import PatientForm, PatientRechercheForm
from .models import DossierMedicalPartage, AccesDMP


def _creer_dmp(patient):
    count = DossierMedicalPartage.objects.count() + 1
    numero = f'DMP-{timezone.now().strftime("%Y%m%d")}-{count:04d}'
    return DossierMedicalPartage.objects.create(
        patient=patient,
        numeroDMP=numero,
    )


def _verifier_approbation_patient(patient, etablissement, demandeur=None):
    """Contrôle l'approbation EXPRESSE du patient (itération 3) avant un acte
    portant sur son DMP : le consentement n'est plus un PIN saisi par le soignant
    mais une autorisation accordée par le patient lui-même depuis son espace.

    Retourne (ok: bool, message_ou_None, demande: AccesDMP|None).
      - ok=True si une approbation active existe.
      - sinon crée la demande et retourne ok=False avec un message invitant à
        l'approbation par le patient, ainsi que la demande en attente.
    Les patients inconnus (DUT non identifié) restent dispensés (Break Glass)."""
    if patient is None:
        return True, '', None
    from .services import verifier_ou_demander_acces
    ok, demande = verifier_ou_demander_acces(patient, etablissement, demandeur)
    if ok:
        return True, '', demande
    return (
        False,
        'L\'accès à ce dossier nécessite l\'approbation du patient. '
        'La demande a été envoyée dans son espace — il doit l\'accepter '
        'pour consentir à cet acte.',
        demande,
    )


def _demande_en_attente(patient, etablissement):
    """Demande d'accès DMP en attente pour ce patient/établissement (None sinon).
    Utilisée par les écrans soignants pour proposer le bouton « Renvoyer »."""
    if patient is None or etablissement is None:
        return None
    return AccesDMP.objects.filter(
        patient=patient,
        etablissement=etablissement,
        statut=AccesDMP.Statut.EN_ATTENTE,
    ).first()


@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def renvoyer_notification_acces(request, acces_pk):
    """T2 — renvoie au patient la notification d'approbation DMP (limite de 3,
    puis délai de sécurité). Réservé au personnel de l'établissement concerné."""
    acces = get_object_or_404(AccesDMP, pk=acces_pk)
    etab = getattr(request.user, 'etablissement', None)
    if etab and acces.etablissement_id != etab.pk and not request.user.is_superuser:
        raise Http404('Accès refusé.')
    if acces.statut != AccesDMP.Statut.EN_ATTENTE:
        messages.info(request, 'Cette demande n\'est plus en attente.')
        return redirect('dashboard')
    if not acces.peut_renvoyer_notification():
        messages.error(
            request,
            'Nombre maximal de renvois atteint ou envoi trop rapproché. '
            'Réessayez dans quelques minutes.')
        return redirect(request.META.get('HTTP_REFERER', 'dashboard'))
    if acces.notifier_patient(request):
        messages.success(request, 'Notification renvoyée au patient.')
    else:
        messages.warning(request, 'Renvoi impossible (service e-mail indisponible).')
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


# ──────────────────────────────────────────────
# Recherche de patient
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def rechercher_patient(request):
    form = PatientRechercheForm(request.GET or None)
    resultats = []
    if form.is_valid():
        q = form.cleaned_data.get('query', '').strip()
        if q:
            resultats = Patient.objects.filter(
                Q(nom__icontains=q) |
                Q(prenom__icontains=q) |
                Q(numeroPatient__icontains=q) |
                Q(email__icontains=q)
            )
    return render(request, 'dmp/rechercher_patient.html',
                  {'form': form, 'resultats': resultats})


# ──────────────────────────────────────────────
# Création de patient (infirmier)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Administrateur', 'Médecin')
def creer_patient(request):
    if request.method == 'POST':
        form = PatientForm(request.POST, request.FILES)
        if form.is_valid():
            # Sécurité stricte : personne ne peut créer son propre dossier patient.
            # Un soignant/administrateur a deux comptes distincts (Personnel et
            # Patient) ; la création d'un compte Patient doit venir d'un collègue.
            email_soumis = (form.cleaned_data.get('email') or '').strip().lower()
            email_connecte = (getattr(request.user, 'email', '') or '').strip().lower()
            if email_soumis and email_soumis == email_connecte:
                form.add_error(
                    'email',
                    'Vous ne pouvez pas créer votre propre dossier patient — '
                    'demandez à un collègue habilité de le faire.')
            else:
                patient = form.save(commit=False)
                patient.numeroPatient = generer_numero_patient()
                mdp = generer_mot_de_passe_provisoire()
                patient.set_password(mdp)
                # Politique de sécurité : changement de mot de passe à la première
                # connexion (comme pour le personnel). Le consentement aux actes
                # passe par l'approbation patient (T7), plus par un code saisi
                # par le soignant.
                patient.doitChangerMotDePasse = True
                patient.codeConfirmation = ''
                patient.save()
                # Photo déjà sauvegardée via form.save()
                _creer_dmp(patient)
                # Journal audit RGPD : création patient avec photo (tracé)
                try:
                    from urgences.models import JournalAudit
                    JournalAudit.objects.create(
                        action='CRÉATION_PATIENT',
                        description=f'Patient {patient.numeroPatient} créé avec photoProfil par {request.user.get_full_name()}',
                        utilisateur=request.user,
                        etablissement=getattr(request.user, 'etablissement', None),
                        adresseIP=request.META.get('REMOTE_ADDR')
                    )
                except Exception:
                    pass
                from core.notifications import envoyer_email
                sujet = 'Votre compte patient MedShare'
                corps = (
                    f'Bonjour {patient.prenom} {patient.nom},\n\n'
                    f'Votre dossier médical partagé (DMP) a été créé sur MedShare.\n\n'
                    f'Voici vos accès :\n'
                    f'  • Numéro patient : {patient.numeroPatient}\n'
                    f'  • E-mail : {patient.email}\n'
                    f'  • Mot de passe provisoire : {mdp}\n\n'
                    f'À la première connexion, vous devrez changer votre mot de passe.\n'
                    f'Chaque professionnel qui souhaite consulter votre dossier vous '
                    f'enverra une demande d\'approbation dans votre espace patient ; '
                    f'aucune consultation n\'a lieu sans votre consentement explicite.\n'
                    f'Cordialement,\nl\'équipe MedShare'
                )
                envoyer_email(request, patient.email, sujet, corps)
                messages.success(request,
                    f'Patient {patient.prenom} {patient.nom} créé. '
                    f'Numéro : {patient.numeroPatient} | E-mail : {patient.email} — '
                    f'les identifiants de connexion ont été envoyés par e-mail au patient.')
                return redirect('detail_patient', pk=patient.pk)
    else:
        form = PatientForm()
    return render(request, 'dmp/creer_patient.html', {'form': form})


# ──────────────────────────────────────────────
# Détail patient
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def detail_patient(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    dmp = getattr(patient, 'dmp', None)
    return render(request, 'dmp/detail_patient.html',
                  {'patient': patient, 'dmp': dmp})


# ──────────────────────────────────────────────
# DMP — consultation
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def consulter_dmp(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    dmp, _ = DossierMedicalPartage.objects.get_or_create(
        patient=patient,
        defaults={'numeroDMP': f'DMP-{timezone.now().strftime("%Y%m%d")}-{DossierMedicalPartage.objects.count()+1:04d}'}
    )
    consultations = dmp.consultations.all()
    _journal_acces_dmp(request, patient, 'CONSULTATION_DMP')
    return render(request, 'dmp/consulter_dmp.html',
                  {'patient': patient, 'dmp': dmp, 'consultations': consultations})


def _journal_acces_dmp(request, patient, action):
    """T1 — trace dans le JournalAudit l'accès au DMP d'un patient identifié.
    L'entrée est liée au patient (visible dans « Historique des accès »)."""
    try:
        from urgences.models import JournalAudit
        JournalAudit.objects.create(
            action=action,
            description=f'Accès au DMP {getattr(patient, "dmp", None).numeroDMP if getattr(patient, "dmp", None) else "—"} par {request.user.get_full_name()}',
            utilisateur=request.user,
            etablissement=getattr(request.user, 'etablissement', None),
            adresseIP=request.META.get('REMOTE_ADDR'),
            patient=patient,
        )
    except Exception:
        pass


@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def detail_consultation(request, pk):
    consultation = get_object_or_404(
        __import__('dmp.models', fromlist=['Consultation']).Consultation, pk=pk)
    dmp = consultation.dmp
    patient = dmp.patient
    prescription = getattr(consultation, 'prescription', None)
    _journal_acces_dmp(request, patient, 'CONSULTATION_DMP')
    return render(request, 'dmp/detail_consultation.html', {
        'consultation': consultation, 'dmp': dmp, 'patient': patient,
        'prescription': prescription,
    })


# ──────────────────────────────────────────────
# Listes distinctes pour sidebar Médecin (éviter statique)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def liste_consultations(request):
    from .models import Consultation
    etab = getattr(request.user, 'etablissement', None)
    qs = Consultation.objects.select_related('dmp__patient', 'etablissement', 'medecin').order_by('-dateHeure')
    if etab:
        qs = qs.filter(etablissement=etab)
    # Médecin ne voit que ses consultations ? on montre tout établissement pour demo
    return render(request, 'dmp/liste_consultations.html', {'consultations': qs[:50], 'etablissement': etab})


@login_required
@role_required_strict('Médecin', 'Administrateur')
def liste_prescriptions(request):
    from .models import Prescription
    etab = getattr(request.user, 'etablissement', None)
    qs = Prescription.objects.select_related('consultation__dmp__patient', 'consultation__etablissement').order_by('-datePrescription')
    if etab:
        qs = qs.filter(consultation__etablissement=etab)
    return render(request, 'dmp/liste_prescriptions.html', {'prescriptions': qs[:50], 'etablissement': etab})


@login_required
@role_required_strict('Médecin', 'Administrateur', 'Infirmier')
def dmp_dashboard(request):
    """Tableau DMP inter-établissements (analytics) — distinct de Patients"""
    from users.models import Patient
    from .models import DossierMedicalPartage, Consultation
    etab = getattr(request.user, 'etablissement', None)
    total_dmp = DossierMedicalPartage.objects.count()
    total_patients = Patient.objects.count()
    consultations_recentes = Consultation.objects.select_related('dmp__patient').order_by('-dateHeure')[:5]
    patients_sans_photo = Patient.objects.filter(photoProfil='').count()
    return render(request, 'dmp/dashboard_dmp.html', {
        'total_dmp': total_dmp,
        'total_patients': total_patients,
        'consultations_recentes': consultations_recentes,
        'patients_sans_photo': patients_sans_photo,
        'etablissement': etab,
    })


# ──────────────────────────────────────────────
# Nouvelle consultation (médecin)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin')
def creer_consultation(request, patient_pk):
    from .forms import ConsultationForm
    patient = get_object_or_404(Patient, pk=patient_pk)
    dmp, _ = DossierMedicalPartage.objects.get_or_create(
        patient=patient,
        defaults={'numeroDMP': f'DMP-{timezone.now().strftime("%Y%m%d")}-{DossierMedicalPartage.objects.count()+1:04d}'}
    )

    if request.method == 'POST':
        form = ConsultationForm(request.POST)
        if form.is_valid():
            ok, erreur, demande = _verifier_approbation_patient(
                patient, request.user.etablissement, demandeur=request.user)
            if not ok:
                form.add_error(None, erreur)
            else:
                consultation = form.save(commit=False)
                consultation.dmp = dmp
                consultation.etablissement = request.user.etablissement
                consultation.medecin = request.user
                consultation.save()
                messages.success(request,
                    f'Consultation enregistrée — approbation patient {patient.numeroPatient} validée.')
                return redirect('detail_consultation', pk=consultation.pk)
    else:
        form = ConsultationForm()
    from .services import acces_pour_dmp
    approbation_active = acces_pour_dmp(dmp, request.user.etablissement) is not None
    demande_en_attente = _demande_en_attente(patient, request.user.etablissement)
    return render(request, 'dmp/creer_consultation.html',
                  {'form': form, 'patient': patient, 'dmp': dmp,
                   'approbation_active': approbation_active,
                   'demande_en_attente': demande_en_attente})


# ──────────────────────────────────────────────
# Ordonnance (médecin)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin')
def creer_ordonnance(request, consultation_pk):
    from .forms import PrescriptionForm, LignePrescriptionFormSet
    consultation = get_object_or_404(
        __import__('dmp.models', fromlist=['Consultation']).Consultation, pk=consultation_pk)
    patient = consultation.dmp.patient

    if hasattr(consultation, 'prescription'):
        messages.info(request, 'Une ordonnance existe déjà pour cette consultation.')
        return redirect('detail_consultation', pk=consultation.pk)

    if request.method == 'POST':
        form = PrescriptionForm(request.POST)
        formset = LignePrescriptionFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            ok, erreur, _demande = _verifier_approbation_patient(
                patient, request.user.etablissement, demandeur=request.user)
            if not ok:
                form.add_error(None, erreur)
            else:
                prescription = form.save(commit=False)
                prescription.consultation = consultation
                prescription.save()
                formset.instance = prescription
                formset.save()
                messages.success(request,
                    f'Ordonnance créée — approbation patient {patient.numeroPatient} validée.')
                return redirect('detail_consultation', pk=consultation.pk)
    else:
        form = PrescriptionForm()
        formset = LignePrescriptionFormSet()

    medicaments = __import__('dmp.models', fromlist=['Medicament']).Medicament.objects.all()
    from .services import acces_pour_dmp
    approbation_active = acces_pour_dmp(
        getattr(patient, 'dmp', None) or consultation.dmp, request.user.etablissement) is not None
    demande_en_attente = _demande_en_attente(patient, request.user.etablissement)
    return render(request, 'dmp/creer_ordonnance.html', {
        'form': form, 'formset': formset,
        'consultation': consultation, 'patient': patient,
        'medicaments': medicaments,
        'approbation_active': approbation_active,
        'demande_en_attente': demande_en_attente,
    })


# ──────────────────────────────────────────────
# Vues patient distinctes pour sidebar (éviter statique)
# ──────────────────────────────────────────────
@login_required
@block_superadmin
def mes_ordonnances(request, patient_pk=None):
    """Mes ordonnances — prescriptions du patient connecté uniquement."""
    # Si patient_pk fourni, seul le patient lui-même (claimant) y a accès.
    if patient_pk:
        patient = get_object_or_404(Patient, pk=patient_pk)
        if request.user.pk != patient.pk:
            raise Http404('Accès refusé.')
    else:
        try:
            patient = request.user.patient_child
        except Exception:
            raise Http404('Accès réservé au patient.')
    dmp = getattr(patient, 'dmp', None)
    prescriptions = []
    if dmp:
        from .models import Prescription
        prescriptions = Prescription.objects.filter(consultation__dmp=dmp).select_related('consultation').order_by('-datePrescription')
    return render(request, 'dmp/mes_ordonnances.html', {'patient': patient, 'prescriptions': prescriptions, 'dmp': dmp})


@login_required
@block_superadmin
def mon_historique(request, patient_pk=None):
    """Mon historique — consultations + DUT fusionnés du patient connecté uniquement."""
    # Si patient_pk fourni, seul le patient lui-même (claimant) y a accès.
    if patient_pk:
        patient = get_object_or_404(Patient, pk=patient_pk)
        if request.user.pk != patient.pk:
            raise Http404('Accès refusé.')
    else:
        try:
            patient = request.user.patient_child
        except Exception:
            raise Http404('Accès réservé au patient.')
    dmp = getattr(patient, 'dmp', None)
    consultations = dmp.consultations.all().order_by('-dateHeure') if dmp else []
    # DUT fusionnés
    from urgences.models import DossierUrgenceTemporaire
    duts = DossierUrgenceTemporaire.objects.filter(dmpRattache=dmp).order_by('-dateCreation') if dmp else []
    return render(request, 'dmp/mon_historique.html', {'patient': patient, 'dmp': dmp, 'consultations': consultations, 'duts': duts})


# Actions « journal d'audit » qui correspondent à un accès réel au dossier du
# patient par un professionnel (alimentent l'historique T1).
ACCES_DMP_ACTIONS = (
    'CONSULTATION_DMP', 'FUSION_DUT_DMP',
    'BREAK_GLASS_CONSULTATION', 'BREAK_GLASS_OUVERTURE',
)

ACCES_DMP_LABELS = {
    'CONSULTATION_DMP': 'Consultation de votre dossier',
    'FUSION_DUT_DMP': 'Rattachement d\'un dossier d\'urgence',
    'BREAK_GLASS_CONSULTATION': 'Ouverture de la fiche vitale',
    'BREAK_GLASS_OUVERTURE': 'Ouverture de la fiche vitale (urgence)',
}


def _acteur_acces(ligne):
    """Résout le nom et le rôle de l'auteur d'une entrée d'audit (l'auteur est
    stocké en base Utilisateur : on remonte au Personnel concret pour le rôle).
    Ne renvoie jamais d'e-mail ni d'identifiant interne."""
    util = ligne.utilisateur
    if util is None:
        return 'Compte supprimé', 'Professionnel'
    nom = util.get_full_name() or 'Professionnel'
    libelle = 'Professionnel'
    try:
        pers = util.personnel_child
        if pers.is_superuser:
            libelle = 'Super Administrateur'
        elif pers.role:
            libelle = pers.role.nomRole
    except Exception:
        pass
    return nom, libelle


@login_required
@block_superadmin
def mon_acces_historique(request, patient_pk=None):
    """T1 (addendum 4) : historique LECTURE SEULE des accès au DMP du patient
    connecté — nom + rôle + date/heure + action. Jamais d'e-mail ni
    d'identifiant interne (RGPD)."""
    if patient_pk:
        patient = get_object_or_404(Patient, pk=patient_pk)
        if request.user.pk != patient.pk:
            raise Http404('Accès refusé.')
    else:
        try:
            patient = request.user.patient_child
        except Exception:
            raise Http404('Accès réservé au patient.')

    from urgences.models import JournalAudit
    logs = (JournalAudit.objects
            .filter(patient=patient, action__in=ACCES_DMP_ACTIONS)
            .select_related('utilisateur', 'etablissement')
            .order_by('-dateHeure')[:100])
    entrees = []
    for ligne in logs:
        nom, libelle = _acteur_acces(ligne)
        entrees.append({
            'ligne': ligne,
            'nom': nom,
            'role': libelle,
            'label': ACCES_DMP_LABELS.get(ligne.action, ligne.action),
        })
    return render(request, 'dmp/mon_acces_historique.html',
                  {'patient': patient, 'entrees': entrees})


# ──────────────────────────────────────────────
# Approbation patient (T7) — endpoint de réponse
# Seul le patient titulaire du DMP peut approuver ou refuser la demande.
# ──────────────────────────────────────────────
@login_required
@block_superadmin
def acces_dmp_repondre(request, acces_pk):
    acces = get_object_or_404(AccesDMP, pk=acces_pk)
    try:
        patient = request.user.patient_child
    except Exception:
        raise Http404('Accès réservé au patient.')
    if patient.pk != acces.patient_id:
        raise Http404('Accès refusé.')

    decision = (request.POST.get('decision') or '').strip().upper()
    if request.method == 'POST' and decision in ('APPROUVER', 'REFUSER'):
        if decision == 'APPROUVER':
            acces.approuver(utilisateur=request.user)
            messages.success(request, 'Vous avez approuvé l\'accès à votre dossier pour '
                              f'{acces.etablissement.nom}.')
        else:
            acces.refuser(utilisateur=request.user)
            messages.info(request, 'Vous avez refusé l\'accès à votre dossier pour '
                           f'{acces.etablissement.nom}.')
        jeton = request.user.jeton_acces
        # Retour à l'espace patient (la demande en attente a disparu).
        from django.urls import reverse
        return redirect('dashboard_patient', jeton=jeton)

    # Formulaire non valide → retour avec message d'erreur
    messages.error(request, 'Décision invalide.')
    jeton = request.user.jeton_acces
    return redirect('dashboard_patient', jeton=jeton)
