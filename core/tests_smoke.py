"""Balayage automatique de toutes les pages (anti-500).

Objectif : déterministe, on ne dépend plus d'un parcours manuel pour remarquer
qu'un bouton renvoie une erreur serveur. Le test demande TOUTES les URL de
l'URLconf racine pour chaque profil (patient, infirmier, médecin,
administrateur, super admin) et échoue si une page renvoie un statut >= 500.

Un 403 (rôle non autorisé) ou une redirection (2FA, mot de passe à changer)
n'est PAS une panne : seules les erreurs serveur 5xx sont signalées.
"""
from datetime import timedelta
from io import BytesIO

from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from dmp.models import (AccesDMP, Consultation, DossierMedicalPartage,
                        Medicament, Prescription)
from establishments.models import (Abonnement, Candidature, Etablissement,
                                   Formule)
from urgences.models import (Constante, DossierUrgenceTemporaire,
                             RechercheIdentite, Triage)
from users.models import Patient, Personnel, Role

MDP = 'Mdp123!'


def photo(nom='photo.jpg'):
    """ Petite image valide pour les téléversements de test. """
    tampon = BytesIO()
    Image.new('RGB', (48, 48), (140, 110, 90)).save(tampon, format='JPEG')
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/jpeg')


class StockageIllisible(Storage):
    """Stockage qui échoue comme le système de fichiers EN LECTURE SEULE de
    Vercel (le seul endroit inscriptible est /tmp). Reproduit le plantage du
    bouton « Créer un DUT » sur le site déployé."""

    def _open(self, name, mode='rb'):
        raise OSError(30, 'Read-only file system')

    def _save(self, name, content):
        raise OSError(30, 'Read-only file system')

    def exists(self, name):
        return False

    def url(self, name):
        return f'/media/{name}'


