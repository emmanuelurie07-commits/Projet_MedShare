from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render

from core.generateurs import (
    generer_matricule_admin,
    generer_mot_de_passe_provisoire,
)


def _serie_derniers_jours(qs, date_field, jours=7):
    """Compte les objets par jour pour les N derniers jours (graphiques).

    Retourne ``{'labels': [...], 'values': [...]}`` dont les labels sont au
    format JJ/MM — prêt pour Chart.js via ``json_script``.
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    aujourdhui = timezone.localdate()
    debut = aujourdhui - timedelta(days=jours - 1)
    rows = (
        qs.filter(**{f'{date_field}__date__gte': debut})
        .order_by(f'{date_field}__date')
        .values(f'{date_field}__date')
        .annotate(n=Count('pk'))
    )
    par_date = {r[f'{date_field}__date']: r['n'] for r in rows}
    labels, values = [], []
    for i in range(jours):
        jour = debut + timedelta(days=i)
        labels.append(jour.strftime('%d/%m'))
        values.append(par_date.get(jour, 0))
    return {'labels': labels, 'values': values}


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
        'repartition_etablissements': {
            'labels': ['Établissements actifs', 'Établissements suspendus'],
            'values': [
                Etablissement.objects.filter(statut='ACTIF').count(),
                Etablissement.objects.filter(statut='SUSPENDU').count(),
            ],
        },
        'repartition_plateforme': {
            'labels': ['Utilisateurs', 'Patients', 'Abonnements actifs'],
            'values': [
                Utilisateur.objects.count(),
                Patient.objects.count(),
                Abonnement.objects.filter(statut='ACTIF').count(),
            ],
        },
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
        'repartition_personnel': {
            'labels': ['Personnel actif', 'Autre personnel'],
            'values': [
                personnel_qs.filter(statutProfessionnel='ACTIF').count(),
                max(personnel_qs.count() - personnel_qs.filter(statutProfessionnel='ACTIF').count(), 0),
            ],
        },
        'repartition_attentes': {
            'labels': ['Candidatures en attente', 'Personnel actif'],
            'values': [
                Candidature.objects.filter(etablissement=etab, statut='EN_ATTENTE').count(),
                personnel_qs.filter(statutProfessionnel='ACTIF').count(),
            ],
        },
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
        'serie_consultations': _serie_derniers_jours(
            Consultation.objects.filter(medecin=user), 'dateHeure'),
        'repartition_activite': {
            'labels': ['Consultations récentes', 'DUT actifs',
                       'Correspondances en attente', 'Patients récents'],
            'values': [len(consultations_recentes), dut_actifs,
                       correspondances_en_attente, len(patients_recents)],
        },
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
        'repartition_urgences': {
            'labels': ['DUT actifs', 'En attente de triage', 'Correspondances'],
            'values': [dut_actifs, patients_attente, correspondances_count],
        },
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


_TEMPLATES_DASHBOARD = {
    'superadmin': 'core/dashboard_superadmin.html',
    'admin_hopital': 'core/dashboard_admin.html',
    'medecin': 'core/dashboard_medecin.html',
    'infirmier': 'core/dashboard_infirmier.html',
    'patient': 'core/dashboard_patient.html',
}

_CONTEXTS_DASHBOARD = {
    'superadmin': _contexte_superadmin,
    'admin_hopital': _contexte_admin_hopital,
    'medecin': _contexte_medecin,
    'infirmier': _contexte_infirmier,
    'patient': _contexte_patient,
}


def _role_dashboard(user):
    """Résout le rôle de tableau de bord d'un utilisateur connecté.

    La résolution s'appuie sur les propriétés métier, puis revérifie le champ
    ``role`` du sous-modèle concret (multi-table inheritance) : tant qu'un rôle
    valide est présent sur un Personnel actif, l'utilisateur accède à SON
    tableau de bord. ``'inconnu'`` n'est renvoyé que si le rôle est réellement
    absent ou nul (le message « Rôle non configuré » ne s'affiche alors que là).
    """
    if getattr(user, 'est_super_admin', False) or getattr(user, 'is_superuser', False):
        return 'superadmin'
    try:
        personnel = user.personnel_child
    except Exception:
        personnel = None
    if personnel is not None:
        if getattr(personnel, 'est_admin_hospital', False):
            return 'admin_hopital'
        if getattr(personnel, 'est_medecin', False):
            return 'medecin'
        if getattr(personnel, 'est_infirmier', False):
            return 'infirmier'
        if getattr(personnel, 'est_super_admin', False):
            return 'superadmin'
        role_obj = getattr(personnel, 'role', None)
        if role_obj is not None:
            nom_role = role_obj.nomRole
            if nom_role == 'Administrateur':
                return 'admin_hopital'
            if nom_role == 'Médecin':
                return 'medecin'
            if nom_role == 'Infirmier':
                return 'infirmier'
            if nom_role == 'Super Admin':
                return 'superadmin'
        return 'inconnu'
    try:
        user.patient_child
        return 'patient'
    except Exception:
        pass
    return 'inconnu'


def dashboard(request):
    """Point d'entrée : affiche le dashboard dédié au rôle de l'utilisateur."""
    if not request.user.is_authenticated:
        return redirect('login')

    user = request.user
    role = _role_dashboard(user)

    template_name = _TEMPLATES_DASHBOARD.get(role)
    if template_name:
        ctx = _CONTEXTS_DASHBOARD[role](user)
        return render(request, template_name, ctx)

    # Rôle réellement absent : on redirige vers l'espace à jeton du personnel,
    # qui affichera le message « Rôle non configuré » — jamais vers le login.
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
    role = _role_dashboard(request.user)
    template_name = _TEMPLATES_DASHBOARD.get(role)
    if template_name:
        return render(request, template_name, _CONTEXTS_DASHBOARD[role](request.user))
    # fallback : aucun rôle associé au compte
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
            f'Bonjour {admin.nom} {admin.prenom},\n\n'
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
                        f'de {admin.nom} {admin.prenom} ont été envoyés par e-mail.')
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
                            f'Identifiants de {admin.nom} {admin.prenom} envoyés par e-mail.')
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
    """Super admin : pilote le catalogue des formules et les abonnements des
    établissements (attribution, changement de formule, prolongation,
    suspension / activation).

    L'admin de l'établissement ne choisit plus sa formule : il renouvelle
    uniquement la formule qui lui a été attribuée (paiement simulé)."""
    from django.utils import timezone

    from django.db.models import ProtectedError

    from establishments.models import Abonnement, Etablissement, Formule
    from urgences.models import JournalAudit
    if not _est_super_admin(request):
        return redirect('dashboard')

    def _int(valeur):
        try:
            return int(valeur)
        except (TypeError, ValueError):
            return None

    def _a_deja_un_abonnement(etab):
        try:
            etab.abonnement
            return True
        except Exception:
            return False

    def _journal(act, description, etab):
        JournalAudit.objects.create(
            action=act, description=description, utilisateur=request.user,
            etablissement=etab, adresseIP=request.META.get('REMOTE_ADDR'))

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── Formules : création ─────────────────────────────────────────
        if action == 'creer_formule':
            nom = request.POST.get('nom', '').strip()
            prix = _int(request.POST.get('prix', ''))
            duree = _int(request.POST.get('dureeMois', ''))
            max_util = _int(request.POST.get('nbUtilisateursMax', ''))
            max_dmp = _int(request.POST.get('nbDMPMax', ''))
            if nom and prix is not None and duree and max_util is not None and max_dmp is not None:
                Formule.objects.create(
                    nom=nom, description=request.POST.get('description', '').strip(),
                    prix=prix, dureeMois=duree, nbUtilisateursMax=max_util,
                    nbDMPMax=max_dmp)
                messages.success(request, f'Formule « {nom} » créée.')
            else:
                messages.error(request,
                    'Champs obligatoires manquants ou invalides pour la formule.')

        # ── Formules : modification ─────────────────────────────────────
        elif action == 'modifier_formule':
            formule = Formule.objects.filter(
                pk=_int(request.POST.get('formule_id', ''))).first()
            if formule is None:
                messages.error(request, 'Formule introuvable.')
            else:
                nom = request.POST.get('nom', '').strip() or formule.nom
                prix = _int(request.POST.get('prix', ''))
                duree = _int(request.POST.get('dureeMois', ''))
                max_util = _int(request.POST.get('nbUtilisateursMax', ''))
                max_dmp = _int(request.POST.get('nbDMPMax', ''))
                if prix is None or duree is None or max_util is None or max_dmp is None:
                    messages.error(request, 'Champs numériques invalides.')
                else:
                    formule.nom = nom
                    formule.description = request.POST.get('description', '').strip()
                    formule.prix = prix
                    formule.dureeMois = duree
                    formule.nbUtilisateursMax = max_util
                    formule.nbDMPMax = max_dmp
                    formule.save()
                    messages.success(request, f'Formule « {formule.nom} » mise à jour.')

        # ── Formules : suppression ──────────────────────────────────────
        elif action == 'supprimer_formule':
            formule = Formule.objects.filter(
                pk=_int(request.POST.get('formule_id', ''))).first()
            if formule is None:
                messages.error(request, 'Formule introuvable.')
            else:
                try:
                    nom = formule.nom
                    formule.delete()
                    messages.success(request, f'Formule « {nom} » supprimée.')
                except ProtectedError:
                    messages.error(request,
                        'Impossible : des abonnements utilisent cette formule.')

        # ── Abonnements : attribution d'une formule à un établissement ──
        elif action == 'attribuer_abonnement':
            etab = Etablissement.objects.filter(
                pk=_int(request.POST.get('etablissement_id', ''))).first()
            formule = Formule.objects.filter(
                pk=_int(request.POST.get('formule_id', ''))).first()
            if not (etab and formule):
                messages.error(request, 'Établissement ou formule introuvable.')
            elif _a_deja_un_abonnement(etab):
                messages.error(request, f'{etab.nom} a déjà un abonnement.')
            else:
                mois = _int(request.POST.get('dureeMois', '')) or formule.dureeMois
                if mois <= 0:
                    mois = formule.dureeMois
                debut = timezone.now().date()
                fin = debut + timezone.timedelta(days=30 * mois)
                abo = Abonnement.objects.create(
                    etablissement=etab, formule=formule, dateDebut=debut,
                    dateFin=fin, statut=Abonnement.Statut.ACTIF)
                _journal('ATTRIBUTION_ABONNEMENT',
                         f'Formule {formule.nom} attribuée à {etab.nom} '
                         f'par {request.user.get_full_name()} — jusqu\'au {fin}.',
                         etab)
                messages.success(
                    request, f'Abonnement {formule.nom} attribué à {etab.nom} '
                    f'(jusqu\'au {abo.dateFin}).')

        # ── Abonnements : changement de formule en cours ────────────────
        elif action == 'changer_formule':
            abo = Abonnement.objects.select_related('etablissement').filter(
                pk=_int(request.POST.get('abonnement_id', ''))).first()
            formule = Formule.objects.filter(
                pk=_int(request.POST.get('formule_id', ''))).first()
            if not (abo and formule):
                messages.error(request, 'Abonnement ou formule introuvable.')
            else:
                ancienne = abo.formule.nom
                abo.formule = formule
                abo.save(update_fields=['formule'])
                _journal('CHANGEMENT_FORMULE',
                         f'Formule de {abo.etablissement.nom} passée de '
                         f'« {ancienne} » à « {formule.nom} » par '
                         f'{request.user.get_full_name()}.',
                         abo.etablissement)
                messages.success(
                    request, f'Formule de {abo.etablissement.nom} changée — '
                    f'nouvelle formule : {formule.nom}.')

        # ── Abonnements : prolongation ──────────────────────────────────
        elif action == 'prolonger_abonnement':
            abo = Abonnement.objects.select_related('etablissement').filter(
                pk=_int(request.POST.get('abonnement_id', ''))).first()
            mois = _int(request.POST.get('mois', ''))
            if not (abo and mois and mois > 0):
                messages.error(request, 'L\'abonnement ou la durée est invalide.')
            else:
                nouvelle_fin = abo.dateFin + timezone.timedelta(days=30 * mois)
                abo.activer()
                abo.dateFin = nouvelle_fin
                abo.save(update_fields=['statut', 'dateFin'])
                _journal('PROLONGATION_ABONNEMENT',
                         f'Abonnement de {abo.etablissement.nom} prolongé de '
                         f'{mois} mois jusqu\'au {nouvelle_fin} par '
                         f'{request.user.get_full_name()}.',
                         abo.etablissement)
                messages.success(
                    request, f'Abonnement prolongé jusqu\'au {nouvelle_fin}.')

        # ── Abonnements : suspension / activation ───────────────────────
        elif action == 'suspendre_abonnement':
            abo = Abonnement.objects.select_related('etablissement').filter(
                pk=_int(request.POST.get('abonnement_id', ''))).first()
            if abo is None:
                messages.error(request, 'Abonnement introuvable.')
            else:
                abo.suspendre()
                etab = abo.etablissement
                if etab.statut != 'SUSPENDU':
                    etab.suspendre(motif='SUSPENSION_MANUELLE')
                _journal('SUSPENSION_ABONNEMENT',
                         f'Abonnement de {etab.nom} suspendu par '
                         f'{request.user.get_full_name()}.',
                         etab)
                messages.warning(request, f'Abonnement de {etab.nom} suspendu.')

        elif action == 'activer_abonnement':
            abo = Abonnement.objects.select_related('etablissement').filter(
                pk=_int(request.POST.get('abonnement_id', ''))).first()
            if abo is None:
                messages.error(request, 'Abonnement introuvable.')
            else:
                abo.activer()
                etab = abo.etablissement
                if etab.statut == 'SUSPENDU' and etab.motifSuspension in (
                        'ABONNEMENT_EXPIRE', 'SUSPENSION_MANUELLE'):
                    etab.reactiver()
                _journal('ACTIVATION_ABONNEMENT',
                         f'Abonnement de {etab.nom} réactivé par '
                         f'{request.user.get_full_name()}.',
                         etab)
                messages.success(request, f'Abonnement de {etab.nom} réactivé.')

        return redirect('super_abonnements')

    abonnements = (Abonnement.objects.select_related('etablissement', 'formule')
                   .order_by('-dateDebut'))
    formules = Formule.objects.all().order_by('prix')
    etablissements_sans_abo = (Etablissement.objects
                               .filter(abonnement__isnull=True).order_by('nom'))
    return render(request, 'core/super_abonnements.html',
                  {'abonnements': abonnements, 'formules': formules,
                   'etablissements_sans_abo': etablissements_sans_abo})


def super_rapports(request):
    """Super admin : journal d'audit global inter-établissements."""
    if not _est_super_admin(request):
        return redirect('dashboard')
    from urgences.models import JournalAudit
    return render(request, 'core/super_rapports.html',
                  {'logs': JournalAudit.objects.select_related(
                       'etablissement', 'utilisateur'
                   ).order_by('-dateHeure')[:100]})
