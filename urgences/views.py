import os
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import Http404

from core.generateurs import generer_numero_dut
from users.decorators import block_superadmin, role_required, role_required_strict
from users.models import Patient

from .forms import ConstanteForm, DUTForm, RechercheIdentiteForm, TriageForm
from .models import (Constante, DossierUrgenceTemporaire, RechercheIdentite,
                      ServiceReconnaissanceFaciale as ServiceReconnaissanceFacialeModel,
                      Triage, JournalAudit)


def _get_user_role(request):
    return getattr(request, 'user_roles', set())


def _est_medecin(request):
    return request.user.is_superuser or 'Médecin' in _get_user_role(request)


def _est_infirmier(request):
    return request.user.is_superuser or 'Infirmier' in _get_user_role(request)


# ──────────────────────────────────────────────
# Liste des urgences actives
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def liste_urgences(request):
    etablissement = getattr(request.user, 'etablissement', None)
    if etablissement:
        duts = DossierUrgenceTemporaire.objects.filter(
            etablissement=etablissement
        ).order_by('-dateCreation')
    else:
        duts = DossierUrgenceTemporaire.objects.all().order_by('-dateCreation')
    return render(request, 'urgences/liste_urgences.html', {'duts': duts})


# ──────────────────────────────────────────────
# Création DUT (patient inconnu) — Étape 1
# Prise de vue & Recherche automatique vectorielle (face distance)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def creer_dut(request):
    if request.method == 'POST':
        form = DUTForm(request.POST, request.FILES)
        if form.is_valid():
            dut = form.save(commit=False)
            dut.etablissement = getattr(request.user, 'etablissement', None)
            # infirmier = user qui crée (peu importe rôle mais on trace)
            dut.infirmier = request.user
            dut.numeroDUT = generer_numero_dut()
            dut.save()

            # Journal audit : création DUT
            JournalAudit.objects.create(
                action='CRÉATION_DUT',
                description=f'DUT {dut.numeroDUT} créé par {request.user.get_full_name()} — photo capturée, recherche faciale lancée.',
                utilisateur=request.user,
                etablissement=dut.etablissement,
                adresseIP=request.META.get('REMOTE_ADDR')
            )

            # ── Lancement IMMÉDIAT de la recherche faciale (Étape 1 → Étape 2) ──
            # La photo du DUT sert de requête vs toutes les photos de profil patients.
            try:
                correspondances = _lancer_recherche_faciale(dut, request)
                if correspondances:
                    messages.success(request,
                        f'DUT {dut.numeroDUT} créé. '
                        f'{len(correspondances)} correspondance(s) détectée(s) — '
                        f'envoyées au médecin pour validation.'
                    )
                else:
                    messages.warning(request,
                        f'DUT {dut.numeroDUT} créé. Aucune correspondance trouvée. '
                        f'Patient probablement non enregistré.'
                    )
                # Redirige vers la page de résultats (comparatifs) — Étape 2
                return redirect('correspondances_dut', pk=dut.pk)
            except ValueError as e:
                messages.error(request, f'DUT {dut.numeroDUT} créé mais photo inexploitable : {e}')
                return redirect('detail_dut', pk=dut.pk)
            except Exception as e:
                messages.warning(request, f'DUT {dut.numeroDUT} créé. Recherche faciale en erreur : {e}')
                return redirect('detail_dut', pk=dut.pk)
    else:
        form = DUTForm()
    return render(request, 'urgences/creer_dut.html', {'form': form})


