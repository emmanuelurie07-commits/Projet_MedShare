"""Vérifications pré-déploiement (Tâche 1) — sessions Patient en production.

Couvre les scénarios « mauvaise surprise » possibles sur Render :

1. Une session Patient survit à la navigation sur plusieurs pages avec
   ``DEBUG=False`` (marqueur de modèle ``_auth_user_model`` maintenu,
   jamais de déconnexion silencieuse).
2. Deux patients connectés (« deux navigateurs ») restent strictement isolés
   y compris quand le jeton d'accès de l'autre est deviné (404).
3. Collision de pk Personnel=1 / Patient=1 avec logins RÉELS parallèles
   (multi-table inheritance) : chaque session résout le bon modèle.
4. Comportement réel des cookies de production (Secure) sur HTTPS : la
   session patient n'est jamais perdue entre deux pages (emulateur HTTPS).
"""
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import ChangerMotDePasseForm
from .models import Patient, Personnel, Role, Utilisateur


def _creer_patient(email, code):
    return Patient.objects.create_user(
        email=email, nom='Pat', prenom='Test', password='Mdp123!',
        numeroPatient=code, nomContactUrgencePrincipal='Mère',
        telephoneContactUrgencePrincipal='69', lienContactUrgencePrincipal='Mère',
        doitChangerMotDePasse=False, codeConfirmation='123456')


def _login_reel(client, email, password='Mdp123!', secure=False):
    """POST du vrai formulaire de connexion (MedShareLoginView).
    Contrairement à client.login(), il pose le marqueur de modèle en session."""
    kwargs = {'secure': True} if secure else {}
    return client.post(reverse('login'),
                       {'username': email, 'password': password}, **kwargs)


def _urls_patient(p):
    """Les pages réellement accessibles au patient connecté (la consultation
    du DMP /dmp/patients/<pk>/dmp/ est une vue SOIGNANT protégée par rôle)."""
    return [
        reverse('dashboard_patient', kwargs={'jeton': p.jeton_acces}),
        reverse('mon_historique_self'),
        reverse('mon_acces_historique_self'),
        reverse('mes_ordonnances_self'),
        reverse('mon_historique', kwargs={'patient_pk': p.pk}),
        reverse('mon_acces_historique', kwargs={'patient_pk': p.pk}),
        reverse('mes_ordonnances', kwargs={'patient_pk': p.pk}),
    ]


class SessionPatientMultiPagesProduitTest(TestCase):
    """Tâche 1 — la session patient survit à plusieurs pages, DEBUG=False."""

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', 'localhost'])
    def test_login_reel_patient_survit_a_7_pages_debug_false(self):
        p = _creer_patient('nav@test.com', 'MS-NAV1')
        r = _login_reel(self.client, p.email)
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()  # jeton régénéré au login
        self.assertEqual(self.client.session.get('_auth_user_model'), 'patient')
        self.assertEqual(self.client.session['_auth_user_id'], str(p.pk))

        for url in _urls_patient(p):
            reponse = self.client.get(url)
            self.assertEqual(reponse.status_code, 200,
                             f'{url} devrait répondre 200 (pas de déconnexion) '
                             f'— reçu {reponse.status_code} '
                             f'-> {reponse.get("Location", "")}')
            self.assertEqual(reponse.context['user'].pk, p.pk,
                             f'{url} ne devrait jamais résoudre un autre utilisateur')
            # Le marqueur et l'identité de session ne bougent pas d'une page à l'autre.
            self.assertEqual(self.client.session.get('_auth_user_model'), 'patient')
            self.assertEqual(self.client.session['_auth_user_id'], str(p.pk))

    @override_settings(DEBUG=False, SESSION_COOKIE_SECURE=True,
                       CSRF_COOKIE_SECURE=True,
                       ALLOWED_HOSTS=['testserver', 'localhost'])
    def test_session_patient_cookies_secures_https(self):
        """Emulation de la production Render (HTTPS, cookies Secure) :
        la session patient n'est jamais perdue entre les pages."""
        p = _creer_patient('http@test.com', 'MS-HTT0')
        r = _login_reel(self.client, p.email, secure=True)
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        for url in _urls_patient(p):
            reponse = self.client.get(url, secure=True)
            self.assertEqual(reponse.status_code, 200,
                             f'HTTPS {url} devrait répondre 200')
            self.assertEqual(reponse.context['user'].pk, p.pk)
            self.assertEqual(self.client.session['_auth_user_id'], str(p.pk))


