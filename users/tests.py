import re
from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from establishments.models import Etablissement
from .models import Patient, Permission, Personnel, Role


class PermissionModelTest(TestCase):
    def test_creation_permission(self):
        p = Permission.objects.create(nom='consulter_dmp', description='Consulter DMP')
        self.assertEqual(str(p), 'consulter_dmp')
        self.assertTrue(Permission.objects.filter(nom='consulter_dmp').exists())

    def test_nom_unique(self):
        Permission.objects.create(nom='test_unique')
        with self.assertRaises(Exception):
            Permission.objects.create(nom='test_unique')


class RoleModelTest(TestCase):
    def setUp(self):
        self.perm = Permission.objects.create(nom='prescrire')

    def test_role_permissions(self):
        role = Role.objects.create(nomRole='Médecin')
        role.attribuer_permission(self.perm)
        self.assertIn(self.perm, role.get_permissions())

    def test_get_permissions_vide(self):
        role = Role.objects.create(nomRole='Infirmier')
        self.assertEqual(role.get_permissions().count(), 0)


class UtilisateurPasswordTest(TestCase):
    """Vérifie le hachage et les opérations sur le mot de passe."""

    def test_mot_de_passe_hache(self):
        p = Personnel.objects.create_user(
            email='test@example.com', nom='Test', prenom='User',
            password='Secret123!', matricule='MAT-001')
        p.refresh_from_db()
        self.assertNotEqual(p.password, 'Secret123!')
        # Devrait commencer par pbkdf2_ (hachage Django)
        self.assertTrue(p.password.startswith('pbkdf2_'))

    def test_verifier_mot_de_passe(self):
        p = Personnel.objects.create_user(
            email='test2@example.com', nom='Test', prenom='User',
            password='Secret123!', matricule='MAT-002')
        self.assertTrue(p.verifier_mot_de_passe('Secret123!'))
        self.assertFalse(p.verifier_mot_de_passe('mauvais'))

    def test_modifier_mot_de_passe(self):
        p = Personnel.objects.create_user(
            email='test3@example.com', nom='Test', prenom='User',
            password='Ancien123!', matricule='MAT-003')
        resultat = p.modifier_mot_de_passe('Ancien123!', 'Nouveau456!')
        self.assertTrue(resultat)
        p.refresh_from_db()
        self.assertTrue(p.verifier_mot_de_passe('Nouveau456!'))

    def test_modifier_mot_de_passe_mauvais_ancien(self):
        p = Personnel.objects.create_user(
            email='test4@example.com', nom='Test', prenom='User',
            password='Ancien123!', matricule='MAT-004')
        resultat = p.modifier_mot_de_passe('mauvais', 'Nouveau456!')
        self.assertFalse(resultat)
        p.refresh_from_db()
        self.assertTrue(p.verifier_mot_de_passe('Ancien123!'))


class PersonnelModelTest(TestCase):
    def setUp(self):
        self.etablissement = Etablissement.objects.create(
            nom='Hôpital Test', adresse='Adresse', telephone='691000000',
            email='hopital@test.com')
        self.role_medecin = Role.objects.create(nomRole='Médecin')
        self.role_infirmier = Role.objects.create(nomRole='Infirmier')
        self.perm = Permission.objects.create(nom='creer_consultation')
        self.role_medecin.attribuer_permission(self.perm)

    def test_creation_personnel(self):
        p = Personnel.objects.create_user(
            email='med@test.com', nom='Dupont', prenom='Marie',
            password='Mdp123!', matricule='MED-001',
            etablissement=self.etablissement)
        self.assertEqual(p.etablissement, self.etablissement)
        self.assertIsNone(p.role)

    def test_roles_et_permissions(self):
        p = Personnel.objects.create_user(
            email='med2@test.com', nom='Dupont', prenom='Jean',
            password='Mdp123!', matricule='MED-002')
        p.role = self.role_medecin
        p.save()
        self.assertTrue(p.a_permission('creer_consultation'))
        self.assertFalse(p.a_permission('gerer_personnel'))

    def test_proprietes_roles(self):
        p = Personnel.objects.create_user(
            email='med3@test.com', nom='Durand', prenom='Paul',
            password='Mdp123!', matricule='MED-003')
        p.role = self.role_medecin
        p.save()
        self.assertTrue(p.est_medecin)
        self.assertFalse(p.est_infirmier)

    def test_consulter_profil(self):
        p = Personnel.objects.create_user(
            email='med4@test.com', nom='Martin', prenom='Luc',
            password='Mdp123!', matricule='MED-004')
        profil = p.consulter_profil()
        self.assertEqual(profil['email'], 'med4@test.com')
        self.assertEqual(profil['matricule'], 'MED-004')

    def test_matricule_unique(self):
        Personnel.objects.create_user(
            email='med5@test.com', nom='A', prenom='B',
            password='Mdp123!', matricule='MED-UNIQUE')
        with self.assertRaises(Exception):
            Personnel.objects.create_user(
                email='med6@test.com', nom='C', prenom='D',
                password='Mdp123!', matricule='MED-UNIQUE')