def _lancer_recherche_faciale(dut, request):
    """
    Exécute la comparaison face_distance entre photo DUT et toutes les photoProfil patients.
    Crée une RechercheIdentite par correspondance (top 5, seuil 60%).
    Retourne la liste des correspondances brutes.
    """
    if not dut.photo or not dut.photo.name:
        raise ValueError('Aucune photo associée au DUT.')

    photo_path = dut.photo.path
    if not os.path.exists(photo_path):
        raise ValueError('Fichier photo DUT introuvable sur le disque.')

    from facial_recognition import MODE_LIBELLE, MODE_RECHERCHE, ServiceReconnaissanceFaciale
    svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
    correspondances = svc.rechercher_correspondance(photo_path, seuil_confiance=60.0)
    mode = MODE_RECHERCHE

    # Enregistre le service (traçabilité) — nom distinct selon le mode réel/simulation
    service_obj, _ = ServiceReconnaissanceFacialeModel.objects.get_or_create(
        nom=f'ReconnaissanceFaciale_{mode}',
        defaults={'urlEndpoint': MODE_LIBELLE}
    )

    # Archive les anciennes recherches non confirmées pour ce DUT (relance)
    # Non-suppression (itération 3) : on passe les lignes en REJETEE au lieu
    # de les supprimer — traçabilité complète de chaque relance. On garde les CONFIRMEE.
    RechercheIdentite.objects.filter(dut=dut).exclude(statut='CONFIRMEE').update(
        statut='REJETEE')

    if not correspondances:
        # Aucune correspondance >60% — on enregistre une ligne AUCUNE
        RechercheIdentite.objects.create(
            dut=dut,
            etablissement=dut.etablissement,
            service=service_obj,
            statut='AUCUNE',
            confiance=None,
        )
        return []

    # Crée une ligne par correspondance (3 à 5)
    for corr in correspondances:
        patient_id = corr.get('patient_id')
        try:
            patient = Patient.objects.get(pk=patient_id)
        except Patient.DoesNotExist:
            continue
        RechercheIdentite.objects.create(
            dut=dut,
            etablissement=dut.etablissement,
            service=service_obj,
            statut='CORRESPONDANCE_TROUVEE',
            patientCorrespondant=patient,
            confiance=corr.get('confiance'),
        )

    # Journal audit
    JournalAudit.objects.create(
        action='RECHERCHE_FACIALE',
        description=f'Recherche faciale DUT {dut.numeroDUT} : {len(correspondances)} correspondance(s) >60% (max {correspondances[0]["confiance"]}%) — mode {mode} ({MODE_LIBELLE}).',
        utilisateur=request.user,
        etablissement=dut.etablissement,
        adresseIP=request.META.get('REMOTE_ADDR')
    )

    return correspondances


# ──────────────────────────────────────────────
# Page des Résultats — Suggestions de Correspondances (Étape 2)
# Tableau comparatif inspiré de la maquette stitch "rattachement_d_identit_medshare/code.html"
# Infirmier = lecture seule (grisé), Médecin = peut VOIR & CONFIRMER
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def correspondances_dut(request, pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=pk)
    # Vérif établissement isolé
    etab_user = getattr(request.user, 'etablissement', None)
    if etab_user and dut.etablissement and dut.etablissement != etab_user and not request.user.is_superuser:
        raise Http404('DUT non accessible pour votre établissement.')

    triage = getattr(dut, 'triage', None)
    constantes = dut.constantes.all().order_by('-date')
    recherches = dut.recherches_identite.select_related('patientCorrespondant').all()

    # Filtre uniquement les correspondances trouvées >60%
    correspondances = recherches.filter(statut='CORRESPONDANCE_TROUVEE').order_by('-confiance')[:5]
    has_confirmed = recherches.filter(statut='CONFIRMEE').exists()
    recherche_confirmee = recherches.filter(statut='CONFIRMEE').first()
    # Aucune correspondance ?
    aucune = recherches.filter(statut='AUCUNE').exists()

    is_medecin = _est_medecin(request)
    is_infirmier = not is_medecin and _est_infirmier(request)

    # Si DUT déjà fusionné → on affiche la fiche vitale
    fiche_vitale = None
    patient_vital = None
    if dut.identiteConfirmee and dut.dmpRattache:
        patient_vital = dut.dmpRattache.patient
        fiche_vitale = _construire_fiche_vitale(dut, patient_vital)

    # Mode du moteur de reconnaissance (réel / simulation démo) — étiquetage UI
    from facial_recognition import MODE_LIBELLE, MODE_RECHERCHE
    mode_reel = MODE_RECHERCHE == 'reel'

    context = {
        'dut': dut,
        'triage': triage,
        'constantes': constantes,
        'correspondances': correspondances,
        'recherches': recherches,
        'has_confirmed': has_confirmed,
        'recherche_confirmee': recherche_confirmee,
        'aucune': aucune,
        'is_medecin': is_medecin,
        'is_infirmier': is_infirmier,
        'fiche_vitale': fiche_vitale,
        'patient_vital': patient_vital,
        'mode_reel': mode_reel,
        'mode_recherche': MODE_RECHERCHE,
        'mode_libelle': MODE_LIBELLE,
    }
    return render(request, 'urgences/correspondances.html', context)


