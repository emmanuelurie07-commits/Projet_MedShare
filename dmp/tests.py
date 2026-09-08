from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from establishments.models import Etablissement
from users.models import Patient, Personnel, Role

from .models import (AccesDMP, Consultation, DossierMedicalPartage,
                     LignePrescription, Medicament, Prescription)


class BaseMedTest(TestCase):
    """Classe de base avec les objets communs."""
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='A', telephone='69000', email='h@h.cm')
        role_med = Role.objects.create(nomRole='Médecin')
        self.medecin = Personnel.objects.create_user(
            email='med@test.com', nom='Dupont', prenom='Jean',
            password='Mdp123!', matricule='MED-01', etablissement=self.etab)
        self.medecin.role = role_med
        self.medecin.save()
        self.patient = Patient.objects.create_user(
            email='patient@test.com', nom='Martin', prenom='Luc',
            password='Mdp123!', numeroPatient='PAT-01',
            doitChangerMotDePasse=False,
            nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='690000000',
            lienContactUrgencePrincipal='Mère')
        self.dmp = DossierMedicalPartage.objects.create(
            patient=self.patient, numeroDMP='DMP-01')


class DMPTest(BaseMedTest):
    def test_creation_dmp(self):
        self.assertEqual(self.dmp.statut, 'ACTIF')
        self.assertEqual(str(self.dmp), f"DMP DMP-01 — {self.patient}")

    def test_arquiver_dmp(self):
        self.dmp.archiver()
        self.dmp.refresh_from_db()
        self.assertEqual(self.dmp.statut, 'ARCHIVE')

    def test_historique_vide(self):
        self.assertEqual(self.dmp.consulter_historique().count(), 0)


class ConsultationTest(BaseMedTest):
    def setUp(self):
        super().setUp()
        self.consultation = Consultation.objects.create(
            dmp=self.dmp, etablissement=self.etab, medecin=self.medecin,
            motif='Fièvre', diagnostic='Paludisme')

    def test_creation_consultation(self):
        self.assertEqual(self.consultation.motif, 'Fièvre')
        self.assertEqual(self.consultation.diagnostic, 'Paludisme')
        self.assertIsNotNone(self.consultation.dateHeure)

    def test_appartient_au_dmp(self):
        self.assertEqual(self.dmp.consultations.first(), self.consultation)

    def test_modifier_consultation(self):
        self.consultation.modifier(diagnostic='Grippe')
        self.consultation.refresh_from_db()
        self.assertEqual(self.consultation.diagnostic, 'Grippe')

    def test_annuler_consultation(self):
        pk = self.consultation.pk
        self.consultation.annuler()
        self.consultation.refresh_from_db()
        # Non-suppression systématique (itération 3) : l'acte est marqué ANNULEE
        self.assertTrue(Consultation.objects.filter(pk=pk).exists())
        self.assertEqual(self.consultation.statut, 'ANNULEE')


class PrescriptionTest(BaseMedTest):
    def setUp(self):
        super().setUp()
        self.consultation = Consultation.objects.create(
            dmp=self.dmp, etablissement=self.etab, medecin=self.medecin,
            motif='Test')
        self.medicament = Medicament.objects.create(
            nomCommercial='Paracétamol', forme='Comprimé')
        self.prescription = Prescription.objects.create(
            consultation=self.consultation, instructions='Prendre après repas')

    def test_creation_prescription(self):
        self.assertEqual(self.prescription.instructions, 'Prendre après repas')
        self.assertIsNotNone(self.prescription.datePrescription)

    def test_prescription_liee_consultation(self):
        self.assertEqual(self.consultation.prescription, self.prescription)

    def test_generer_ordonnance(self):
        ligne = LignePrescription.objects.create(
            prescription=self.prescription, medicament=self.medicament,
            posologie='1 comprimé', frequence='2 fois/jour', duree='3 jours',
            quantite='6')
        ordonnance = self.prescription.generer_ordonnance()
        self.assertEqual(len(ordonnance['lignes']), 1)
        self.assertEqual(ordonnance['lignes'][0], ligne)

    def test_annuler_prescription(self):
        pk = self.prescription.pk
        self.prescription.annuler()
        self.prescription.refresh_from_db()
        # Non-suppression systématique (itération 3) : l'ordonnance est marquée ANNULEE
        self.assertTrue(Prescription.objects.filter(pk=pk).exists())
        self.assertEqual(self.prescription.statut, 'ANNULEE')


