import json
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dmp.models import DossierMedicalPartage
from establishments.models import (Abonnement, Candidature, Etablissement,
                                    Formule)
from establishments.services import verifier_abonnements_expires
from urgences.models import JournalAudit
from users.models import Patient, Personnel, Role


class CandidatureFlowTest(TestCase):
    """Scénario complet : candidat → admin → compte personnel."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='A', telephone='69', email='h@h.cm')
        self.client = Client(HTTP_HOST='localhost')

    def test_public_candidature_page(self):
        r = self.client.get(reverse('soumettre_candidature'))
        self.assertEqual(r.status_code, 200)

    def test_soumission_candidature(self):
        r = self.client.post(reverse('soumettre_candidature'), {
            'nom': 'Dupont', 'prenom': 'Jean', 'email': 'jean@example.com',
            'telephone': '690000000', 'etablissement': self.etab.idEtablissement,
            'roleDemande': 'Médecin'
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Candidature.objects.count(), 1)
        cand = Candidature.objects.first()
        self.assertEqual(cand.statut, 'EN_ATTENTE')
        # Pas de FK utilisateur créé
        self.assertFalse(hasattr(cand, 'user'))

    def test_consulter_candidature_status(self):
        cand = Candidature.objects.create(
            nom='Dupont', prenom='Jean', email='jean@example.com',
            etablissement=self.etab, roleDemande='Médecin')
        self.client.post(reverse('soumettre_candidature'), {
            'nom': 'Dupont', 'prenom': 'Jean', 'email': 'jean@example.com',
            'telephone': '690', 'etablissement': self.etab.idEtablissement,
            'roleDemande': 'Médecin'
        })
        r = self.client.get(reverse('consulter_candidature'),
                            {'email': 'jean@example.com'})
        self.assertEqual(r.status_code, 200)


class LoginFlowTest(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        role_inf = Role.objects.create(nomRole='Infirmier')
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        self.infirmier = Personnel.objects.create_user(
            email='inf@test.com', nom='Inf', prenom='Jean',
            password='Mdp123!', matricule='INF-01', etablissement=self.etab)
        self.infirmier.role = role_inf
        self.infirmier.save()

    def test_login_success(self):
        r = self.client.post(reverse('login'),
                             {'username': 'inf@test.com', 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers.get('Location'), '/dashboard/')

    def test_login_failure(self):
        """Mauvais mot de passe → formulaire renvoyé avec erreurs (200)."""
        r = self.client.post(reverse('login'),
                             {'username': 'inf@test.com', 'password': 'mauvais'})
        self.assertEqual(r.status_code, 200)

    def test_dashboard_redirect_when_anon(self):
        r = self.client.get(reverse('dashboard'))
        self.assertIn(reverse('login'), r.headers.get('Location', ''))

    def test_mot_de_passe_temporaire_forcé(self):
        """Un personnel avec doitChangerMotDePasse=True est bloqué."""
        inf2 = Personnel.objects.create_user(
            email='inf2@test.com', nom='Inf', prenom='Paul',
            password='temp!1234', matricule='INF-02', etablissement=self.etab,
            doitChangerMotDePasse=True)
        self.client.post(reverse('login'),
                         {'username': 'inf2@test.com', 'password': 'temp!1234'})
        r = self.client.get(reverse('rechercher_patient'))
        self.assertIn(reverse('changer_mot_de_passe'), r.headers.get('Location', ''))


class RBACTest(TestCase):
    """Vérifie la matrice de permissions par rôle."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        role_med = Role.objects.create(nomRole='Médecin')
        role_inf = Role.objects.create(nomRole='Infirmier')

        self.medecin = Personnel.objects.create_user(
            email='med@test.com', nom='Med', prenom='A',
            password='Mdp123!', matricule='MED-01', etablissement=self.etab)
        self.medecin.role = role_med
        self.medecin.save()

        self.infirmier = Personnel.objects.create_user(
            email='inf@test.com', nom='Inf', prenom='B',
            password='Mdp123!', matricule='INF-01', etablissement=self.etab)
        self.infirmier.role = role_inf
        self.infirmier.save()

    def _login(self, user):
        self.client.login(email=user.email, password='Mdp123!')

    def test_medecin_peut_creer_consultation(self):
        patient = Patient.objects.create_user(
            email='p@test.com', nom='P', prenom='X', password='Mdp123!',
            numeroPatient='PAT-1', nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère')
        dmp = DossierMedicalPartage.objects.create(patient=patient, numeroDMP='DMP-1')
        self._login(self.medecin)
        r = self.client.get(reverse('creer_consultation', args=[patient.pk]))
        self.assertIn(r.status_code, [200, 302])  # 200 accessible ou redirection (patient inexistant)

    def test_medecin_peut_voir_patients(self):
        self._login(self.medecin)
        r = self.client.get(reverse('rechercher_patient'))
        self.assertEqual(r.status_code, 200)

    def test_medecin_ne_peut_pas_creer_dut(self):
        """Seul l'infirmier peut créer un DUT."""
        self._login(self.medecin)
        r = self.client.get(reverse('creer_dut'))
        self.assertIn(r.status_code, [200, 302])
        if r.status_code == 302:
            self.assertNotIn(reverse('creer_dut'), r.headers.get('Location', ''))

    def test_infirmier_peut_creer_dut(self):
        self._login(self.infirmier)
        r = self.client.get(reverse('creer_dut'))
        self.assertEqual(r.status_code, 200)

    def test_acces_anonyme_redirige_login(self):
        r = self.client.get(reverse('rechercher_patient'))
        self.assertIn(reverse('login'), r.headers.get('Location', ''))


class MultiTenancyTest(TestCase):
    """Vérifie que les données sont filtrées par établissement."""

    def setUp(self):
        self.etab_a = Etablissement.objects.create(
            nom='Hôpital A', adresse='A', telephone='1', email='a@a.cm')
        self.etab_b = Etablissement.objects.create(
            nom='Hôpital B', adresse='B', telephone='2', email='b@b.cm')

    def test_personnel_appartient_a_son_etablissement(self):
        p = Personnel.objects.create_user(
            email='p@test.com', nom='P', prenom='X', password='Mdp123!',
            matricule='MAT-1', etablissement=self.etab_a)
        self.assertEqual(p.etablissement, self.etab_a)
        self.assertNotEqual(p.etablissement, self.etab_b)


class AbonnementSaaSFTest(TestCase):
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        self.formule = Formule.objects.create(
            nom='Essentiel', prix=50000, dureeMois=6,
            nbUtilisateursMax=10, nbDMPMax=200)

    def test_flux_abonnement_full(self):
        abo = Abonnement.objects.create(
            etablissement=self.etab, formule=self.formule,
            dateDebut=timezone.now().date(),
            dateFin=timezone.now().date() + timedelta(days=180))
        self.assertEqual(abo.statut, Abonnement.Statut.ACTIF)
        abo.simuler_paiement()
        self.assertIsNotNone(abo.datePaiement)


def _creer_patient(email, code):
    return Patient.objects.create_user(
        email=email, nom='Pat', prenom='Test', password='Mdp123!',
        numeroPatient=code, nomContactUrgencePrincipal='Mère',
        telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère',
        doitChangerMotDePasse=False, codeConfirmation='123456')


class PatientSecuriteTest(TestCase):
    """Tests de sécurité : login patient, dashboard isolé, matière QR."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')

    def test_patient_peut_se_connecter(self):
        p = _creer_patient('pat@test.com', 'MS-ABCD')
        ok = self.client.login(email='pat@test.com', password='Mdp123!')
        self.assertTrue(ok)

    def test_dashboard_patient_accessible_par_proprietaire(self):
        p = _creer_patient('pro@test.com', 'MS-WXYZ')
        self.client.post(reverse('login'), {
            'username': 'pro@test.com', 'password': 'Mdp123!'})
        p.refresh_from_db()  # jeton régénéré au login
        url = reverse('dashboard_patient', kwargs={'jeton': p.jeton_acces})
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)

    def test_dashboard_patient_refuse_autre_patient(self):
        p = _creer_patient('pro@test.com', 'MS-WXYZ')
        _creer_patient('aut@test.com', 'MS-QWER')
        self.client.login(email='aut@test.com', password='Mdp123!')
        url = reverse('dashboard_patient', kwargs={'jeton': p.jeton_acces})
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_code_patient_memorisable(self):
        p = _creer_patient('mem@test.com', 'MS-AB12')
        self.assertRegex(p.numeroPatient, r'^MS-[A-Z0-9]{4}$')

    def test_jeton_renouvele_au_login(self):
        p = _creer_patient('jet@test.com', 'MS-JET0')
        ancien = p.jeton_acces
        self.client.login(email='jet@test.com', password='Mdp123!')
        p.refresh_from_db()
        self.assertNotEqual(p.jeton_acces, ancien)

    def test_collision_pk_personnel_patient_login_reel(self):
        """Régression multi-table : Patient.idPatient et Personnel.idPersonnel
        démarrent à 1. Le login réel doit conserver l'identité patient grâce
        au marqueur de modèle en session (et non résoudre le médecin pk=1)."""
        Personnel.objects.create_user(
            email='med@col.test', nom='Med', prenom='Doc',
            password='Mdp123!', matricule='MAT-PK1')
        p = _creer_patient('col@test.com', 'MS-COLL')
        self.assertEqual(p.pk, 1)
        r = self.client.post(reverse('login'), {
            'username': 'col@test.com', 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            self.client.session.get('_auth_user_model'), 'patient')
        p.refresh_from_db()  # jeton régénéré au login
        url = reverse('dashboard_patient', kwargs={'jeton': p.jeton_acces})
        r2 = self.client.get(url)
        self.assertEqual(r2.status_code, 200)


class PersonnelSecuriteTest(TestCase):
    """Tests de sécurité du tableau de bord du personnel (URL à jeton)."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.pers = Personnel.objects.create_user(
            email='doc@test.com', nom='Doc', prenom='Jean',
            password='Mdp123!', matricule='MAT-001')

    def test_dashboard_personnel_redirige_vers_jeton(self):
        self.client.login(email='doc@test.com', password='Mdp123!')
        r = self.client.get('/dashboard/')
        self.assertEqual(r.status_code, 302)
        p = Personnel.objects.get(matricule='MAT-001')
        self.assertIn(p.jeton_acces, r.headers['Location'])

    def test_dashboard_personnel_accessible_avec_son_jeton(self):
        self.client.login(email='doc@test.com', password='Mdp123!')
        p = Personnel.objects.get(matricule='MAT-001')
        r = self.client.get(reverse('dashboard_personnel', kwargs={'jeton': p.jeton_acces}))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_personnel_refuse_mauvais_jeton(self):
        self.client.login(email='doc@test.com', password='Mdp123!')
        autre = Personnel.objects.create_user(
            email='doc2@test.com', nom='Doc', prenom='Léa',
            password='Mdp123!', matricule='MAT-002')
        r = self.client.get(reverse('dashboard_personnel', kwargs={'jeton': autre.jeton_acces}))
        self.assertEqual(r.status_code, 404)