def _construire_fiche_vitale(dut, patient):
    """
    Données critiques pour sauver le patient (Break Glass).
    Inspiré de la capture "AVERTISSEMENTS VITAUX & ANTÉCÉDENTS".
    """
    dmp = getattr(patient, 'dmp', None)
    # Traitements depuis prescriptions actives (dernières consultations)
    traitements = []
    antecedents = patient.liste_antecedents if hasattr(patient, 'liste_antecedents') else []
    allergies = patient.liste_allergies if hasattr(patient, 'liste_allergies') else []
    if dmp:
        for c in dmp.consultations.select_related('prescription').all()[:3]:
            if hasattr(c, 'prescription'):
                lignes = c.prescription.lignes.select_related('medicament').all()
                for l in lignes:
                    traitements.append(f"{l.medicament.nomCommercial} — {l.posologie}")
        if not traitements and patient.traitementEnCours:
            traitements = [t.strip() for t in patient.traitementEnCours.split(',') if t.strip()]

    # Constantes récentes du DUT (transférées)
    soins_urgences = []
    for const in dut.constantes.all().order_by('date')[:5]:
        soins_urgences.append(f"{const.date:%H:%M} — FC {const.frequenceCardiaque or '-'} bpm, TA {const.tensionArterielle or '-'}")

    if not soins_urgences and dut.informationsInitiales:
        soins_urgences = [dut.informationsInitiales]

    return {
        'groupe_sanguin': patient.groupeSanguin or '— Non renseigné',
        'allergies': allergies or ['— Aucune connue'],
        'antecedents': antecedents or ['— Aucun renseigné'],
        'traitement': traitements or ['— Aucun'],
        'contact_nom': patient.nomContactUrgencePrincipal,
        'contact_tel': patient.telephoneContactUrgencePrincipal,
        'contact_lien': patient.lienContactUrgencePrincipal,
        'soins_urgences': soins_urgences,
    }


# ──────────────────────────────────────────────
# Détail DUT (vue technique complète)
# ──────────────────────────────────────────────
@login_required
@block_superadmin
def detail_dut(request, pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=pk)
    etab_user = getattr(request.user, 'etablissement', None)
    if etab_user and dut.etablissement and dut.etablissement != etab_user and not request.user.is_superuser:
        raise Http404('Accès refusé.')
    triage = getattr(dut, 'triage', None)
    constantes = dut.constantes.all().order_by('-date')
    recherches = dut.recherches_identite.select_related('patientCorrespondant', 'confirmePar').all()
    is_medecin = _est_medecin(request)
    return render(request, 'urgences/detail_dut.html', {
        'dut': dut, 'triage': triage,
        'constantes': constantes, 'recherches': recherches,
        'is_medecin': is_medecin,
        'est_medecin': is_medecin,  # alias pour template legacy
    })


# ──────────────────────────────────────────────
# Triage
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def creer_triage(request, dut_pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=dut_pk)
    if hasattr(dut, 'triage'):
        messages.info(request, 'Un triage existe déjà pour ce DUT.')
        return redirect('detail_dut', pk=dut.pk)

    if request.method == 'POST':
        form = TriageForm(request.POST)
        if form.is_valid():
            from dmp.views import _verifier_approbation_patient
            patient = dut.dmpRattache.patient if (dut.identiteConfirmee and dut.dmpRattache) else None
            ok, erreur, _dem = _verifier_approbation_patient(
                patient, dut.etablissement, demandeur=request.user)
            if not ok:
                form.add_error(None, erreur)
            else:
                triage = form.save(commit=False)
                triage.dut = dut
                triage.etablissement = dut.etablissement
                triage.save()
                messages.success(request, 'Triage enregistré.')
                return redirect('detail_dut', pk=dut.pk)
    else:
        form = TriageForm()
    from dmp.services import acces_pour_dmp
    from dmp.views import _demande_en_attente
    approbation_active = acces_pour_dmp(dut.dmpRattache, dut.etablissement) is not None
    patient = dut.dmpRattache.patient if (dut.identiteConfirmee and dut.dmpRattache) else None
    demande_en_attente = _demande_en_attente(patient, dut.etablissement)
    return render(request, 'urgences/creer_triage.html',
                  {'form': form, 'dut': dut, 'approbation_active': approbation_active,
                   'demande_en_attente': demande_en_attente})


