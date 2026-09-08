from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render

from core.generateurs import (
    generer_matricule_admin,
    generer_mot_de_passe_provisoire,
)


def _contexte_superadmin(user):
    from establishments.models import Abonnement, Etablissement, Formule
    from users.models import Patient, Utilisateur
    from urgences.models import JournalAudit
    return {
        'user': user,
        'total_etablissements': Etablissement.objects.count(),
        'etablissements_actifs': Etablissement.objects.filter(statut='ACTIF').count(),
        'etablissements_suspendus': Etablissement.objects.filter(statut='SUSPENDU').count(),
        'total_formules': Formule.objects.count(),
        'formules': Formule.objects.all(),
        'total_utilisateurs': Utilisateur.objects.count(),
        'total_patients': Patient.objects.count(),
        'abonnements_actifs': Abonnement.objects.filter(statut='ACTIF').count(),
        'etablissements_recents': Etablissement.objects.order_by('-idEtablissement')[:5],
        'logs': JournalAudit.objects.all().order_by('-dateHeure')[:5],
    }


def _contexte_admin_hopital(user):
    from establishments.models import Candidature
    from users.models import Personnel
    from urgences.models import JournalAudit
    etab = getattr(user, 'etablissement', None)
    if not etab:
        return {'user': user}
    personnel_qs = Personnel.objects.filter(etablissement=etab)
    try:
        abonnement = etab.abonnement
    except Exception:
        abonnement = None
    logs = JournalAudit.objects.filter(etablissement=etab).order_by('-dateHeure')[:5]
    return {
        'user': user,
        'nb_personnel': personnel_qs.count(),
        'nb_personnel_actif': personnel_qs.filter(statutProfessionnel='ACTIF').count(),
        'personnel_actif': personnel_qs.filter(statutProfessionnel='ACTIF')[:5],
        'candidatures': Candidature.objects.filter(etablissement=etab, statut='EN_ATTENTE').order_by('-dateSoumission')[:5],
        'candidatures_attente': Candidature.objects.filter(etablissement=etab, statut='EN_ATTENTE').count(),
        'abonnement': abonnement,
        'abonnement_formule': abonnement.formule.nom if abonnement else '—',
        'abonnement_statut': abonnement.statut if abonnement else '—',
        'abonnement_fin': abonnement.dateFin if abonnement else '—',
        'logs': logs,
    }


def _contexte_medecin(user):
    from users.models import Patient
    from dmp.models import Consultation
    from urgences.models import DossierUrgenceTemporaire, RechercheIdentite
    etab = getattr(user, 'etablissement', None)
    # Patients récents inter-établissements (DMP SaaS)
    patients_recents = Patient.objects.all().order_by('-idPatient')[:6]
    # Consultations récentes du médecin
    try:
        consultations_recentes = Consultation.objects.filter(medecin=user).select_related('dmp__patient').order_by('-dateHeure')[:5]
    except Exception:
        consultations_recentes = []
    # Urgences en attente de validation (correspondances >60% non confirmées)
    try:
        qs = DossierUrgenceTemporaire.objects.filter(statut='ACTIF')
        if etab:
            qs = qs.filter(etablissement=etab)
        urgences_a_valider = qs.filter(recherches_identite__statut='CORRESPONDANCE_TROUVEE').distinct().count()
        dut_actifs = qs.count()
        correspondances_en_attente = RechercheIdentite.objects.filter(statut='CORRESPONDANCE_TROUVEE')
        if etab:
            correspondances_en_attente = correspondances_en_attente.filter(etablissement=etab)
        correspondances_en_attente = correspondances_en_attente.count()
    except Exception:
        urgences_a_valider = 0
        dut_actifs = 0
        correspondances_en_attente = 0

    return {
        'user': user,
        'patients_recents': patients_recents,
        'consultations_recentes': consultations_recentes,
        'urgences_a_valider': urgences_a_valider,
        'dut_actifs': dut_actifs,
        'correspondances_en_attente': correspondances_en_attente,
    }


def _contexte_infirmier(user):
    from users.models import Patient
    from urgences.models import DossierUrgenceTemporaire, RechercheIdentite
    etab = getattr(user, 'etablissement', None)
    try:
        qs = DossierUrgenceTemporaire.objects.filter(statut='ACTIF')
        if etab:
            qs = qs.filter(etablissement=etab)
        urgences_en_cours = qs.count()
        dut_actifs = qs.count()
        patients_attente = qs.filter(triage__isnull=True).count()
        correspondances = RechercheIdentite.objects.filter(statut='CORRESPONDANCE_TROUVEE')
        if etab:
            correspondances = correspondances.filter(etablissement=etab)
        correspondances_count = correspondances.count()
    except Exception:
        urgences_en_cours = 0
        dut_actifs = 0
        patients_attente = 0
        correspondances_count = 0
    return {
        'user': user,
        'patients_accueillis': Patient.objects.count(),
        'patients_attente': patients_attente,
        'urgences_en_cours': urgences_en_cours,
        'dut_actifs': dut_actifs,
        'correspondances_count': correspondances_count,
    }