class SessionPatientIsolementTest(TestCase):
    """Tâche 1 — deux patients connectés en parallèle restent isolés."""

    def test_deux_patients_navigateurs_paralleles_isoles(self):
        p1 = _creer_patient('nav1@test.com', 'MS-ISO1')
        p2 = _creer_patient('nav2@test.com', 'MS-ISO2')
        c1, c2 = Client(), Client()

        self.assertEqual(_login_reel(c1, p1.email).status_code, 302)
        self.assertEqual(_login_reel(c2, p2.email).status_code, 302)
        p1.refresh_from_db()
        p2.refresh_from_db()

        # Chacun navigue sur ses pages : aucune interférence.
        self.assertEqual(c1.get(reverse('dashboard_patient',
                                        kwargs={'jeton': p1.jeton_acces})).status_code, 200)
        self.assertEqual(c2.get(reverse('dashboard_patient',
                                        kwargs={'jeton': p2.jeton_acces})).status_code, 200)
        self.assertEqual(c1.get(reverse('mes_ordonnances',
                                        kwargs={'patient_pk': p1.pk})).status_code, 200)
        self.assertEqual(c2.get(reverse('mes_ordonnances',
                                        kwargs={'patient_pk': p2.pk})).status_code, 200)

        # Tentative croisée avec le jeton de l'autre : refusée (404).
        self.assertEqual(c1.get(reverse('dashboard_patient',
                                        kwargs={'jeton': p2.jeton_acces})).status_code, 404)
        self.assertEqual(c2.get(reverse('dashboard_patient',
                                        kwargs={'jeton': p1.jeton_acces})).status_code, 404)

        # Les deux sessions sont TOUJOURS celle du bon patient.
        self.assertEqual(c1.session['_auth_user_id'], str(p1.pk))
        self.assertEqual(c1.session.get('_auth_user_model'), 'patient')
        self.assertEqual(c2.session['_auth_user_id'], str(p2.pk))
        self.assertEqual(c2.session.get('_auth_user_model'), 'patient')


class CollisionPkSessionsParallelesTest(TestCase):
    """Tâche 1 — Personnel.pk=1 ET Patient.pk=1, logins réels en parallèle.

    Multi-table inheritance : les deux AutoField démarrent à 1. Le marqueur
    de modèle en session doit lever l'ambiguïté lors du rechargement des
    sessions (get_user)."""

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', 'localhost'])
    def test_personnel_et_patient_pk1_sessions_non_confondues(self):
        pers = Personnel.objects.create_user(
            email='med@coll.test', nom='Med', prenom='Doc',
            password='Mdp123!', matricule='MAT-PK1')
        # Supabase / Postgres ne reset pas les séquences entre tests : la
        # séquence idPersonnel a déjà été consommée par le super-admin issu de
        # la migration 0008. On force donc Patient.pk := Personnel.pk pour
        # reproduire EXACTEMENT la collision de pk du multi-table inheritance
        # (deux AutoField indépendants qui peuvent avoir la même valeur).
        pat = _creer_patient('pat@coll.test', 'MS-PK11')
        Patient.objects.filter(idPatient=pat.idPatient).update(idPatient=pers.pk)
        pat = Patient.objects.get(idPatient=pers.pk)  # recharge après le changement de pk
        self.assertEqual(pers.pk, pat.pk)

        c_pers, c_pat = Client(), Client()
        self.assertEqual(_login_reel(c_pers, pers.email).status_code, 302)
        self.assertEqual(_login_reel(c_pat, pat.email).status_code, 302)
        pers.refresh_from_db()
        pat.refresh_from_db()

        # Marqueur de session : bon modèle, bon pk.
        self.assertEqual(c_pers.session.get('_auth_user_model'), 'personnel')
        self.assertEqual(c_pers.session['_auth_user_id'], str(pers.pk))
        self.assertEqual(c_pat.session.get('_auth_user_model'), 'patient')
        self.assertEqual(c_pat.session['_auth_user_id'], str(pat.pk))

        # Chacun accède à SON dashboard par son jeton.
        self.assertEqual(c_pers.get(reverse('dashboard_personnel',
                                            kwargs={'jeton': pers.jeton_acces})).status_code, 200)
        self.assertEqual(c_pat.get(reverse('dashboard_patient',
                                           kwargs={'jeton': pat.jeton_acces})).status_code, 200)

        # Aucun croisement : le patient ne reçoit jamais le dashboard du médecin
        # (même pk, jeton différent) et inversement.
        self.assertEqual(c_pat.get(reverse('dashboard_personnel',
                                           kwargs={'jeton': pers.jeton_acces})).status_code, 404)
        self.assertEqual(c_pers.get(reverse('dashboard_personnel',
                                            kwargs={'jeton': pat.jeton_acces})).status_code, 404)

        # Et les deux sessions restent valides après toutes ces requêtes.
        self.assertEqual(c_pers.session['_auth_user_id'], str(pers.pk))
        self.assertEqual(c_pat.session['_auth_user_id'], str(pat.pk))


class MoindrePrivilegePatientTest(TestCase):
    """Tâche 1 — le patient ne peut JAMAIS atteindre les vues soignants.

    La consultation ''métier'' du DMP est une vue protégée par rôle
    (@role_required_strict Médecin/Administrateur/Infirmier) : le patient y
    est redirigé, jamais le contenu d'un dossier ne lui est exposé."""

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', 'localhost'])
    def test_patient_bloque_sur_vue_soignant_et_medecin_autorise(self):
        p = _creer_patient('pmin@test.com', 'MS-MIN1')
        role = Role.objects.get_or_create(nomRole='Médecin')[0]
        med = Personnel.objects.create_user(
            email='med@min.test', nom='Med', prenom='Dr',
            password='Mdp123!', matricule='MAT-MIN1')
        med.role = role
        med.save()

        c_pat, c_med = Client(), Client()
        self.assertEqual(_login_reel(c_pat, p.email).status_code, 302)
        self.assertEqual(_login_reel(c_med, med.email).status_code, 302)

        url = reverse('consulter_dmp', kwargs={'patient_pk': p.pk})
        # Le patient : redirigé (302), jamais le contenu.
        self.assertEqual(c_pat.get(url).status_code, 302)
        # Le médecin dispose bien du rôle : la vue répond.
        self.assertEqual(c_med.get(url).status_code, 200)