# ──────────────────────────────────────────────
# Constantes vitales
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def ajouter_constante(request, dut_pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=dut_pk)
    if request.method == 'POST':
        form = ConstanteForm(request.POST)
        if form.is_valid():
            from dmp.views import _verifier_approbation_patient
            patient = dut.dmpRattache.patient if (dut.identiteConfirmee and dut.dmpRattache) else None
            ok, erreur, _dem = _verifier_approbation_patient(
                patient, dut.etablissement, demandeur=request.user)
            if not ok:
                form.add_error(None, erreur)
            else:
                constante = form.save(commit=False)
                constante.dut = dut
                constante.etablissement = dut.etablissement
                constante.save()
                messages.success(request, 'Constantes enregistrées.')
                return redirect('detail_dut', pk=dut.pk)
    else:
        form = ConstanteForm()
    from dmp.services import acces_pour_dmp
    from dmp.views import _demande_en_attente
    approbation_active = acces_pour_dmp(dut.dmpRattache, dut.etablissement) is not None
    patient = dut.dmpRattache.patient if (dut.identiteConfirmee and dut.dmpRattache) else None
    demande_en_attente = _demande_en_attente(patient, dut.etablissement)
    return render(request, 'urgences/ajouter_constante.html',
                  {'form': form, 'dut': dut, 'approbation_active': approbation_active,
                   'demande_en_attente': demande_en_attente})


# ──────────────────────────────────────────────
# Recherche d'identité (relance manuelle)
# Peut être relancée même après un AUCUNE
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def rechercher_identite(request, dut_pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=dut_pk)

    # Si la DUT a déjà une photo → relance directe sans re-upload
    if request.method == 'POST':
        form = RechercheIdentiteForm(request.POST, request.FILES)
        # Cas 1 : l'utilisateur fournit une nouvelle photo (écrase DUT photo)
        if form.is_valid() and form.cleaned_data.get('photo'):
            photo = form.cleaned_data['photo']
            # Sauvegarde temporaire pour analyse
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                for chunk in photo.chunks():
                    f.write(chunk)
                tmp_path = f.name
            try:
                from facial_recognition import ServiceReconnaissanceFaciale
                svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
                # Option : remplacer la photo DUT par la nouvelle si demandée
                # On ne remplace que si l'utilisateur a coché (ici on suppose oui si upload)
                # Mais pour traçabilité on garde la photo originale et on analyse la nouvelle
                correspondances = svc.rechercher_correspondance(tmp_path, seuil_confiance=60.0)
                # Enregistre les nouvelles correspondances
                service_obj, _ = ServiceReconnaissanceFacialeModel.objects.get_or_create(
                    nom=f'ReconnaissanceFaciale_{svc.mode}',
                    defaults={'urlEndpoint': svc.mode_libelle}
                )
                RechercheIdentite.objects.filter(dut=dut).exclude(statut='CONFIRMEE').update(
                    statut='REJETEE')
                if correspondances:
                    for corr in correspondances:
                        try:
                            patient = Patient.objects.get(pk=corr['patient_id'])
                        except Patient.DoesNotExist:
                            continue
                        RechercheIdentite.objects.create(
                            dut=dut, etablissement=dut.etablissement,
                            service=service_obj, statut='CORRESPONDANCE_TROUVEE',
                            patientCorrespondant=patient, confiance=corr['confiance']
                        )
                    messages.success(request, f'{len(correspondances)} correspondance(s) trouvée(s).')
                else:
                    RechercheIdentite.objects.create(
                        dut=dut, etablissement=dut.etablissement,
                        service=service_obj, statut='AUCUNE'
                    )
                    messages.warning(request, 'Aucune correspondance trouvée.')
                return redirect('correspondances_dut', pk=dut.pk)
            except ValueError as e:
                messages.error(request, f'Photo inexploitable : {e}')
                return redirect('detail_dut', pk=dut.pk)
            except Exception as e:
                messages.error(request, f'Erreur recherche : {e}')
                return redirect('detail_dut', pk=dut.pk)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            # Cas 2 : relance sur la photo DUT existante (bouton "Relancer recherche")
            try:
                correspondances = _lancer_recherche_faciale(dut, request)
                if correspondances:
                    messages.success(request, f'{len(correspondances)} correspondance(s) relancée(s).')
                else:
                    messages.warning(request, 'Aucune correspondance après relance.')
                return redirect('correspondances_dut', pk=dut.pk)
            except ValueError as e:
                messages.error(request, f'Photo inexploitable : {e}')
                return redirect('detail_dut', pk=dut.pk)
            except Exception as e:
                messages.error(request, f'Erreur relance : {e}')
                return redirect('detail_dut', pk=dut.pk)
    else:
        form = RechercheIdentiteForm()
    return render(request, 'urgences/rechercher_identite.html', {'form': form, 'dut': dut})