class LignePrescriptionTest(BaseMedTest):
    def setUp(self):
        super().setUp()
        self.consultation = Consultation.objects.create(
            dmp=self.dmp, etablissement=self.etab, medecin=self.medecin,
            motif='Test')
        self.prescription = Prescription.objects.create(
            consultation=self.consultation)
        self.medicament = Medicament.objects.create(
            nomCommercial='Amoxicilline', forme='Gélule')

    def test_ligne_medicament(self):
        ligne = LignePrescription.objects.create(
            prescription=self.prescription, medicament=self.medicament,
            posologie='1 gélule', frequence='3 fois/jour', duree='7 jours')
        self.assertEqual(self.medicament.lignes_prescription.first(), ligne)
        self.assertEqual(self.prescription.lignes.first(), ligne)

    def test_plusieurs_lignes(self):
        med2 = Medicament.objects.create(nomCommercial='Ibuprofène', forme='Comprimé')
        LignePrescription.objects.create(
            prescription=self.prescription, medicament=self.medicament,
            posologie='1 gélule', duree='7 jours')
        LignePrescription.objects.create(
            prescription=self.prescription, medicament=med2,
            posologie='1 comprimé', duree='5 jours')
        self.assertEqual(self.prescription.lignes.count(), 2)


class MedicamentTest(TestCase):
    def test_creation(self):
        med = Medicament.objects.create(nomCommercial='Salbutamol', forme='Spray')
        self.assertEqual(str(med), 'Salbutamol')


# ──────────────────────────────────────────────
# T7 — Approbation patient (AccesDMP, remplacement du PIN soignant)
# ──────────────────────────────────────────────
class ApprobationPatientTest(BaseMedTest):
    def _creer_demande(self, statut=AccesDMP.Statut.EN_ATTENTE):
        return AccesDMP.objects.create(
            patient=self.patient, etablissement=self.etab,
            demandeur=self.medecin, statut=statut)

    def test_demande_initiale_en_attente(self):
        acces = self._creer_demande()
        self.assertFalse(acces.est_actif)
        self.assertEqual(acces.get_statut_display(), 'En attente')

    def test_approuver_et_revoquer(self):
        acces = self._creer_demande()
        acces.approuver()
        acces.refresh_from_db()
        self.assertTrue(acces.est_actif)
        acces.revoquer()
        acces.refresh_from_db()
        self.assertFalse(acces.est_actif)
        self.assertEqual(acces.get_statut_display(), 'Révoqué')

    def test_consultation_bloquee_sans_approbation(self):
        from dmp.services import verifier_ou_demander_acces
        autoriser, demande = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)
        self.assertFalse(autoriser)
        self.assertEqual(demande.statut, AccesDMP.Statut.EN_ATTENTE)
        # La demande crée lors du premier essai d'un soignant consent à la
        # trace : une seule demande EN_ATTENTE par (patient, etablissement).
        autoriser2, demande2 = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)
        self.assertFalse(autoriser2)
        self.assertEqual(demande2.pk, demande.pk)

    def test_consultation_autorisee_apres_approbation(self):
        from dmp.services import verifier_ou_demander_acces
        dem = self._creer_demande()
        dem.approuver()
        autoriser, acces = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)
        self.assertTrue(autoriser)
        self.assertTrue(acces.est_actif)

    def test_medecin_peut_creer_consultation_apres_approbation(self):
        from .views import _verifier_approbation_patient
        dem = self._creer_demande()
        dem.approuver()
        ok, erreur, _ = _verifier_approbation_patient(
            self.patient, self.etab, demandeur=self.medecin)
        self.assertTrue(ok)
        self.assertEqual(erreur, '')

    def test_medecin_bloque_sans_approbation_et_cree_demande(self):
        from .views import _verifier_approbation_patient
        ok, erreur, demande = _verifier_approbation_patient(
            self.patient, self.etab, demandeur=self.medecin)
        self.assertFalse(ok)
        self.assertIn('approbation', erreur.lower())
        self.assertEqual(demande.statut, AccesDMP.Statut.EN_ATTENTE)

    def test_coeur_approbation_consentement_patient(self):
        """Approbation patient via son vrai espace (login réel).
        Vérifie aussi l'absence de collision de pk Personnel/Patient
        (multi-table inheritance) grâce au marqueur de modèle en session."""
        from dmp.models import AccesDMP
        ac = AccesDMP.objects.create(
            patient=self.patient, etablissement=self.etab, statut='EN_ATTENTE')
        # Connexion réelle du patient (MedShareLoginView pose le marqueur
        # _auth_user_model='patient', indispensable car self.medecin (pk 1)
        # et self.patient (pk 1) partagent la même valeur numérique de pk).
        self.client.post('/', {'username': self.patient.email, 'password': 'Mdp123!'})
        self.assertNotEqual(self.client.session.get('_auth_user_model'), 'personnel')
        self.patient.refresh_from_db()  # le login régénère le jeton
        response = self.client.post(
            f'/dmp/acces/{ac.pk}/repondre/', {'decision': 'APPROUVER'})
        ac.refresh_from_db()
        self.assertRedirects(response,
            f'/compte/acces/{self.patient.jeton_acces}/')
        self.assertTrue(ac.est_actif)