def _contexte_patient(user):
    # Patient connecté : on affiche son vrai patient_child si disponible
    try:
        patient = user.patient_child
    except Exception:
        patient = user if hasattr(user, 'photoProfil') else None
    # DMP et prescriptions
    try:
        dmp = getattr(patient, 'dmp', None) if patient else None
        consultations = dmp.consultations.select_related('prescription').all()[:5] if dmp else []
        prescriptions = []
        for c in consultations:
            if hasattr(c, 'prescription'):
                for l in c.prescription.lignes.select_related('medicament').all():
                    prescriptions.append({'medicament': l.medicament.nomCommercial, 'posologie': l.posologie})
        if not prescriptions and patient and getattr(patient, 'traitementEnCours', ''):
            for t in patient.traitementEnCours.split(','):
                t = t.strip()
                if t:
                    prescriptions.append({'medicament': t, 'posologie': '—'})
    except Exception:
        prescriptions = []
        consultations = []
    # Approbations d'accès DMP : demandes en attente + accès accordés (T7)
    try:
        from dmp.models import AccesDMP
        demandes_attente = AccesDMP.objects.filter(
            patient=patient, statut=AccesDMP.Statut.EN_ATTENTE
        ).select_related('etablissement') if patient else AccesDMP.objects.none()
        acces_accordes = AccesDMP.objects.filter(
            patient=patient, statut=AccesDMP.Statut.ACCORDE
        ).select_related('etablissement') if patient else AccesDMP.objects.none()
    except Exception:
        demandes_attente = []
        acces_accordes = []
    return {
        'user': user,
        'patient': patient,
        'prescriptions': prescriptions,
        'consultations': consultations if 'consultations' in locals() else [],
        'rendezvous': [],
        'demandes_attente': demandes_attente,
        'acces_accordes': acces_accordes,
    }


def dashboard(request):
    """Point d'entrée : affiche le dashboard dédié au rôle de l'utilisateur."""
    if not request.user.is_authenticated:
        return redirect('login')

    user = request.user
    role = None

    if getattr(user, 'est_super_admin', False) or user.is_superuser:
        role = 'superadmin'
    elif getattr(user, 'est_admin_hospital', False):
        role = 'admin_hopital'
    elif getattr(user, 'est_medecin', False):
        role = 'medecin'
    elif getattr(user, 'est_infirmier', False):
        role = 'infirmier'
    else:
        try:
            _ = user.patient_child
            role = 'patient'
        except Exception:
            role = 'inconnu'

    templates_map = {
        'superadmin': 'core/dashboard_superadmin.html',
        'admin_hopital': 'core/dashboard_admin.html',
        'medecin': 'core/dashboard_medecin.html',
        'infirmier': 'core/dashboard_infirmier.html',
        'patient': 'core/dashboard_patient.html',
    }
    context_builders = {
        'superadmin': _contexte_superadmin,
        'admin_hopital': _contexte_admin_hopital,
        'medecin': _contexte_medecin,
        'infirmier': _contexte_infirmier,
        'patient': _contexte_patient,
    }

    template_name = templates_map.get(role)
    if template_name:
        ctx = context_builders[role](user)
        return render(request, template_name, ctx)

    # Fallback : personnel avec jeton
    from users.models import Personnel
    if hasattr(user, 'personnel_child'):
        jeton = getattr(user.personnel_child, 'jeton_acces', None)
        if jeton:
            return redirect('dashboard_personnel', jeton=jeton)

    return redirect('login')


def dashboard_personnel(request, jeton):
    """Dashboard du personnel, accessible UNIQUEMENT avec le jeton associé."""
    if not request.user.is_authenticated:
        return redirect('login')
    if jeton != request.user.jeton_acces:
        raise Http404('Accès refusé.')
    # Réutilise la logique de dashboard mais en conservant l'isolation par jeton
    user = request.user
    if getattr(user, 'est_super_admin', False) or user.is_superuser:
        return render(request, 'core/dashboard_superadmin.html', _contexte_superadmin(user))
    if getattr(user, 'est_admin_hospital', False):
        return render(request, 'core/dashboard_admin.html', _contexte_admin_hopital(user))
    if getattr(user, 'est_medecin', False):
        return render(request, 'core/dashboard_medecin.html', _contexte_medecin(user))
    if getattr(user, 'est_infirmier', False):
        return render(request, 'core/dashboard_infirmier.html', _contexte_infirmier(user))
    # fallback
    return render(request, 'core/role_inconnu.html')