# ──────────────────────────────────────────────
# Confirmation & Fusion DUT→DMP (MÉDECIN UNIQUEMENT)
# Étape 3 : Rapprochement sécurisé + Ouverture Fiche Vitale
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin')
def confirmer_identite(request, pk):
    """
    Valide manuellement une correspondance trouvée.
    Seul le médecin peut confirmer et fusionner.
    L'infirmier voit les correspondances en lecture seule (grisé).
    """
    recherche = get_object_or_404(RechercheIdentite, pk=pk)
    dut = recherche.dut

    # Sécurité : seul statut CORRESPONDANCE_TROUVEE peut être confirmé
    if recherche.statut != 'CORRESPONDANCE_TROUVEE':
        messages.error(request, 'Cette recherche ne peut pas être confirmée (statut incorrect).')
        return redirect('correspondances_dut', pk=dut.pk)

    if dut.identiteConfirmee:
        messages.warning(request, f'DUT {dut.numeroDUT} déjà rattaché à {dut.dmpRattache}.')
        return redirect('correspondances_dut', pk=dut.pk)

    if request.method == 'POST':
        # patient_id peut venir du POST (explicite) ou de la recherche
        patient_id = request.POST.get('patient_id') or getattr(recherche.patientCorrespondant, 'pk', None)
        if not patient_id:
            messages.error(request, 'Aucun patient correspondant.')
            return redirect('correspondances_dut', pk=dut.pk)
        patient = get_object_or_404(Patient, pk=patient_id)
        dmp = getattr(patient, 'dmp', None)
        if not dmp:
            messages.error(request, f'Aucun DMP trouvé pour {patient.prenom} {patient.nom} — fusion impossible.')
            return redirect('correspondances_dut', pk=dut.pk)

        # ── Rapprochement sécurisé en BDD ───────────────────────────────
        recherche.patientCorrespondant = patient
        recherche.confirmePar = request.user
        recherche.statut = 'CONFIRMEE'
        recherche.dateConfirmation = timezone.now()
        recherche.save()

        # Cloture les autres correspondances pour ce DUT (non choisies)
        RechercheIdentite.objects.filter(dut=dut).exclude(pk=recherche.pk).exclude(statut='CONFIRMEE').update(statut='AUCUNE')

        # Fusion DUT → DMP (transfert soins urgences)
        dut.fusionner_avec_dmp(dmp)

        # Journal audit RGPD + Break Glass
        JournalAudit.objects.create(
            action='FUSION_DUT_DMP',
            description=f'DUT {dut.numeroDUT} rattaché à PAT {patient.numeroPatient} ({patient.prenom} {patient.nom}) par Dr {request.user.get_full_name()} — confiance {recherche.confiance}%',
            utilisateur=request.user,
            etablissement=dut.etablissement,
            adresseIP=request.META.get('REMOTE_ADDR'),
            patient=patient,
        )
        JournalAudit.objects.create(
            action='BREAK_GLASS_OUVERTURE',
            description=f'Fiche Vitale ouverte pour {patient.numeroPatient} via DUT {dut.numeroDUT} (allergies, groupe sanguin, antécédents).',
            utilisateur=request.user,
            etablissement=dut.etablissement,
            adresseIP=request.META.get('REMOTE_ADDR'),
            patient=patient,
        )

        # Notification e-mail au patient identifié (fusion DUT → DMP)
        try:
            from core.notifications import envoyer_email
            envoyer_email(
                request,
                patient.email,
                'Votre prise en charge d’urgence a été rattachée à votre DMP',
                (
                    f'Bonjour {patient.prenom} {patient.nom},\n\n'
                    f'Lors de votre passage aux urgences de '
                    f'{dut.etablissement.nom if dut.etablissement else "l\'établissement"}, '
                    f'un dossier d\'urgence temporaire (DUT {dut.numeroDUT}) a été créé.\n'
                    f'Votre identité a été confirmée par le médecin et ce dossier a été '
                    f'rattaché à votre Dossier Médical Partagé (DMP {dmp.numeroDMP}).\n\n'
                    f'Les informations de cette prise en charge sont désormais '
                    f'consultables par les professionnels autorisés.\n'
                    f'Cordialement,\nl\'équipe MedShare'
                )
            )
        except Exception:
            pass

        messages.success(request,
            f'Identité confirmée : {patient.prenom} {patient.nom} ({patient.numeroPatient}) — '
            f'DUT {dut.numeroDUT} fusionné avec DMP {dmp.numeroDMP}. '
            f'Fiche d’Urgence Vitale déverrouillée.'
        )
        return redirect('fiche_vitale', dut_pk=dut.pk)

    # GET → redirige vers page correspondances (il faut POST)
    return redirect('correspondances_dut', pk=dut.pk)