class BaseSmoke(TestCase):
    """Jeu de données minimal mais réaliste : un établissement actif, un
    compte par rôle, un patient avec son DMP, une consultation, une ordonnance,
    une demande d'accès, un DUT avec son triage et une candidature."""

    @classmethod
    def setUpTestData(cls):
        jour = timezone.localdate()
        cls.etab = Etablissement.objects.create(
            nom='Hôpital Smoke', adresse='Rue test', telephone='690000000',
            email='smoke@test.cm')
        formule = Formule.objects.create(
            nom='Formule test', description='', prix=10000, dureeMois=1,
            nbUtilisateursMax=50, nbDMPMax=500)
        Abonnement.objects.create(
            etablissement=cls.etab, formule=formule, dateDebut=jour,
            dateFin=jour + timedelta(days=30))

        cls.roles = {}
        for nom in ('Médecin', 'Infirmier', 'Administrateur'):
            cls.roles[nom] = Role.objects.create(nomRole=nom)

        def creer_personnel(email, nom, role, matricule, superuser=False):
            if superuser:
                u = Personnel.objects.create_superuser(
                    email=email, nom=nom, prenom='Test', password=MDP,
                    matricule=matricule, etablissement=cls.etab,
                    doitChangerMotDePasse=False)
            else:
                u = Personnel.objects.create_user(
                    email=email, nom=nom, prenom='Test', password=MDP,
                    matricule=matricule, etablissement=cls.etab,
                    doitChangerMotDePasse=False)
            u.role = cls.roles[role]
            u.save()
            return u

        cls.medecin = creer_personnel('medecin@smoke.cm', 'Medecin', 'Médecin', 'MED-01')
        cls.infirmier = creer_personnel('infirmier@smoke.cm', 'Infirmier', 'Infirmier', 'INF-01')
        cls.admin = creer_personnel('admin@smoke.cm', 'Admin', 'Administrateur', 'ADM-01')
        cls.superadmin = creer_personnel('super@smoke.cm', 'Super', 'Administrateur',
                                        'SUP-01', superuser=True)

        cls.patient = Patient.objects.create_user(
            email='patient@smoke.cm', nom='Patient', prenom='Test', password=MDP,
            numeroPatient='PAT-SMOKE-01', doitChangerMotDePasse=False,
            nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='690000001',
            lienContactUrgencePrincipal='Mère')
        cls.dmp = DossierMedicalPartage.objects.create(
            patient=cls.patient, numeroDMP='DMP-SMOKE-01')
        cls.consultation = Consultation.objects.create(
            dmp=cls.dmp, etablissement=cls.etab, medecin=cls.medecin,
            motif='Fièvre', diagnostic='Paludisme')
        medicament = Medicament.objects.create(nomCommercial='Paracétamol', forme='Cp')
        prescription = Prescription.objects.create(
            consultation=cls.consultation, instructions='Après repas')
        prescription.lignes.create(
            medicament=medicament, posologie='1 cp', frequence='2x/j',
            duree='3 j', quantite='6')
        cls.acces = AccesDMP.objects.create(
            patient=cls.patient, etablissement=cls.etab,
            demandeur=cls.medecin, statut=AccesDMP.Statut.ACCORDE)
        cls.acces.approuver()

        cls.dut = DossierUrgenceTemporaire.objects.create(
            etablissement=cls.etab, infirmier=cls.infirmier, numeroDUT='DUT-SMOKE-01',
            informationsInitiales='Patient inconscient')
        Triage.objects.create(
            dut=cls.dut, etablissement=cls.etab, priorite='JAUNE',
            motifArrivee='Forte fièvre')
        Constante.objects.create(
            dut=cls.dut, etablissement=cls.etab, temperature=39.5)
        cls.recherche = RechercheIdentite.objects.create(
            dut=cls.dut, etablissement=cls.etab,
            patientCorrespondant=cls.patient, statut=RechercheIdentite.Statut.CONFIRMEE)

        cls.candidature = Candidature.objects.create(
            nom='Candidat', prenom='Test', email='cand@smoke.cm',
            telephone='690000002', etablissement=cls.etab, roleDemande='Infirmier')

    # ──────────────────────────────────────────
    def _urls(self, jeton_patient, jeton_personnel):
        """Liste exhaustive (nom, URL) de toutes les pages de l'application."""
        p, pk_pat = self.patient, self.patient.pk
        return [
            ('login', '/'),
            ('dashboard', reverse('dashboard')),
            ('dashboard_personnel', reverse('dashboard_personnel',
                                            kwargs={'jeton': jeton_personnel})),
            ('super_etablissements', reverse('super_etablissements')),
            ('super_abonnements', reverse('super_abonnements')),
            ('super_rapports', reverse('super_rapports')),
            ('mon_profil', reverse('mon_profil')),
            ('changer_mot_de_passe', reverse('changer_mot_de_passe')),
            ('changer_mot_de_passe_succes', reverse('changer_mot_de_passe_succes')),
            ('password_change', reverse('password_change')),
            ('password_change_done', reverse('password_change_done')),
            ('dashboard_patient', reverse('dashboard_patient',
                                          kwargs={'jeton': jeton_patient})),
            ('superadmin_2fa', reverse('superadmin_2fa')),
            ('superadmin_2fa_verifier', reverse('superadmin_2fa_verifier')),
            ('mot_de_passe_oublie', reverse('mot_de_passe_oublie')),
            ('reinitialiser_mot_de_passe',
             reverse('reinitialiser_mot_de_passe', kwargs={'jeton': 'invalide'})),
            # etablissements/
            ('soumettre_candidature', reverse('soumettre_candidature')),
            ('candidature_confirmation',
             reverse('candidature_confirmation', args=[self.candidature.pk])),
            ('consulter_candidature', reverse('consulter_candidature')),
            ('gestion_candidatures', reverse('gestion_candidatures')),
            ('detail_candidature',
             reverse('detail_candidature', args=[self.candidature.pk])),
            ('supprimer_candidature',
             reverse('supprimer_candidature', args=[self.candidature.pk])),
            ('mon_etablissement', reverse('mon_etablissement')),
            ('liste_personnel', reverse('liste_personnel')),
            ('abonnement_detail', reverse('abonnement_detail')),
            ('journal_audit', reverse('journal_audit')),
            # dmp/
            ('rechercher_patient', reverse('rechercher_patient')),
            ('creer_patient', reverse('creer_patient')),
            ('detail_patient', reverse('detail_patient', args=[pk_pat])),
            ('consulter_dmp', reverse('consulter_dmp', args=[pk_pat])),
            ('creer_consultation', reverse('creer_consultation', args=[pk_pat])),
            ('liste_consultations', reverse('liste_consultations')),
            ('detail_consultation',
             reverse('detail_consultation', args=[self.consultation.pk])),
            ('creer_ordonnance',
             reverse('creer_ordonnance', args=[self.consultation.pk])),
            ('liste_prescriptions', reverse('liste_prescriptions')),
            ('dmp_dashboard', reverse('dmp_dashboard')),
            ('mes_ordonnances', reverse('mes_ordonnances', args=[pk_pat])),
            ('mon_historique', reverse('mon_historique', args=[pk_pat])),
            ('mes_ordonnances_self', reverse('mes_ordonnances_self')),
            ('mon_historique_self', reverse('mon_historique_self')),
            ('mon_acces_historique_self', reverse('mon_acces_historique_self')),
            ('mon_acces_historique', reverse('mon_acces_historique', args=[pk_pat])),
            ('renvoyer_notification_acces',
             reverse('renvoyer_notification_acces', args=[self.acces.pk])),
            ('acces_dmp_repondre', reverse('acces_dmp_repondre', args=[self.acces.pk])),
            # urgences/
            ('liste_urgences', reverse('liste_urgences')),
            ('liste_triage', reverse('liste_triage')),
            ('liste_identification', reverse('liste_identification')),
            ('creer_dut', reverse('creer_dut')),
            ('detail_dut', reverse('detail_dut', args=[self.dut.pk])),
            ('correspondances_dut', reverse('correspondances_dut', args=[self.dut.pk])),
            ('fiche_vitale', reverse('fiche_vitale', args=[self.dut.pk])),
            ('break_glass', reverse('break_glass', args=[self.dut.pk])),
            ('creer_triage', reverse('creer_triage', args=[self.dut.pk])),
            ('ajouter_constante', reverse('ajouter_constante', args=[self.dut.pk])),
            ('rechercher_identite', reverse('rechercher_identite', args=[self.dut.pk])),
            ('confirmer_identite',
             reverse('confirmer_identite', args=[self.recherche.pk])),
            ('cloturer_dut', reverse('cloturer_dut', args=[self.dut.pk])),
        ]

    def _balayer(self, email, deux_fa=False):
        """Connexion puis GET sur toutes les pages. Retourne la liste des pannes."""
        self.client.logout()
        r = self.client.post('/', {'username': email, 'password': MDP})
        self.assertEqual(r.status_code, 302, f'connexion impossible pour {email}')
        if deux_fa:
            session = self.client.session
            session['2fa_valide'] = True
            session.save()
        # Le jeton d'accès est régénéré à chaque connexion : on relit les comptes.
        self.patient.refresh_from_db()
        self.superadmin.refresh_from_db()
        self.medecin.refresh_from_db()
        self.infirmier.refresh_from_db()
        self.admin.refresh_from_db()
        if hasattr(self.client, 'raise_request_exception'):
            self.client.raise_request_exception = False
        pannes = []
        for nom, url in self._urls(self.patient.jeton_acces, self.superadmin.jeton_acces):
            reponse = self.client.get(url)
            if reponse.status_code >= 500:
                pannes.append(f'{nom} ({url}) -> HTTP {reponse.status_code}')
        return pannes

    def _aucune_panne(self, email, deux_fa=False):
        pannes = self._balayer(email, deux_fa=deux_fa)
        self.assertEqual(
            pannes, [],
            f'Pages en erreur serveur pour le profil {email} :\n  '
            + '\n  '.join(pannes))