class AccesDMPNotificationTest(BaseMedTest):
    """T2 (addendum 4) — le patient est notifié dès la création d'une demande
    d'accès, avec renvois limités (3) et délai de sécurité (5 min)."""

    def test_creation_demande_notifie_le_patient(self):
        from .services import verifier_ou_demander_acces
        ok, acces = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)
        self.assertFalse(ok)
        self.assertEqual(acces.statut, AccesDMP.Statut.EN_ATTENTE)
        self.assertEqual(acces.nbNotificationsEnvoyees, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.patient.email, mail.outbox[0].to)

    def test_renvois_limites_puis_bloques(self):
        from .services import verifier_ou_demander_acces
        _, acces = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)

        # Cooldown immédiat après l'envoi initial : pas de renvoi.
        acces.refresh_from_db()
        self.assertFalse(acces.peut_renvoyer_notification())

        # Le délai de 5 minutes s'écoule : renvoi autorisé (2e envoi).
        acces.dernierEnvoiNotification = timezone.now() - timedelta(minutes=6)
        acces.save(update_fields=['dernierEnvoiNotification'])
        self.assertTrue(acces.peut_renvoyer_notification())
        self.assertTrue(acces.notifier_patient())

        # 3e envoi après délai : autorisé puis max atteint (3).
        acces.refresh_from_db()
        acces.dernierEnvoiNotification = timezone.now() - timedelta(minutes=6)
        acces.save(update_fields=['dernierEnvoiNotification'])
        self.assertTrue(acces.notifier_patient())
        acces.refresh_from_db()
        self.assertEqual(acces.nbNotificationsEnvoyees, 3)
        self.assertFalse(acces.peut_renvoyer_notification())

    def test_vue_renvoi_bloquee_a_la_limite(self):
        from .services import verifier_ou_demander_acces
        _, acces = verifier_ou_demander_acces(
            self.patient, self.etab, self.medecin)
        # Limite atteinte : la vue refuse le renvoi et l'explique.
        acces.nbNotificationsEnvoyees = AccesDMP.RENVOIS_MAX
        acces.dernierEnvoiNotification = timezone.now() - timedelta(minutes=6)
        acces.save(update_fields=['nbNotificationsEnvoyees',
                                  'dernierEnvoiNotification'])
        # Connexion réelle du médecin (la vue est limitée aux rôles soignants).
        self.client.post(reverse('login'), {
            'username': self.medecin.email, 'password': 'Mdp123!'})
        r = self.client.post(reverse('renvoyer_notification_acces',
                                     args=[acces.pk]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Nombre maximal de renvois')


class MonAccesHistoriqueTest(BaseMedTest):
    """T1 (addendum 4) — le patient consulte qui a accédé à son dossier
    (lecture seule, jamais d'e-mail ni d'identifiant interne)."""

    def _creer_log_acces(self):
        from urgences.models import JournalAudit
        JournalAudit.objects.create(
            action='CONSULTATION_DMP',
            description='Accès DMP pour test',
            utilisateur=self.medecin,
            etablissement=self.etab,
            patient=self.patient)

    def test_historique_affiche_qui_quand_sans_email(self):
        self._creer_log_acces()
        self.client.post(reverse('login'), {
            'username': self.patient.email, 'password': 'Mdp123!'})
        r = self.client.get(reverse('mon_acces_historique_self'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Dupont')
        self.assertContains(r, 'Médecin')
        self.assertContains(r, 'Consultation de votre dossier')
        self.assertContains(r, 'Hôpital Central')
        # RGPD : jamais l'e-mail du soignant ni un identifiant interne.
        self.assertNotContains(r, 'med@test.com')
        self.assertNotContains(r, 'MED-01')

    def test_historique_patient_ne_voit_que_ses_propres_logs(self):
        autre_med = Personnel.objects.create_user(
            email='autre@test.com', nom='Autre', prenom='Dr',
            password='Mdp123!', matricule='MED-02', etablissement=self.etab)
        from urgences.models import JournalAudit
        JournalAudit.objects.create(
            action='CONSULTATION_DMP', utilisateur=autre_med,
            etablissement=self.etab, patient=self.patient,
            description='a')
        self.client.post(reverse('login'), {
            'username': self.patient.email, 'password': 'Mdp123!'})
        r = self.client.get(reverse('mon_acces_historique_self'))
        self.assertContains(r, 'Autre')
        self.assertNotContains(r, 'une_autre@test.com')