# ──────────────────────────────────────────────
# Fiche d'Urgence Vitale (Break Glass)
# Accessible après fusion OU via Break Glass direct (médecin)
# Affiche les données critiques pour sauver le patient
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin', 'Infirmier', 'Administrateur')
def fiche_vitale(request, dut_pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=dut_pk)
    etab_user = getattr(request.user, 'etablissement', None)
    if etab_user and dut.etablissement and dut.etablissement != etab_user and not request.user.is_superuser:
        raise Http404('Accès refusé.')

    # Si pas encore fusionné : on propose Break Glass uniquement au médecin
    if not dut.identiteConfirmee or not dut.dmpRattache:
        # Médecin peut voir DUT même sans identité via Break Glass (infos DUT seules)
        is_medecin = _est_medecin(request)
        if not is_medecin:
            messages.error(request, 'Identité non confirmée — fiche vitale réservée au médecin.')
            return redirect('correspondances_dut', pk=dut.pk)
        # Break Glass sur DUT non fusionné → montre infos DUT + alerte
        if request.method == 'POST' or request.GET.get('break_glass') == '1':
            JournalAudit.objects.create(
                action='BREAK_GLASS_DUT_NON_FUSIONNE',
                description=f'Break Glass DUT {dut.numeroDUT} par {request.user.get_full_name()} (identité non confirmée)',
                utilisateur=request.user,
                etablissement=dut.etablissement,
                adresseIP=request.META.get('REMOTE_ADDR')
            )
            messages.warning(request, 'Break Glass activé sur DUT non rattaché — informations limitées (photo + triage + constantes).')
        # Affiche page avec warning
        patient = None
        fiche = {
            'groupe_sanguin': '— Inconnu (identité non confirmée)',
            'allergies': ['— Inconnues — Break Glass partiel'],
            'antecedents': ['— Inconnus'],
            'traitement': ['— Inconnu'],
            'contact_nom': '—',
            'contact_tel': '—',
            'contact_lien': '—',
            'soins_urgences': [dut.informationsInitiales or '—'],
        }
        return render(request, 'urgences/fiche_vitale.html', {
            'dut': dut, 'patient': patient, 'fiche': fiche,
            'is_medecin': True, 'non_fusionne': True
        })

    # Cas normal : DUT fusionné → fiche vitale complète
    patient = dut.dmpRattache.patient
    fiche = _construire_fiche_vitale(dut, patient)
    is_medecin = _est_medecin(request)

    # Log Break Glass si médecin accède
    if is_medecin:
        JournalAudit.objects.create(
            action='BREAK_GLASS_CONSULTATION',
            description=f'Consultation Fiche Vitale DUT {dut.numeroDUT} / PAT {patient.numeroPatient} par {request.user.get_full_name()}',
            utilisateur=request.user,
            etablissement=dut.etablissement,
            adresseIP=request.META.get('REMOTE_ADDR')
        )

    return render(request, 'urgences/fiche_vitale.html', {
        'dut': dut, 'patient': patient, 'fiche': fiche,
        'dmp': dut.dmpRattache,
        'is_medecin': is_medecin, 'non_fusionne': False
    })