class SmokePagesTest(BaseSmoke):
    def test_pages_patient(self):
        self._aucune_panne('patient@smoke.cm')

    def test_pages_infirmier(self):
        self._aucune_panne('infirmier@smoke.cm')

    def test_pages_medecin(self):
        self._aucune_panne('medecin@smoke.cm')

    def test_pages_administrateur(self):
        self._aucune_panne('admin@smoke.cm', deux_fa=True)

    def test_pages_superadmin(self):
        self._aucune_panne('super@smoke.cm', deux_fa=True)

    def test_pages_anonyme(self):
        """Visiteur non connecté : la page d'accueil et les pages publiques
        (mot de passe oublié, candidature) ne doivent pas planter."""
        if hasattr(self.client, 'raise_request_exception'):
            self.client.raise_request_exception = False
        pannes = []
        for nom, url in [('login', '/'),
                         ('mot_de_passe_oublie', reverse('mot_de_passe_oublie')),
                         ('soumettre_candidature', reverse('soumettre_candidature'))]:
            reponse = self.client.get(url)
            if reponse.status_code >= 500:
                pannes.append(f'{nom} ({url}) -> HTTP {reponse.status_code}')
        self.assertEqual(pannes, [], 'Pages publiques en erreur :\n  '
                                      + '\n  '.join(pannes))