class ObligationChangementMotDePasseTest(TestCase):
    """Régression : l'obligation de changement de mot de passe n'est imposée
    qu'à la PREMIÈRE connexion et disparaît dès que l'utilisateur a défini
    son propre mot de passe — pour TOUS les rôles (personnel, patient,
    super administrateur), quelle que soit la voie utilisée (formulaire
    imposé, formulaire « mot de passe oublié », admin Django)."""

    def _personnel(self, **extra):
        return Personnel.objects.create_user(
            email='oblig@test.com', nom='Pré', prenom='Test',
            password='Mdp123!', matricule='MAT-OBL',
            doitChangerMotDePasse=True, **extra)

    def test_formulaire_impose_leve_obligation_personnel(self):
        pers = self._personnel()
        form = ChangerMotDePasseForm(pers, data={
            'ancien_mot_de_passe': 'Mdp123!',
            'nouveau_mot_de_passe': 'Nouveau123!',
            'confirmer_mot_de_passe': 'Nouveau123!',
        })
        self.assertTrue(form.is_valid())
        form.save()
        pers.refresh_from_db()
        self.assertFalse(pers.doitChangerMotDePasse)
        self.assertTrue(pers.verifier_mot_de_passe('Nouveau123!'))

    def test_set_password_admin_leve_obligation_compte_existant(self):
        pers = self._personnel()
        pers.set_password('ViaAdmin123!')
        pers.refresh_from_db()
        self.assertFalse(pers.doitChangerMotDePasse)
        self.assertTrue(pers.verifier_mot_de_passe('ViaAdmin123!'))

    def test_creation_nouveau_compte_conserve_obligation(self):
        pers = Personnel.objects.create_user(
            email='neuf@test.com', nom='Neuf', prenom='Test',
            password='Mdp123!', matricule='MAT-NEUF',
            doitChangerMotDePasse=True)
        pers.refresh_from_db()
        self.assertTrue(pers.doitChangerMotDePasse)

    def test_superadmin_utilisateur_base_leve_obligation_personnel(self):
        """Le super administrateur est authentifié comme Personnel,
        mais on vérifie aussi le cas d'un Utilisateur « pur » passé au
        formulaire : le sous-modèle porte bien le drapeau, il doit être
        levé sur la ligne Personnel (multi-table inheritance)."""
        pers = self._personnel(is_superuser=True, is_staff=True)
        base = Utilisateur.objects.get(pk=pers.pk)
        form = ChangerMotDePasseForm(base, data={
            'ancien_mot_de_passe': 'Mdp123!',
            'nouveau_mot_de_passe': 'SuperNouveau123!',
            'confirmer_mot_de_passe': 'SuperNouveau123!',
        })
        self.assertTrue(form.is_valid())
        form.save()
        pers.refresh_from_db()
        self.assertFalse(pers.doitChangerMotDePasse)
        self.assertTrue(pers.verifier_mot_de_passe('SuperNouveau123!'))

    def test_parcours_complet_plus_de_blocage_apres_changement(self):
        """Flux réel : (1) à la 1re connexion, redirection forcée vers le
        changement ; (2) après le changement, le tableau de bord répond 200
        à chaque requête ultérieure (fini le blocage à chaque Ctrl+F5)."""
        pers = self._personnel()
        pers.role = Role.objects.get_or_create(nomRole='Médecin')[0]
        pers.save()
        self.client.post(reverse('login'),
                         {'username': pers.email, 'password': 'Mdp123!'})
        # 1re connexion : contrainte — le dashboard est inatteignable.
        reponse = self.client.get(reverse('dashboard'))
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(reponse.get('Location'), reverse('changer_mot_de_passe'))
        # L'utilisateur change son mot de passe.
        reponse = self.client.post(reverse('changer_mot_de_passe'), {
            'ancien_mot_de_passe': 'Mdp123!',
            'nouveau_mot_de_passe': 'BienNouveau123!',
            'confirmer_mot_de_passe': 'BienNouveau123!',
        })
        self.assertIn(reponse.status_code, (200, 302))
        pers.refresh_from_db()
        self.assertFalse(pers.doitChangerMotDePasse)
        # Connexions ultérieures : plus aucun blocage.
        self.client.get(reverse('logout'))
        self.client.post(reverse('login'),
                         {'username': pers.email, 'password': 'BienNouveau123!'})
        reponse = self.client.get(reverse('dashboard'))
        self.assertEqual(reponse.status_code, 200)