@login_required
@role_required_strict('Médecin', 'Infirmier', 'Administrateur')
def break_glass(request, dut_pk):
    """Raccourci Break Glass — redirige vers fiche_vitale avec flag."""
    return redirect(f'/urgences/{dut_pk}/fiche-vitale/?break_glass=1')


# ──────────────────────────────────────────────
# Vues distinctes pour sidebar Infirmier (éviter statique)
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def liste_triage(request):
    """Page Triage : tous les DUT avec/sans triage, bouton vers creer_triage"""
    etablissement = getattr(request.user, 'etablissement', None)
    qs = DossierUrgenceTemporaire.objects.select_related('triage', 'infirmier').order_by('-dateCreation')
    if etablissement:
        qs = qs.filter(etablissement=etablissement)
    return render(request, 'urgences/liste_triage.html', {'duts': qs, 'etablissement': etablissement})


@login_required
@role_required_strict('Infirmier', 'Médecin', 'Administrateur')
def liste_identification(request):
    """Page Identification : DUTs avec correspondances >60% (veille)"""
    etablissement = getattr(request.user, 'etablissement', None)
    qs = DossierUrgenceTemporaire.objects.filter(recherches_identite__statut='CORRESPONDANCE_TROUVEE').distinct().order_by('-dateCreation')
    if etablissement:
        qs = qs.filter(etablissement=etablissement)
    # Pour chaque DUT, on passe ses correspondances
    from django.db.models import Count
    qs = qs.annotate(nb_correspondances=Count('recherches_identite'))
    return render(request, 'urgences/liste_identification.html', {'duts': qs, 'etablissement': etablissement})


# ──────────────────────────────────────────────
# Clôture DUT (addendum 4, T3)
# Clôture DÉFINITIVE uniquement par un Médecin, manuellement, avec motif.
# Aucune fermeture automatique : après 72 h sans correspondance validée, le
# DUT passe en EN_ATTENTE_PROLONGEE (réversible) — voir
# urgences.services.appliquer_politique_cloture_dut.
# ──────────────────────────────────────────────
@login_required
@role_required_strict('Médecin')
def cloturer_dut(request, pk):
    dut = get_object_or_404(DossierUrgenceTemporaire, pk=pk)
    etab_user = getattr(request.user, 'etablissement', None)
    if etab_user and dut.etablissement and dut.etablissement != etab_user and not request.user.is_superuser:
        raise Http404('Accès refusé.')
    if dut.statut in (DossierUrgenceTemporaire.Statut.INACTIF,):
        messages.info(request, f'DUT {dut.numeroDUT} déjà clôturé.')
        return redirect('detail_dut', pk=dut.pk)

    if request.method != 'POST':
        return redirect('detail_dut', pk=dut.pk)

    motif = (request.POST.get('motif') or '').strip()
    if not motif:
        messages.error(request, 'Veuillez renseigner un motif pour la clôture.')
        return redirect('detail_dut', pk=dut.pk)

    dut.cloturer(motif=motif)
    patient = dut.dmpRattache.patient if (dut.identiteConfirmee and dut.dmpRattache) else None
    JournalAudit.objects.create(
        action='CLOTURE_DUT',
        description=f'DUT {dut.numeroDUT} clôturé par Dr {request.user.get_full_name()} — motif : {motif}',
        utilisateur=request.user,
        etablissement=dut.etablissement,
        adresseIP=request.META.get('REMOTE_ADDR'),
        patient=patient,
    )
    messages.info(request, f'DUT {dut.numeroDUT} clôturé.')
    return redirect('liste_urgences')