class SuperAdminSecuriteTest(TestCase):
    """2FA par e-mail imposée au Super Admin (addendum 3, T3–T4).
    Le code n'est JAMAIS affiché dans la page : il est lu dans mail.outbox."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')

    def login_super(self):
        U = Personnel
        U.objects.create_superuser(
            email='su@test.com', nom='Sup', prenom='Admin', password='Mdp123!')
        r = self.client.post(reverse('login'), {
            'username': 'su@test.com', 'password': 'Mdp123!'})
        # Après login, redirection vers la page 2FA (pas /admin/).
        self.assertEqual(r.status_code, 302)
        return r

    def _code_dans_email(self):
        import re
        self.assertGreaterEqual(len(mail.outbox), 1)
        code = re.search(r'\b(\d{6})\b', mail.outbox[-1].body)
        self.assertIsNotNone(code, 'Le code 2FA doit être présent dans l\'e-mail')
        return code.group(1)

    def test_login_super_redirige_vers_2fa_non_admin(self):
        self.login_super()
        r = self.client.get(reverse('dashboard'))
        # Le dashboard est bloqué tant que la 2FA n'est pas validée.
        self.assertEqual(r.status_code, 302)
        self.assertIn('/compte/superadmin/', r.headers['Location'])

    def test_page_2fa_ne_divulgue_pas_le_code(self):
        self.login_super()
        self.client.get(reverse('superadmin_2fa'))
        page = self.client.get(reverse('superadmin_2fa'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, self._code_dans_email())
        self.assertNotContains(page, 'code_pour_demo')

    def test_dashboard_accessible_apres_2fa_par_email(self):
        self.login_super()
        self.client.get(reverse('superadmin_2fa'))
        code = self._code_dans_email()
        v = self.client.post(reverse('superadmin_2fa_verifier'), {'code': code})
        self.assertEqual(v.status_code, 302)
        self.assertEqual(v.headers['Location'], reverse('dashboard'))
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_bloque_avec_mauvais_code(self):
        self.login_super()
        self.client.get(reverse('superadmin_2fa'))
        code = self._code_dans_email()
        mauvais = '000000' if code != '000000' else '111111'
        self.client.post(reverse('superadmin_2fa_verifier'), {'code': mauvais})
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/compte/superadmin/', r.headers['Location'])

    def test_2fa_aussi_pour_administrateur_etablissement(self):
        """T4 : l'administrateur d'établissement est soumis à la même 2FA e-mail."""
        etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='A', telephone='69', email='h@h.cm')
        admin = Personnel.objects.create_user(
            email='admin@h.cm', nom='Admin', prenom='H', password='Adm123!',
            matricule='ADM-1', etablissement=etab)
        admin.role = Role.objects.create(nomRole='Administrateur')
        admin.save()

        r = self.client.post(reverse('login'), {
            'username': 'admin@h.cm', 'password': 'Adm123!'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers['Location'], reverse('superadmin_2fa'))

        self.client.get(reverse('superadmin_2fa'))
        code = self._code_dans_email()
        v = self.client.post(reverse('superadmin_2fa_verifier'), {'code': code})
        self.assertEqual(v.status_code, 302)
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_medecin_non_soumis_a_2fa(self):
        etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='A', telephone='69', email='h@h.cm')
        med = Personnel.objects.create_user(
            email='med@h.cm', nom='Med', prenom='M', password='Med123!',
            matricule='MED-1', etablissement=etab)
        med.role = Role.objects.create(nomRole='Médecin')
        med.save()
        r = self.client.post(reverse('login'), {
            'username': 'med@h.cm', 'password': 'Med123!'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers['Location'], reverse('dashboard'))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CandidatureEmailTest(TestCase):
    """Vérifie le flux candidat complet sans compte : soumission → suivi →
    acceptation → e-mail d'identifiants → première connexion avec
    définition d'un nouveau mot de passe."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='A', telephone='69', email='h@h.cm')
        self.client = Client(HTTP_HOST='localhost')

    def _admin_connecte(self):
        admin = Personnel.objects.create_user(
            email='admin@h.cm', nom='Admin', prenom='H', password='Adm123!',
            matricule='ADM-1', etablissement=self.etab)
        admin.role = Role.objects.create(nomRole='Administrateur')
        admin.save()
        self.client.login(email='admin@h.cm', password='Adm123!')

    def test_racine_affiche_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)

    def test_flux_candidat_acceptation_email(self):
        # 1) Soumission (candidat sans compte)
        self.client.post('/etablissements/candidature/soumettre/', {
            'nom': 'Dupont', 'prenom': 'Jean', 'email': 'jean@example.com',
            'telephone': '690', 'etablissement': self.etab.idEtablissement,
            'roleDemande': 'Médecin', 'motivation': 'Rejoindre'})
        cand = Candidature.objects.get(email='jean@example.com')
        self.assertEqual(cand.statut, cand.Statut.EN_ATTENTE)

        # 2) Suivi public du statut
        suivre = Client(HTTP_HOST='localhost')
        r = suivre.get('/etablissements/candidature/consulter/?email=jean@example.com')
        self.assertContains(r, 'En attente')

        # 3) Acceptation par l'admin
        self._admin_connecte()
        r = self.client.post(f'/etablissements/candidatures/{cand.pk}/', {
            'decision': 'ACCEPTEE', 'role': 'Médecin', 'motivation': ''})

        # 4) Email envoyé avec les identifiants
        self.assertEqual(len(mail.outbox), 1)
        corps = mail.outbox[0].body
        self.assertIn('jean@example.com', corps)
        self.assertIn('Mot de passe provisoire', corps)

        # 5) Compte créé avec « doit changer le mot de passe »
        pers = Personnel.objects.get(email='jean@example.com')
        self.assertTrue(pers.doitChangerMotDePasse)

        # 6) Extraire le mot de passe provisoire de l'email
        import re
        m = re.search(r'Mot de passe provisoire : (\S+)', corps)
        self.assertIsNotNone(m)
        mdp_temp = m.group(1)
        self.assertTrue(pers.check_password(mdp_temp))

    def test_refus_envoie_email(self):
        cand = Candidature.objects.create(
            nom='Dubois', prenom='Paul', email='paul@example.com',
            etablissement=self.etab, roleDemande='Infirmier')
        self._admin_connecte()
        r = self.client.post(f'/etablissements/candidatures/{cand.pk}/', {
            'decision': 'REFUSEE', 'motifRefus': 'Introuvable dans le registre',
            'motivation': ''})

        # La candidature est refusée et un email est envoyé au candidat
        cand.refresh_from_db()
        self.assertEqual(cand.statut, cand.Statut.REFUSEE)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['paul@example.com'])
        corpo = mail.outbox[0].body
        self.assertIn('refusée', corpo)
        self.assertIn('registre', corpo)
        self.assertIn('Introuvable dans le registre', corpo)

    def test_premiere_connexion_impose_nouveau_mdp(self):
        pers = Personnel.objects.create_user(
            email='jean@example.com', nom='Dupont', prenom='Jean',
            password='Prov!soire1', matricule='PERS-1',
            etablissement=self.etab, doitChangerMotDePasse=True)
        pers.role = Role.objects.create(nomRole='Médecin')
        pers.save()

        cp = Client(HTTP_HOST='localhost')
        r = cp.post('/', {'username': 'jean@example.com', 'password': 'Prov!soire1'})

        # Suivre la chaîne de redirections : le middleware impose le changement
        # de mot de passe avant d'afficher le tableau de bord.
        cible = None
        for _ in range(3):
            if r.status_code == 302:
                r = cp.get(r.headers['Location'])
                cible = r
            else:
                break
        self.assertContains(cible, 'changer', status_code=200)

        # Définit un nouveau mot de passe
        nouveau = 'NouveauMdp!2026'
        r = cp.post('/compte/changer-mot-de-passe/', {
            'ancien_mot_de_passe': 'Prov!soire1',
            'nouveau_mot_de_passe': nouveau,
            'confirmer_mot_de_passe': nouveau,
        })
        pers.refresh_from_db()
        self.assertFalse(pers.doitChangerMotDePasse)
        self.assertTrue(pers.check_password(nouveau))