class SmokeBoutonsTest(BaseSmoke):
    """Balayage des BOUTONS (POST) : c'est là que se produisent les « j'ai
    cliqué et j'ai eu une erreur 500 ». On vérifie qu'aucune action métier
    n'explose, quel que soit le profil. Le lien reste la cause racine
    (template → vue → service), mais ce test garantit la non-régression."""

    def _connecter(self, email, deux_fa=False):
        self.client.logout()
        r = self.client.post('/', {'username': email, 'password': MDP})
        self.assertEqual(r.status_code, 302, f'connexion impossible : {email}')
        if deux_fa:
            session = self.client.session
            session['2fa_valide'] = True
            session.save()
        if hasattr(self.client, 'raise_request_exception'):
            self.client.raise_request_exception = False

    def _collecter(self, actions):
        pannes = []
        for nom, url, donnees, fichiers in actions:
            # Le client de test n'a pas de paramètre « fichiers » : un fichier
            # se transmet en le plaçant dans le dictionnaire de données (la
            # requête est déjà en multipart). C'est indispensable pour
            # réellement exercer l'écriture du fichier sur le stockage.
            payload = dict(donnees or {})
            payload.update(fichiers or {})
            try:
                reponse = self.client.post(url, payload)
            except Exception as exc:  # noqa: BLE001 — on veut le message
                pannes.append(f'{nom} ({url}) -> EXCEPTION {type(exc).__name__}: {exc}')
                continue
            if reponse.status_code >= 500:
                pannes.append(f'{nom} ({url}) -> HTTP {reponse.status_code}')
        return pannes

    def _aucune_panne(self, pannes):
        self.assertEqual(pannes, [], 'Boutons en erreur serveur :\n  ' + '\n  '.join(pannes))

    # ──────────────────────────────────────────
    def test_boutons_infirmier(self):
        self._connecter('infirmier@smoke.cm')
        dut = DossierUrgenceTemporaire.objects.create(
            etablissement=self.etab, infirmier=self.infirmier,
            numeroDUT='DUT-SMOKE-02', informationsInitiales='Chute')
        pannes = self._collecter([
            ('creer_dut', reverse('creer_dut'),
             {'informationsInitiales': 'Patient inconscient'}, {'photo': photo()}),
            ('creer_patient', reverse('creer_patient'), {
                'nom': 'Nouveau', 'prenom': 'Patient', 'email': 'nouveau@smoke.cm',
                'telephone': '690000009', 'sexe': 'M', 'groupeSanguin': 'O+',
                'adresse': 'Rue test',
                'nomContactUrgencePrincipal': 'Mère',
                'telephoneContactUrgencePrincipal': '690000010',
                'lienContactUrgencePrincipal': 'Mère',
            }, {'photoProfil': photo('profil.jpg')}),
            ('rechercher_patient', reverse('rechercher_patient') + '?query=Patient', {}, {}),
            ('creer_triage', reverse('creer_triage', args=[dut.pk]),
             {'priorite': 'JAUNE', 'motifArrivee': 'Fièvre', 'observations': ''}, {}),
            ('ajouter_constante', reverse('ajouter_constante', args=[dut.pk]),
             {'frequenceCardiaque': 80, 'tensionArterielle': '12/8',
              'temperature': 39, 'saturationOxygene': 95,
              'frequenceRespiratoire': 20, 'poids': 70}, {}),
            ('rechercher_identite', reverse('rechercher_identite', args=[dut.pk]),
             {}, {'photo': photo()}),
            ('break_glass', reverse('break_glass', args=[dut.pk]), {}, {}),
            ('fiche_vitale', reverse('fiche_vitale', args=[dut.pk]), {}, {}),
        ])
        self._aucune_panne(pannes)

    def test_boutons_medecin(self):
        self._connecter('medecin@smoke.cm')
        # Le patient du jeu de données a déjà accordé l'accès (AccesDMP ACCORDE).
        recherche = RechercheIdentite.objects.create(
            dut=self.dut, etablissement=self.etab,
            patientCorrespondant=self.patient, confiance=92.5,
            statut=RechercheIdentite.Statut.CORRESPONDANCE_TROUVEE)
        consultation = Consultation.objects.create(
            dmp=self.dmp, etablissement=self.etab, medecin=self.medecin,
            motif='Suivi')
        pannes = self._collecter([
            ('creer_consultation', reverse('creer_consultation', args=[self.patient.pk]),
             {'motif': 'Fièvre', 'informationsCliniques': 'Toux',
              'observations': '', 'diagnostic': 'Grippe', 'conduiteATenir': 'Repos',
              'compteRendu': '', 'recommandations': ''}, {}),
            ('creer_ordonnance', reverse('creer_ordonnance', args=[consultation.pk]), {
                'instructions': 'Après repas',
                'lignes-TOTAL_FORMS': 1, 'lignes-INITIAL_FORMS': 0,
                'lignes-MIN_NUM_FORMS': 0, 'lignes-MAX_NUM_FORMS': 1000,
                'lignes-0-medicament': Medicament.objects.first().pk,
                'lignes-0-posologie': '1 cp', 'lignes-0-frequence': '2x/j',
                'lignes-0-duree': '3 j', 'lignes-0-quantite': '6',
            }, {}),
            ('confirmer_identite', reverse('confirmer_identite', args=[recherche.pk]),
             {'patient_id': self.patient.pk}, {}),
            ('renvoyer_notification_acces',
             reverse('renvoyer_notification_acces', args=[self.acces.pk]), {}, {}),
            ('fiche_vitale', reverse('fiche_vitale', args=[self.dut.pk]), {}, {}),
        ])
        self._aucune_panne(pannes)

    def test_boutons_patient(self):
        self._connecter('patient@smoke.cm')
        pannes = self._collecter([
            ('changer_mot_de_passe', reverse('changer_mot_de_passe'),
             {'old_password': MDP, 'new_password1': 'NouveauMdp123!',
              'new_password2': 'NouveauMdp123!'}, {}),
            ('acces_dmp_repondre', reverse('acces_dmp_repondre', args=[self.acces.pk]),
             {'decision': 'REFUSER'}, {}),
        ])
        self._aucune_panne(pannes)

    def test_boutons_administrateur(self):
        self._connecter('admin@smoke.cm', deux_fa=True)
        pannes = self._collecter([
            ('detail_candidature', reverse('detail_candidature', args=[self.candidature.pk]),
             {'decision': 'REFUSEE', 'motifRefus': 'Dossier incomplet'}, {}),
            ('abonnement_detail', reverse('abonnement_detail'),
             {'action': 'renouveler'}, {}),
            ('supprimer_candidature',
             reverse('supprimer_candidature', args=[self.candidature.pk]), {}, {}),
            ('liste_personnel', reverse('liste_personnel'), {}, {}),
            ('journal_audit', reverse('journal_audit'), {}, {}),
        ])
        self._aucune_panne(pannes)

    def test_boutons_superadmin(self):
        self._connecter('super@smoke.cm', deux_fa=True)
        abonnement = Abonnement.objects.get(etablissement=self.etab)
        formule = Formule.objects.first()
        pannes = self._collecter([
            ('creer_etablissement', reverse('super_etablissements'), {
                'action': 'creer_etablissement', 'nom': 'Clinique Test',
                'adresse': 'Rue test', 'telephone': '690000020',
                'email': 'clinique@test.cm', 'admin_email': 'admin2@test.cm',
                'admin_nom': 'Admin', 'admin_prenom': 'Deux',
            }, {}),
            ('modifier_etablissement', reverse('super_etablissements'), {
                'action': 'modifier_etablissement',
                'etablissement_id': self.etab.pk, 'nom': 'Hôpital Smoke',
            }, {}),
            ('suspendre_etablissement', reverse('super_etablissements'), {
                'action': 'suspendre_etablissement',
                'etablissement_id': self.etab.pk,
            }, {}),
            ('reactiver_etablissement', reverse('super_etablissements'), {
                'action': 'reactiver_etablissement',
                'etablissement_id': self.etab.pk,
            }, {}),
            ('creer_formule', reverse('super_abonnements'), {
                'action': 'creer_formule', 'nom': 'Premium test', 'prix': '50000',
                'dureeMois': 12, 'nbUtilisateursMax': 20, 'nbDMPMax': 200,
            }, {}),
            ('prolonger_abonnement', reverse('super_abonnements'), {
                'action': 'prolonger_abonnement',
                'abonnement_id': abonnement.pk, 'mois': 6,
            }, {}),
            ('suspendre_abonnement', reverse('super_abonnements'), {
                'action': 'suspendre_abonnement', 'abonnement_id': abonnement.pk,
            }, {}),
            ('activer_abonnement', reverse('super_abonnements'), {
                'action': 'activer_abonnement', 'abonnement_id': abonnement.pk,
            }, {}),
            ('changer_formule', reverse('super_abonnements'), {
                'action': 'changer_formule', 'abonnement_id': abonnement.pk,
                'formule_id': formule.pk,
            }, {}),
            ('super_rapports', reverse('super_rapports'), {}, {}),
        ])
        self._aucune_panne(pannes)