class PatientModelTest(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create_user(
            email='patient@test.com', nom='Patient', prenom='Test',
            password='Mdp123!', numeroPatient='PAT-001',
            nomContactUrgencePrincipal='Mère', telephoneContactUrgencePrincipal='690000000',
            lienContactUrgencePrincipal='Mère')

    def test_contact_urgence_obligatoire_rempli(self):
        self.assertEqual(self.patient.nomContactUrgencePrincipal, 'Mère')
        self.assertEqual(self.patient.lienContactUrgencePrincipal, 'Mère')

    def test_contact_secondaire_facultatif(self):
        self.assertEqual(self.patient.nomContactUrgenceSecondaire, '')
        # Ajout du secondaire
        self.patient.nomContactUrgenceSecondaire = 'Père'
        self.patient.telephoneContactUrgenceSecondaire = '691000000'
        self.patient.lienContactUrgenceSecondaire = 'Père'
        self.patient.save()
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.nomContactUrgenceSecondaire, 'Père')

    def test_consulter_profil(self):
        profil = self.patient.consulter_profil()
        self.assertEqual(profil['numeroPatient'], 'PAT-001')

    def test_numero_patient_unique(self):
        with self.assertRaises(Exception):
            Patient.objects.create_user(
                email='patient2@test.com', nom='X', prenom='Y',
                password='Mdp123!', numeroPatient='PAT-001',
                nomContactUrgencePrincipal='Mère',
                telephoneContactUrgencePrincipal='690000000',
                lienContactUrgencePrincipal='Mère')


class UtilisateurSuperuserTest(TestCase):
    def test_creation_superuser(self):
        from django.core.exceptions import ValidationError
        admin = Personnel.objects.create_superuser(
            email='admin@test.com', nom='Admin', prenom='Super',
            password='Admin123!', matricule='ADM-001')
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)