# ──────────────────────────────────────────────
# Vues distinctes SuperAdmin (éviter statique)
# ──────────────────────────────────────────────
def _est_super_admin(request):
    if not request.user.is_authenticated:
        return False
    return getattr(request.user, 'is_superuser', False) or getattr(request.user, 'est_super_admin', False)


def super_etablissements(request):
    """Super admin : crée/modifie les établissements ET leur compte
    administrateur (fusion de l'ancienne page 'Administrateurs').

    Les identifiants du compte administrateur sont transmis par e-mail
    uniquement — jamais affichés à l'écran (politique de sécurité)."""
    from establishments.models import Etablissement
    from users.models import Personnel, Role
    from urgences.models import JournalAudit
    if not _est_super_admin(request):
        return redirect('dashboard')

    role_admin, _ = Role.objects.get_or_create(nomRole='Administrateur')
    etablissements = Etablissement.objects.all().order_by('nom')
    administrateurs = Personnel.objects.filter(role=role_admin).select_related(
        'etablissement', 'role').order_by('nom', 'prenom')

    def _creer_admin(etablissement, email, nom, prenom):
        if Personnel.objects.filter(email=email).exists():
            return None, 'Un compte existe déjà avec cette adresse e-mail.'
        mot_de_passe = generer_mot_de_passe_provisoire()
        matricule = generer_matricule_admin()
        admin = Personnel.objects.create_user(
            email=email, nom=nom, prenom=prenom, password=mot_de_passe,
            matricule=matricule, etablissement=etablissement,
            doitChangerMotDePasse=True)
        admin.role = role_admin
        admin.save()
        JournalAudit.objects.create(
            action='CREATION_ADMIN_ETABLISSEMENT',
            description=(f'Administrateur {admin.get_full_name()} '
                         f'créé pour {etablissement.nom} par '
                         f'{request.user.get_full_name()}'),
            utilisateur=request.user, etablissement=etablissement,
            adresseIP=request.META.get('REMOTE_ADDR'))
        sujet = 'Votre compte administrateur MedShare'
        corps = (
            f'Bonjour {admin.prenom} {admin.nom},\n\n'
            f'Votre compte administrateur pour l\'établissement '
            f'{etablissement.nom} a été créé sur MedShare.\n\n'
            f'Voici vos identifiants :\n'
            f'  • E-mail : {admin.email}\n'
            f'  • Matricule : {matricule}\n'
            f'  • Mot de passe provisoire : {mot_de_passe}\n\n'
            f'À la première connexion, vous devrez changer votre mot de passe.\n'
            f'Cordialement,\nMedShare'
        )
        from core.notifications import envoyer_email
        envoyer_email(request, admin.email, sujet, corps)
        return admin, None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'creer_etablissement':
            nom = request.POST.get('nom', '').strip()
            adresse = request.POST.get('adresse', '').strip()
            telephone = request.POST.get('telephone', '').strip()
            email = request.POST.get('email', '').strip().lower()
            admin_email = request.POST.get('admin_email', '').strip().lower()
            admin_nom = request.POST.get('admin_nom', '').strip()
            admin_prenom = request.POST.get('admin_prenom', '').strip()

            if not all([nom, adresse, telephone, email, admin_email, admin_nom, admin_prenom]):
                messages.error(request, 'Champs obligatoires : établissement + e-mail de l\'administrateur.')
            elif Etablissement.objects.filter(email=email).exists():
                messages.error(request, 'Un établissement existe déjà avec cet e-mail de contact.')
            elif Personnel.objects.filter(email=admin_email).exists():
                messages.error(request, 'Un compte existe déjà avec cette adresse e-mail.')
            else:
                etablissement = Etablissement.objects.create(
                    nom=nom, adresse=adresse, telephone=telephone, email=email,
                    statut='ACTIF')
                admin, erreur = _creer_admin(etablissement, admin_email, admin_nom, admin_prenom)
                if admin is None:
                    # Repli : on supprime l'établissement si sa création a échoué
                    etablissement.delete()
                    messages.error(request, erreur)
                else:
                    JournalAudit.objects.create(
                        action='CREATION_ETABLISSEMENT',
                        description=(f'Établissement {etablissement.nom} créé avec '
                                     f'administrateur {admin.get_full_name()} par '
                                     f'{request.user.get_full_name()}'),
                        utilisateur=request.user, etablissement=etablissement,
                        adresseIP=request.META.get('REMOTE_ADDR'))
                    messages.success(request,
                        f'Établissement {etablissement.nom} créé. Les identifiants '
                        f'de {admin.prenom} {admin.nom} ont été envoyés par e-mail.')
                    return redirect('super_etablissements')

        elif action == 'modifier_etablissement':
            etablissement_id = request.POST.get('etablissement_id', '')
            etablissement = etablissements.filter(pk=etablissement_id).first()
            if not etablissement:
                messages.error(request, 'Établissement introuvable.')
            else:
                etablissement.nom = request.POST.get('nom', etablissement.nom).strip() or etablissement.nom
                etablissement.adresse = request.POST.get('adresse', etablissement.adresse).strip() or etablissement.adresse
                etablissement.telephone = request.POST.get('telephone', etablissement.telephone).strip() or etablissement.telephone
                etablissement.email = request.POST.get('email', etablissement.email).strip().lower() or etablissement.email
                etablissement.statut = request.POST.get('statut', etablissement.statut)
                etablissement.save()
                JournalAudit.objects.create(
                    action='MODIFICATION_ETABLISSEMENT',
                    description=(f'Établissement {etablissement.nom} modifié par '
                                 f'{request.user.get_full_name()}'),
                    utilisateur=request.user, etablissement=etablissement,
                    adresseIP=request.META.get('REMOTE_ADDR'))
                # Création de l'administrateur au besoin (champs renseignés)
                admin_email = request.POST.get('admin_email', '').strip().lower()
                admin_nom = request.POST.get('admin_nom', '').strip()
                admin_prenom = request.POST.get('admin_prenom', '').strip()
                if admin_email and admin_nom and admin_prenom:
                    admin, erreur = _creer_admin(etablissement, admin_email, admin_nom, admin_prenom)
                    if admin is None:
                        messages.error(request, erreur)
                    else:
                        messages.success(request,
                            f'Identifiants de {admin.prenom} {admin.nom} envoyés par e-mail.')
                messages.success(request, f'Établissement {etablissement.nom} mis à jour.')
                return redirect('super_etablissements')

        elif action == 'suspendre_etablissement':
            etablissement_id = request.POST.get('etablissement_id', '')
            etablissement = etablissements.filter(pk=etablissement_id).first()
            if not etablissement:
                messages.error(request, 'Établissement introuvable.')
            elif etablissement.statut == 'SUSPENDU':
                messages.info(request, f'{etablissement.nom} est déjà suspendu.')
            else:
                etablissement.suspendre(motif='SUSPENSION_MANUELLE')
                JournalAudit.objects.create(
                    action='SUSPENSION_MANUELLE',
                    description=(f'Établissement {etablissement.nom} suspendu '
                                 f'manuellement par le Super Admin '
                                 f'({request.user.get_full_name()}).'),
                    utilisateur=request.user, etablissement=etablissement,
                    adresseIP=request.META.get('REMOTE_ADDR'))
                messages.warning(request, f'Établissement {etablissement.nom} suspendu.')

        elif action == 'reactiver_etablissement':
            etablissement_id = request.POST.get('etablissement_id', '')
            etablissement = etablissements.filter(pk=etablissement_id).first()
            if not etablissement:
                messages.error(request, 'Établissement introuvable.')
            elif etablissement.statut != 'SUSPENDU':
                messages.info(request, f'{etablissement.nom} n\'est pas suspendu.')
            else:
                etablissement.reactiver()
                JournalAudit.objects.create(
                    action='REACTIVATION_MANUELLE',
                    description=(f'Établissement {etablissement.nom} réactivé '
                                 f'manuellement par le Super Admin '
                                 f'({request.user.get_full_name()}).'),
                    utilisateur=request.user, etablissement=etablissement,
                    adresseIP=request.META.get('REMOTE_ADDR'))
                messages.success(request, f'Établissement {etablissement.nom} réactivé.')

    return render(request, 'core/super_etablissements.html',
                  {'etablissements': etablissements,
                   'administrateurs': administrateurs})


def super_abonnements(request):
    """Super admin : vue globale des abonnements et des formules."""
    if not _est_super_admin(request):
        return redirect('dashboard')
    from establishments.models import Abonnement, Formule
    return render(request, 'core/super_abonnements.html',
                  {'abonnements': Abonnement.objects.select_related(
                       'etablissement', 'formule').order_by('-dateDebut'),
                   'formules': Formule.objects.all().order_by('prix')})


def super_rapports(request):
    """Super admin : journal d'audit global inter-établissements."""
    if not _est_super_admin(request):
        return redirect('dashboard')
    from urgences.models import JournalAudit
    return render(request, 'core/super_rapports.html',
                  {'logs': JournalAudit.objects.select_related(
                       'etablissement', 'utilisateur'
                   ).order_by('-dateHeure')[:100]})