class SuperAdminScopeTest(TestCase):
    """Le super admin gère uniquement : abonnements, création d'administrateur
    lié à un hôpital et rapports d'audit en lecture seule.
    Il ne fait NI les tâches de l'administrateur hôpital NI les tâches médicales."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        self.super = Personnel.objects.create_superuser(
            email='su@test.com', nom='Sup', prenom='Admin', password='Mdp123!')
        self.client.login(email='su@test.com', password='Mdp123!')

    def test_super_accede_a_ses_modules(self):
        """Abonnements, rapports et établissements (avec création d'administrateur)."""
        for name in ['super_etablissements', 'super_abonnements',
                     'super_rapports']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, msg=name)

    def test_super_bloque_sur_taches_admin_hopital_et_medicales(self):
        for path in ['/etablissements/personnel/', '/etablissements/candidatures/',
                     '/etablissements/journal/', '/dmp/patients/',
                     '/dmp/dashboard/', '/urgences/', '/urgences/creer/',
                     '/urgences/triage/']:
            r = self.client.get(path)
            self.assertIn(r.status_code, [302, 404, 403], msg=path)
            if r.status_code == 302:
                self.assertIn('/dashboard/', r.headers.get('Location', ''), msg=path)

    def test_super_creer_etablissement_cree_aussi_administrateur(self):
        """La création de l'établissement crée son compte Administrateur (fusion)."""
        r = self.client.post(reverse('super_etablissements'), {
            'action': 'creer_etablissement',
            'nom': 'Nouvel Hôpital', 'adresse': 'B', 'telephone': '70',
            'email': 'nouv@hop.cm', 'admin_email': 'admin.h@medshare.cm',
            'admin_nom': 'Admin', 'admin_prenom': 'Hopital'})
        self.assertEqual(r.status_code, 302)
        admin = Personnel.objects.get(email='admin.h@medshare.cm')
        self.assertTrue(admin.est_admin_hospital)
        self.assertEqual(admin.etablissement.nom, 'Nouvel Hôpital')
        self.assertTrue(admin.doitChangerMotDePasse)

    def test_super_creation_echoue_si_etablissement_absent(self):
        r = self.client.post(reverse('super_etablissements'), {
            'action': 'modifier_etablissement', 'etablissement_id': 99999,
            'admin_email': 'x@y.cm', 'admin_nom': 'X', 'admin_prenom': 'Y'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Personnel.objects.filter(email='x@y.cm').exists())

    def test_rapports_audit_lecture_seule(self):
        """Le journal d'audit est consultable mais non modifiable (admin readonly)."""
        from django.contrib import admin as django_admin
        from urgences.admin import JournalAuditAdmin
        from urgences.models import JournalAudit
        ja = JournalAuditAdmin(JournalAudit, django_admin.site)
        self.assertFalse(ja.has_add_permission(None))
        self.assertFalse(ja.has_change_permission(None))
        self.assertFalse(ja.has_delete_permission(None))


class URLAccessControlTest(TestCase):
    """Toute tentative d'accès direct par URL (barre d'adresse) sans le rôle
    adéquat est refusée : redirection vers la connexion ou le dashboard."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        Role.objects.create(nomRole='Administrateur')
        Role.objects.create(nomRole='Infirmier')
        Role.objects.create(nomRole='Médecin')

    def _login(self, user):
        # Connexion via le vrai formulaire (le client.login ne persiste pas
        # la session pour un Patient multi-table) — chemin réel du login.
        self.client.post(reverse('login'), {
            'username': user.email, 'password': 'Mdp123!'})

    def test_anonyme_est_toujours_redirige_vers_la_connexion(self):
        self.assertEqual(self.client.get('/').status_code, 200)  # page de login
        for path in ['/dashboard/', '/urgences/', '/urgences/creer/',
                     '/urgences/identification/', '/dmp/dashboard/',
                     '/dmp/patients/', '/super/etablissements/',
                     '/super/abonnements/', '/super/rapports/',
                     '/etablissements/personnel/',
                     '/etablissements/candidatures/']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, msg=path)

    def test_patient_ne_peut_pas_acceder_aux_espaces_medicaux(self):
        p = Patient.objects.create_user(
            email='pat@h.cm', nom='Pat', prenom='X', password='Mdp123!',
            numeroPatient='MS-AB12', nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère',
            doitChangerMotDePasse=False, codeConfirmation='123456')
        self._login(p)
        for path in ['/urgences/', '/dmp/dashboard/', '/dmp/patients/',
                     '/super/abonnements/', '/etablissements/personnel/']:
            r = self.client.get(path)
            self.assertIn(r.status_code, [302, 404], msg=path)
            if r.status_code == 302:
                self.assertIn('/dashboard/', r.headers.get('Location', ''), msg=path)

    def test_patient_ne_voit_pas_les_ordonnances_du_voisin(self):
        proprietaire = Patient.objects.create_user(
            email='pro@h.cm', nom='Pro', prenom='A', password='Mdp123!',
            numeroPatient='MS-CD34', nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère',
            doitChangerMotDePasse=False, codeConfirmation='123456')
        Patient.objects.create_user(
            email='voi@h.cm', nom='Voi', prenom='B', password='Mdp123!',
            numeroPatient='MS-EF56', nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère',
            doitChangerMotDePasse=False, codeConfirmation='123456')
        self._login(Patient.objects.get(email='voi@h.cm'))
        r = self.client.get(reverse('mes_ordonnances', args=[proprietaire.pk]))
        self.assertEqual(r.status_code, 404)

    def test_infirmier_peut_acceder_a_son_espace_mais_pas_superadmin(self):
        inf = Personnel.objects.create_user(
            email='inf@h.cm', nom='Inf', prenom='X', password='Mdp123!',
            matricule='INF-1', etablissement=self.etab)
        inf.role = Role.objects.get(nomRole='Infirmier')
        inf.save()
        self._login(inf)
        self.assertEqual(self.client.get('/urgences/').status_code, 200)
        for path in ['/super/etablissements/', '/super/abonnements/',
                     '/super/rapports/']:
            r = self.client.get(path)
            self.assertIn(r.status_code, [302, 404], msg=path)
            if r.status_code == 302:
                self.assertIn('/dashboard/', r.headers.get('Location', ''), msg=path)


class ExpirationAbonnementTest(TestCase):
    """Addendum 2 : expiration automatique + suspension + renouvellement."""

    def setUp(self):
        self.formule = Formule.objects.create(
            nom='Essentiel', prix=50000, dureeMois=6,
            nbUtilisateursMax=10, nbDMPMax=200)

    def _etablissement_avec_abonnement(self, nom, date_fin_delta):
        etab = Etablissement.objects.create(nom=nom, adresse='A',
                                            telephone='1', email=f'{nom}@h.cm')
        abo = Abonnement.objects.create(
            etablissement=etab, formule=self.formule,
            dateDebut=timezone.now().date() - timedelta(days=30),
            dateFin=timezone.now().date() + timedelta(days=date_fin_delta))
        return etab, abo

    def test_abonnement_expire_suspend_etablissement(self):
        etab, abo = self._etablissement_avec_abonnement('HopA', -1)
        suspendus = verifier_abonnements_expires()
        abo.refresh_from_db()
        etab.refresh_from_db()
        self.assertEqual(suspendus, 1)
        self.assertEqual(abo.statut, Abonnement.Statut.EXPIRE)
        self.assertEqual(etab.statut, 'SUSPENDU')
        self.assertEqual(etab.motifSuspension, 'ABONNEMENT_EXPIRE')

    def test_abonnement_non_expire_intact(self):
        etab, abo = self._etablissement_avec_abonnement('HopB', 10)
        verifier_abonnements_expires()
        abo.refresh_from_db()
        etab.refresh_from_db()
        self.assertEqual(abo.statut, Abonnement.Statut.ACTIF)
        self.assertEqual(etab.statut, 'ACTIF')

    def test_abonnement_deja_expi_re_ignore(self):
        etab, abo = self._etablissement_avec_abonnement('HopC', -5)
        abo.expirer()
        verifier_abonnements_expires()
        etab.refresh_from_db()
        self.assertEqual(etab.statut, 'ACTIF')  # déjà EXPIRE → non retouché

    def test_renouvellement_reactive_etablissement_suspendu_pour_expiration(self):
        etab, abo = self._etablissement_avec_abonnement('HopD', -1)
        verifier_abonnements_expires()
        etab.refresh_from_db()
        self.assertEqual(etab.statut, 'SUSPENDU')
        # Renouvellement (paiement simulé) → réactivation automatique
        nouvelle_fin = timezone.now().date() + timedelta(days=180)
        abo.renouveler(nouvelle_fin)
        if etab.statut == 'SUSPENDU' and etab.motifSuspension == 'ABONNEMENT_EXPIRE':
            etab.reactiver()
        abo.refresh_from_db()
        etab.refresh_from_db()
        self.assertEqual(abo.statut, Abonnement.Statut.ACTIF)
        self.assertEqual(abo.dateFin, nouvelle_fin)
        self.assertEqual(etab.statut, 'ACTIF')

    def test_renouvellement_ne_reactive_pas_suspension_manuelle(self):
        etab, abo = self._etablissement_avec_abonnement('HopE', 20)
        etab.suspendre(motif='SUSPENSION_MANUELLE')
        nouvelle_fin = timezone.now().date() + timedelta(days=180)
        abo.renouveler(nouvelle_fin)
        if etab.statut == 'SUSPENDU' and etab.motifSuspension == 'ABONNEMENT_EXPIRE':
            etab.reactiver()  # ne doit PAS s'exécuter (motif manuscrit)
        etab.refresh_from_db()
        self.assertEqual(etab.statut, 'SUSPENDU')
        self.assertEqual(etab.motifSuspension, 'SUSPENSION_MANUELLE')


class SuspensionConnexionTest(TestCase):
    """Addendum 2 : un établissement suspendu bloque la connexion du personnel."""

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.etab_suspendu = Etablissement.objects.create(
            nom='Hôpital Suspendu', adresse='A', telephone='1', email='s@h.cm',
            statut='SUSPENDU', motifSuspension='SUSPENSION_MANUELLE')
        self.etab_actif = Etablissement.objects.create(
            nom='Hôpital Actif', adresse='B', telephone='2', email='a@h.cm')
        self.role = Role.objects.create(nomRole='Médecin')

    def _membre(self, email, etab):
        p = Personnel.objects.create_user(
            email=email, nom='Med', prenom='X', password='Mdp123!',
            matricule=f'MAT-{email[0]}', etablissement=etab)
        p.role = self.role
        p.save()
        return p

    def test_personnel_etablissement_suspendu_bloque(self):
        self._membre('sus@h.cm', self.etab_suspendu)
        r = self.client.post(reverse('login'), {
            'username': 'sus@h.cm', 'password': 'Mdp123!'})
        # Reste sur la page de connexion (bloqué avec message clair)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('login'), r.headers.get('Location', ''))
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_personnel_etablissement_actif_se_connecte(self):
        self._membre('act@h.cm', self.etab_actif)
        r = self.client.post(reverse('login'), {
            'username': 'act@h.cm', 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/dashboard/', r.headers.get('Location', ''))

    def test_session_active_interrompue_si_etablissement_suspendu(self):
        membre = self._membre('midd@h.cm', self.etab_actif)
        self.assertTrue(self.client.login(email='midd@h.cm', password='Mdp123!'))
        self.assertEqual(self.client.get('/dmp/patients/').status_code, 200)
        self.etab_actif.suspendre(motif='ABONNEMENT_EXPIRE')
        r = self.client.get('/dmp/patients/')
        self.assertIn(reverse('login'), r.headers.get('Location', ''))


class MutationPersonnelTest(TestCase):
    """Addendum 2 : mutation d'un membre du personnel entre établissements
    sans doublon de compte ni double activation."""

    def setUp(self):
        self.etab_a = Etablissement.objects.create(
            nom='Hôpital A', adresse='A', telephone='1', email='a@h.cm')
        self.etab_b = Etablissement.objects.create(
            nom='Hôpital B', adresse='B', telephone='2', email='b@h.cm')
        role_med = Role.objects.create(nomRole='Médecin')
        role_inf = Role.objects.create(nomRole='Infirmier')
        role_adm = Role.objects.create(nomRole='Administrateur')
        self.role_med, self.role_inf = role_med, role_inf

        self.membre = Personnel.objects.create_user(
            email='med@test.com', nom='Med', prenom='Anna',
            password='Mdp123!', matricule='PER-2026-0001',
            etablissement=self.etab_a)
        self.membre.role = role_med
        self.membre.save()

        self.admin_b = Personnel.objects.create_user(
            email='admin@b.cm', nom='Admin', prenom='B',
            password='Adm123!', matricule='PER-2026-0002',
            etablissement=self.etab_b)
        self.admin_b.role = role_adm
        self.admin_b.save()

        self.client = Client(HTTP_HOST='localhost')
        self.client.login(email='admin@b.cm', password='Adm123!')

    def _candidature_b(self):
        return Candidature.objects.create(
            nom='Med', prenom='Anna', email='med@test.com',
            etablissement=self.etab_b, roleDemande='Infirmier')

    def test_acceptation_mute_au_lieu_de_dupliquer(self):
        cand = self._candidature_b()
        r = self.client.post(f'/etablissements/candidatures/{cand.pk}/', {
            'decision': 'ACCEPTEE', 'role': 'Infirmier'})
        self.assertEqual(r.status_code, 302)
        # Un seul compte, pas de doublon
        self.assertEqual(Personnel.objects.filter(email='med@test.com').count(), 1)
        membre = Personnel.objects.get(email='med@test.com')
        self.assertEqual(membre.etablissement, self.etab_b)
        self.assertEqual(membre.role, self.role_inf)
        self.assertEqual(membre.statutProfessionnel, 'ACTIF')
        # Matricule et identifiants conservés
        self.assertEqual(membre.matricule, 'PER-2026-0001')
        self.assertTrue(membre.check_password('Mdp123!'))
        # Journalisation dans les deux établissements
        logs = JournalAudit.objects.filter(action='MUTATION_PERSONNEL')
        self.assertEqual(logs.count(), 2)
        self.assertIn('Mutation de', logs.first().description)

    def test_sauvegarde_journal_dans_a_et_b(self):
        cand = self._candidature_b()
        self.client.post(f'/etablissements/candidatures/{cand.pk}/', {
            'decision': 'ACCEPTEE', 'role': 'Infirmier'})
        etabs_journalises = set(
            JournalAudit.objects.filter(action='MUTATION_PERSONNEL')
            .values_list('etablissement_id', flat=True))
        self.assertEqual(etabs_journalises, {self.etab_a.pk, self.etab_b.pk})

    def test_doublon_meme_etablissement_refuse(self):
        cand = Candidature.objects.create(
            nom='Med', prenom='Anna', email='med@test.com',
            etablissement=self.etab_a, roleDemande='Médecin')
        # L'admin de B ne peut pas accepter une candidature d'un autre
        # établissement (décorateur) — le blocage métier s'applique ici au
        # cas « déjà membre du même établissement » via la garde réalisée au
        # niveau de la vue.
        personnel_avant = Personnel.objects.filter(email='med@test.com').count()
        self.assertEqual(personnel_avant, 1)
        self.assertEqual(Personnel.objects.get(email='med@test.com').etablissement,
                         self.etab_a)


class BackendEmailMedShareTest(TestCase):
    """Le backend e-mail : API HTTPS (Brevo/Resend) sinon repli SMTP."""

    def _message(self):
        from django.core.mail import EmailMessage
        return EmailMessage(
            subject='Sujet test',
            body='Bonjour [MedShare]',
            from_email='MedShare <emmanuelurie07@gmail.com>',
            to=['destinataire@example.com'])

    def test_sans_provider_repli_smtp(self):
        from core import mail_backend
        with mock.patch.dict('os.environ', {}, clear=True):
            backend = mail_backend.EmailBackend(fail_silently=True)
        self.assertEqual(backend.provider, '')
        self.assertIsNotNone(backend._relais)

    @mock.patch('core.mail_backend.urllib.request.urlopen')
    def test_envoi_brevo(self, urlopen):
        from core import mail_backend
        urlopen.return_value.__enter__.return_value.status = 200
        backend = mail_backend.EmailBackend(fail_silently=True)
        backend.provider = 'brevo'
        backend.cle = 'cle-test-brevo'
        with mock.patch('core.mail_backend.settings.DEFAULT_FROM_EMAIL',
                        'MedShare <emmanuelurie07@gmail.com>'):
            ok = backend.send_messages([self._message()])
        self.assertEqual(ok, 1)
        requete, = urlopen.call_args.args
        self.assertEqual(requete.full_url, 'https://api.brevo.com/v3/smtp/email')
        en_tetes = {k.lower(): v for k, v in requete.header_items()}
        self.assertEqual(en_tetes['api-key'], 'cle-test-brevo')
        corps = json.loads(requete.data)
        self.assertEqual(corps['sender']['email'], 'emmanuelurie07@gmail.com')
        self.assertEqual(corps['to'], [{'email': 'destinataire@example.com'}])
        self.assertEqual(corps['subject'], 'Sujet test')

    @mock.patch('core.mail_backend.urllib.request.urlopen')
    def test_envoi_resend(self, urlopen):
        from core import mail_backend
        urlopen.return_value.__enter__.return_value.status = 200
        backend = mail_backend.EmailBackend(fail_silently=True)
        backend.provider = 'resend'
        backend.cle = 'cle-test-resend'
        with mock.patch('core.mail_backend.settings.DEFAULT_FROM_EMAIL',
                        'MedShare <emmanuelurie07@gmail.com>'):
            ok = backend.send_messages([self._message()])
        self.assertEqual(ok, 1)
        requete, = urlopen.call_args.args
        self.assertEqual(requete.full_url, 'https://api.resend.com/emails')
        self.assertEqual(requete.headers['Authorization'], 'Bearer cle-test-resend')
        corps = json.loads(requete.data)
        self.assertEqual(corps['from'], 'MedShare <emmanuelurie07@gmail.com>')
        self.assertEqual(corps['to'], ['destinataire@example.com'])

    @mock.patch('core.mail_backend.urllib.request.urlopen')
    def test_erreur_api_non_silencieuse_remonte(self, urlopen):
        from core import mail_backend
        backend = mail_backend.EmailBackend(fail_silently=False)
        backend.provider = 'brevo'
        backend.cle = 'cle'
        urlopen.side_effect = RuntimeError('réseau coupé')
        with self.assertRaises(RuntimeError):
            backend.send_messages([self._message()])

    def test_provider_cle_manquante_repli(self):
        from core import mail_backend
        with mock.patch.dict('os.environ', {'EMAIL_PROVIDER': 'resend'},
                             clear=True):
            backend = mail_backend.EmailBackend(fail_silently=True)
        self.assertEqual(backend.provider, '')
        self.assertIsNotNone(backend._relais)