class SecuriteConnexionTest(TestCase):
    """T8 — verrouillage après 5 échecs (15 min), réinitialisation du mot de
    passe « oublié » (lien signé 24 h), déconnexion automatique par inactivité."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Test', adresse='Adresse', telephone='691000000',
            email='hopital@test.com')
        self.pers = Personnel.objects.create_user(
            email='seco@test.com', nom='Securite', prenom='Test',
            password='Mdp123!', matricule='SEC-01', etablissement=self.etab)

    def _tentatives(self, n):
        for _ in range(n):
            self.client.post(reverse('login'), {
                'username': self.pers.email, 'password': 'mauvais'})

    def test_verrouillage_apres_cinq_echecs(self):
        self._tentatives(5)
        self.pers.refresh_from_db()
        self.assertIsNotNone(self.pers.verrouillageJusqua)
        self.assertEqual(self.pers.nbEchecsConnexion, 0)  # compteur remis à 0
        # Même avec le bon mot de passe, le compte reste verrouillé.
        r = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['form'].verrouille)
        self.assertContains(r, 'verrouillé')

    def test_quatre_echecs_ne_verrouillent_pas(self):
        self._tentatives(4)
        self.pers.refresh_from_db()
        self.assertIsNone(self.pers.verrouillageJusqua)
        r = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)  # 5e tentative (réussie) acceptée

    def test_deverrouillage_apres_duree_ecoulee(self):
        self._tentatives(5)
        Personnel.objects.filter(pk=self.pers.pk).update(
            verrouillageJusqua=timezone.now() - timedelta(minutes=16))
        r = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)

    def test_echec_reinitialise_les_compteurs_au_login_suivant(self):
        self._tentatives(2)
        r = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 302)
        self.pers.refresh_from_db()
        self.assertEqual(self.pers.nbEchecsConnexion, 0)
        self.assertIsNone(self.pers.verrouillageJusqua)

    def test_verrouillage_patient_partage_la_table_commune(self):
        pat = Patient.objects.create_user(
            email='pat-sec@test.com', nom='P', prenom='T', password='Mdp123!',
            numeroPatient='PAT-SEC', nomContactUrgencePrincipal='M',
            telephoneContactUrgencePrincipal='0', lienContactUrgencePrincipal='M')
        for _ in range(5):
            self.client.post(reverse('login'), {
                'username': pat.email, 'password': 'mauvais'})
        pat.refresh_from_db()
        self.assertIsNotNone(pat.verrouillageJusqua)
        # Le vrai chemin de connexion (MedShareAuthenticationForm) l'annonce.
        r = self.client.post(reverse('login'), {
            'username': pat.email, 'password': 'Mdp123!'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['form'].verrouille)

    def test_mot_de_passe_oublie_flux_complet(self):
        r = self.client.post(reverse('mot_de_passe_oublie'), {'email': self.pers.email})
        self.assertRedirects(r, reverse('login'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('MedShare', mail.outbox[0].subject)
        jeton = re.search(
            r'/compte/reinitialiser/([^/\s]+)/', mail.outbox[0].body).group(1)

        # Page « nouveau mot de passe » accessible avec le lien valide.
        r2 = self.client.get(f'/compte/reinitialiser/{jeton}/')
        self.assertEqual(r2.status_code, 200)

        r3 = self.client.post(f'/compte/reinitialiser/{jeton}/', {
            'nouveau_mot_de_passe': 'NvMot123!',
            'confirmer_mot_de_passe': 'NvMot123!'})
        self.assertRedirects(r3, reverse('login'))
        self.pers.refresh_from_db()
        self.assertTrue(self.pers.check_password('NvMot123!'))

        # L'ancien mot de passe est refusé, le nouveau passe.
        r4 = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        self.assertEqual(r4.status_code, 200)
        r5 = self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'NvMot123!'})
        self.assertEqual(r5.status_code, 302)

        # Le lien ne peut pas être réutilisé (mot de passe déjà changé).
        r6 = self.client.get(f'/compte/reinitialiser/{jeton}/')
        self.assertRedirects(r6, reverse('login'))

    def test_reinitialisation_compte_inconnu_aucun_email(self):
        r = self.client.post(reverse('mot_de_passe_oublie'), {'email': 'absent@test.com'},
                             follow=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(r, 'Si cette adresse est associée')

    def test_lien_reinitialisation_falsifie_refuse(self):
        self.client.post(reverse('mot_de_passe_oublie'), {'email': self.pers.email})
        jeton = re.search(
            r'/compte/reinitialiser/([^/\s]+)/', mail.outbox[0].body).group(1)
        r = self.client.get(f'/compte/reinitialiser/{jeton[:-4]}AAAA/')
        self.assertRedirects(r, reverse('login'))

    def test_inactivite_deconnecte_apres_seuil(self):
        self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        session = self.client.session
        session['_derniere_activite'] = (timezone.now() - timedelta(minutes=31)).isoformat()
        session.save()
        r = self.client.get(reverse('dashboard'))
        self.assertRedirects(r, reverse('login'))

    def test_inactivite_recente_conserve_la_session(self):
        self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})
        session = self.client.session
        session['_derniere_activite'] = (timezone.now() - timedelta(minutes=1)).isoformat()
        session.save()
        r = self.client.get(reverse('dashboard'))
        # La requête est traitée normalement (pas de redirection vers le login).
        self.assertNotIn('next=', r.headers.get('Location', ''))


class ChangementMotDePasseFlowTest(TestCase):
    """P1 — après le changement obligatoire du mot de passe, l'utilisateur
    retrouve DIRECTEMENT son tableau de bord sans repasser par le login
    (update_session_auth_hash conserve la session valide)."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Test', adresse='Adresse', telephone='691000000',
            email='hopital@test.com')
        role_med = Role.objects.create(nomRole='Médecin')
        self.pers = Personnel.objects.create_user(
            email='chgt@test.com', nom='Changement', prenom='Test',
            password='Ancien123!', matricule='CHG-01',
            etablissement=self.etab, doitChangerMotDePasse=True)
        self.pers.role = role_med
        self.pers.save()

    def test_flux_complet_sans_retour_au_login(self):
        self.client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Ancien123!'})
        r = self.client.get(reverse('changer_mot_de_passe'))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse('changer_mot_de_passe'), {
            'ancien_mot_de_passe': 'Ancien123!',
            'nouveau_mot_de_passe': 'Nouveau456!',
            'confirmer_mot_de_passe': 'Nouveau456!',
        })
        self.assertRedirects(r, reverse('changer_mot_de_passe_succes'))
        r = self.client.get(reverse('changer_mot_de_passe_succes'))
        self.assertContains(r, 'Mot de passe mis à jour')
        self.assertContains(r, 'Accéder à mon tableau de bord')
        # Accès direct au dashboard : toujours authentifié, aucun retour login.
        r = self.client.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)
        self.pers.refresh_from_db()
        self.assertFalse(self.pers.doitChangerMotDePasse)
        self.assertTrue(self.pers.verifier_mot_de_passe('Nouveau456!'))