class StockageReadOnlyTest(BaseSmoke):
    """Vercel : le système de fichiers est en lecture seule (sauf /tmp). Si le
    stockage des médias n'est pas configuré (Supabase Storage), l'enregistrement
    d'une photo explose et le bouton renvoie une erreur 500. Aucun écran ne
    doit répondre 500 : on affiche un message exploitable."""

    STORAGES = {
        'default': {'BACKEND': 'core.tests_smoke.StockageIllisible'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }

    def setUp(self):
        super().setUp()
        if hasattr(self.client, 'raise_request_exception'):
            self.client.raise_request_exception = False

    def test_creer_dut_ne_plante_pas_si_stockage_illisible(self):
        self.client.post('/', {'username': 'infirmier@smoke.cm', 'password': MDP})
        with override_settings(STORAGES=self.STORAGES):
            reponse = self.client.post(
                reverse('creer_dut'),
                {'informationsInitiales': 'Patient inconscient',
                 'photo': photo()})
        self.assertLess(
            reponse.status_code, 500,
            '« Créer un DUT » renvoie une erreur serveur quand la photo ne peut '
            'pas être écrite (Vercel en lecture seule).')

    def test_creer_patient_ne_plante_pas_si_stockage_illisible(self):
        self.client.post('/', {'username': 'infirmier@smoke.cm', 'password': MDP})
        with override_settings(STORAGES=self.STORAGES):
            reponse = self.client.post(
                reverse('creer_patient'),
                {'nom': 'Nouvelle', 'prenom': 'Patiente', 'email': 'np@smoke.cm',
                 'telephone': '690000099', 'sexe': 'F', 'groupeSanguin': 'A+',
                 'nomContactUrgencePrincipal': 'Frère',
                 'telephoneContactUrgencePrincipal': '690000098',
                 'lienContactUrgencePrincipal': 'Frère',
                 'photoProfil': photo('profil.jpg')})
        self.assertLess(
            reponse.status_code, 500,
            '« Créer un patient » renvoie une erreur serveur quand la photo ne '
            'peut pas être écrite.')




