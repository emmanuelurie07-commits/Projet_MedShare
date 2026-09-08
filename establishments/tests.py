from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from .models import Abonnement, Candidature, Etablissement, Formule


class EtablissementTest(TestCase):
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='Adresse', telephone='690000000',
            email='contact@hc.cm')

    def test_statut_par_defaut(self):
        self.assertEqual(self.etab.statut, 'ACTIF')

    def test_valider_et_suspendre(self):
        self.etab.suspendre()
        self.assertEqual(self.etab.statut, 'SUSPENDU')
        self.etab.valider()
        self.assertEqual(self.etab.statut, 'ACTIF')

    def test_modifier_informations(self):
        self.etab.modifier_informations(nom='Nouveau Nom')
        self.etab.refresh_from_db()
        self.assertEqual(self.etab.nom, 'Nouveau Nom')


class CandidatureTest(TestCase):
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital Central', adresse='Adresse', telephone='690000000',
            email='contact@hc.cm')
        self.candidature = Candidature.objects.create(
            nom='Dupont', prenom='Jean', email='jean@example.com',
            etablissement=self.etab, roleDemande='Médecin')

    def test_statut_initial(self):
        self.assertEqual(self.candidature.statut, Candidature.Statut.EN_ATTENTE)

    def test_pas_de_lien_utilisateur(self):
        """Le candidat n'a pas de compte utilisateur — seulement des champs texte."""
        self.assertEqual(self.candidature.email, 'jean@example.com')
        self.assertEqual(self.candidature.nom, 'Dupont')
        # Il ne doit pas y avoir de FK vers un Utilisateur
        self.assertFalse(hasattr(self.candidature, 'user'))

    def test_accepter(self):
        self.candidature.accepter()
        self.candidature.refresh_from_db()
        self.assertEqual(self.candidature.statut, Candidature.Statut.ACCEPTEE)
        self.assertIsNotNone(self.candidature.dateDecision)

    def test_refuser_avec_motif(self):
        self.candidature.refuser('Profil ne correspond pas')
        self.candidature.refresh_from_db()
        self.assertEqual(self.candidature.statut, Candidature.Statut.REFUSEE)
        self.assertEqual(self.candidature.motifRefus, 'Profil ne correspond pas')

    def test_annuler(self):
        self.candidature.annuler()
        self.candidature.refresh_from_db()
        self.assertEqual(self.candidature.statut, Candidature.Statut.REFUSEE)
        self.assertEqual(self.candidature.motifRefus, 'Candidature annulée par le candidat')


class FormuleAbonnementTest(TestCase):
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        self.formule = Formule.objects.create(
            nom='Essentiel', prix=50000, dureeMois=6,
            nbUtilisateursMax=10, nbDMPMax=200)

    def test_creation_formule(self):
        self.assertEqual(self.formule.dureeMois, 6)
        self.assertEqual(str(self.formule), 'Essentiel — 50000 FCFA / 6 mois')

    def test_relation_formule_abonnement(self):
        abonnement = Abonnement.objects.create(
            etablissement=self.etab, formule=self.formule,
            dateDebut=timezone.now().date(),
            dateFin=timezone.now().date() + timedelta(days=180))
        self.assertEqual(abonnement.formule, self.formule)
        self.assertEqual(self.formule.abonnements.first(), abonnement)

    def test_activer_suspendre(self):
        abonnement = Abonnement.objects.create(
            etablissement=self.etab, formule=self.formule,
            dateDebut=timezone.now().date(),
            dateFin=timezone.now().date() + timedelta(days=180))
        abonnement.suspendre()
        self.assertEqual(abonnement.statut, Abonnement.Statut.SUSPENDU)
        abonnement.activer()
        self.assertEqual(abonnement.statut, Abonnement.Statut.ACTIF)

    def test_simuler_paiement(self):
        abonnement = Abonnement.objects.create(
            etablissement=self.etab, formule=self.formule,
            dateDebut=timezone.now().date(),
            dateFin=timezone.now().date() + timedelta(days=180))
        abonnement.suspendre()
        abonnement.simuler_paiement()
        self.assertEqual(abonnement.statut, Abonnement.Statut.ACTIF)
        self.assertIsNotNone(abonnement.datePaiement)

    def test_un_seul_abonnement_par_etablissement(self):
        Abonnement.objects.create(
            etablissement=self.etab, formule=self.formule,
            dateDebut=timezone.now().date(),
            dateFin=timezone.now().date() + timedelta(days=180))
        with self.assertRaises(Exception):
            Abonnement.objects.create(
                etablissement=self.etab, formule=self.formule,
                dateDebut=timezone.now().date(),
                dateFin=timezone.now().date() + timedelta(days=365))