class SessionUniqueActiveTest(TestCase):
    """T4 (addendum 4) — une seule session active par compte : une connexion
    plus récente déconnecte proprement l'ancien appareil (message explicite),
    l'appareil récent reste connecté."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Test', adresse='Adresse', telephone='691000000',
            email='hopital@test.com')
        role_med = Role.objects.create(nomRole='Médecin')
        self.pers = Personnel.objects.create_user(
            email='uniq@test.com', nom='Unique', prenom='Session',
            password='Mdp123!', matricule='UNIQ-01', etablissement=self.etab)
        self.pers.role = role_med
        self.pers.save()

    def _login(self, client):
        return client.post(reverse('login'), {
            'username': self.pers.email, 'password': 'Mdp123!'})

    def test_deuxieme_connexion_deconnecte_l_ancien_appareil(self):
        c1, c2 = Client(), Client()
        self.assertEqual(self._login(c1).status_code, 302)
        r2 = self._login(c2)
        self.assertEqual(r2.status_code, 302)

        # L'ancien appareil est déconnecté et reçoit un message explicite.
        r_old = c1.get(reverse('dashboard'))
        self.assertEqual(r_old.status_code, 302)
        self.assertEqual(r_old.headers['Location'], reverse('login'))
        page = c1.get(reverse('login'))
        self.assertContains(page, 'remplacée par une connexion plus récente')

        # Le nouvel appareil continue normalement.
        r_new = c2.get(reverse('dashboard'))
        self.assertEqual(r_new.status_code, 200)

    def test_session_consommee_reste_valide_sans_remplacement(self):
        c = Client()
        self._login(c)
        r = c.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_reconnexion_meme_appareil_reste_valide(self):
        c = Client()
        self._login(c)
        self._login(c)
        r = c.get(reverse('dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_remplacement_journalise(self):
        from urgences.models import JournalAudit
        c1, c2 = Client(), Client()
        self._login(c1)
        self._login(c2)
        self.assertTrue(
            JournalAudit.objects.filter(action='SESSION_REMPLACEE').exists())

    def test_session_active_key_renouvelee_a_chaque_login(self):
        c = Client()
        self._login(c)
        self.pers.refresh_from_db()
        premiere = self.pers.session_active_key
        self.assertTrue(premiere)
        c2 = Client()
        self._login(c2)
        self.pers.refresh_from_db()
        self.assertNotEqual(self.pers.session_active_key, premiere)


class Renvoi2FACooldownTest(TestCase):
    """T2 — robustesse e-mail : délai de sécurité entre deux envois du code
    2FA (anti-spam), en plus de la limite de 3 renvois."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Test', adresse='Adresse', telephone='691000000',
            email='hopital@test.com')
        role_admin = Role.objects.create(nomRole='Administrateur')
        self.admin = Personnel.objects.create_user(
            email='ad2fa@test.com', nom='Admin', prenom='Deux',
            password='Mdp123!', matricule='AD2FA-01',
            etablissement=self.etab)
        self.admin.role = role_admin
        self.admin.save()

    def test_renvoi_trop_rapide_bloque_puis_autorise(self):
        self.client.post(reverse('login'), {
            'username': self.admin.email, 'password': 'Mdp123!'})
        self.client.get(reverse('superadmin_2fa'))  # émission initiale (1)
        nb = len(mail.outbox)

        # Renvoi immédiat : bloqué par le délai de 60 s.
        r = self.client.post(reverse('superadmin_2fa'), {'renvoyer': '1'},
                             follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Patientez une minute')
        self.assertEqual(len(mail.outbox), nb)

        # Délai franchi : le renvoi passe et un e-mail part.
        session = self.client.session
        session['2fa_dernier_envoi'] = (
            timezone.now() - timedelta(seconds=90)).isoformat()
        session.save()
        r = self.client.post(reverse('superadmin_2fa'), {'renvoyer': '1'})
        self.assertRedirects(r, reverse('superadmin_2fa'))
        self.assertEqual(len(mail.outbox), nb + 1)