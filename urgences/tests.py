from django.test import TestCase

from dmp.models import DossierMedicalPartage
from establishments.models import Etablissement
from users.models import Patient, Personnel, Role

from .models import (Constante, DossierUrgenceTemporaire, RechercheIdentite,
                      ServiceReconnaissanceFaciale, Triage)


class UrgenceTest(TestCase):
    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        role_inf = Role.objects.create(nomRole='Infirmier')
        role_med = Role.objects.create(nomRole='Médecin')
        self.infirmier = Personnel.objects.create_user(
            email='inf@test.com', nom='Inf', prenom='Jean',
            password='Mdp123!', matricule='INF-01', etablissement=self.etab)
        self.infirmier.role = role_inf
        self.infirmier.save()

        # DUT pour patient inconnu
        self.dut = DossierUrgenceTemporaire.objects.create(
            etablissement=self.etab, infirmier=self.infirmier,
            numeroDUT='DUT-01',
            informationsInitiales='Homme, ~40 ans, chemise bleue')


class DUTCreationTest(UrgenceTest):
    def test_creation_dut(self):
        self.assertEqual(self.dut.statut, 'ACTIF')
        self.assertEqual(self.dut.infirmier, self.infirmier)
        self.assertEqual(self.dut.identiteConfirmee, False)
        self.assertEqual(self.dut.dmpRattache, None)

    def test_cloturer_dut(self):
        self.dut.cloturer()
        self.dut.refresh_from_db()
        self.assertEqual(self.dut.statut, 'INACTIF')
        self.assertIsNotNone(self.dut.dateCloture)


class TriageTest(UrgenceTest):
    def test_creation_triage(self):
        triage = Triage.objects.create(
            dut=self.dut, etablissement=self.etab,
            priorite='ORANGE', motifArrivee='Douleur thoracique')
        self.assertEqual(triage.priorite, 'ORANGE')
        self.assertEqual(triage.dut, self.dut)
        self.assertEqual(str(triage), f"Triage DUT-01 — ORANGE")

    def test_un_seul_triage_par_dut(self):
        Triage.objects.create(
            dut=self.dut, etablissement=self.etab,
            priorite='JAUNE', motifArrivee='Test')
        with self.assertRaises(Exception):
            Triage.objects.create(
                dut=self.dut, etablissement=self.etab,
                priorite='VERT', motifArrivee='Test 2')

    def test_modifier_triage(self):
        triage = Triage.objects.create(
            dut=self.dut, etablissement=self.etab,
            priorite='ROUGE', motifArrivee='Arrêt cardiaque')
        triage.modifier(priorite='ORANGE')
        triage.refresh_from_db()
        self.assertEqual(triage.priorite, 'ORANGE')


class ConstanteTest(UrgenceTest):
    def test_creation_constante(self):
        c = Constante.objects.create(
            dut=self.dut, etablissement=self.etab,
            frequenceCardiaque=80, tensionArterielle='12/8',
            temperature=37.5, saturationOxygene=98, poids=70.0)
        self.assertEqual(c.frequenceCardiaque, 80)
        self.assertEqual(c.temperature, 37.5)

    def test_plusieurs_constantes(self):
        Constante.objects.create(dut=self.dut, etablissement=self.etab, temperature=37.0)
        Constante.objects.create(dut=self.dut, etablissement=self.etab, temperature=36.8)
        self.assertEqual(self.dut.constantes.count(), 2)


class ServiceReconnaissanceTest(UrgenceTest):
    def test_creation_service(self):
        service = ServiceReconnaissanceFaciale.objects.create(
            nom='ReconnaissanceFaciale', urlEndpoint='http://localhost:8001/api/match')
        self.assertEqual(str(service), 'ReconnaissanceFaciale')

    def test_recherche_correspondance_simulee(self):
        service = ServiceReconnaissanceFaciale.objects.create(nom='TestService')
        resultats = service.rechercher_correspondance('/chemin/inexistant.jpg')
        self.assertIsInstance(resultats, list)


class RechercheIdentiteTest(UrgenceTest):
    def setUp(self):
        super().setUp()
        self.service = ServiceReconnaissanceFaciale.objects.create(nom='TestService')
        self.recherche = RechercheIdentite.objects.create(
            dut=self.dut, etablissement=self.etab, service=self.service,
            statut='EN_RECHERCHE')
        self.patient = Patient.objects.create_user(
            email='pat@test.com', nom='Patient', prenom='X',
            password='Mdp123!', numeroPatient='PAT-99',
            nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='690000000',
            lienContactUrgencePrincipal='Mère')
        self.dmp = DossierMedicalPartage.objects.create(
            patient=self.patient, numeroDMP='DMP-99')

    def test_creation_recherche(self):
        self.assertEqual(self.recherche.statut, 'EN_RECHERCHE')
        self.assertEqual(self.recherche.patientCorrespondant, None)

    def test_confirmer_et_fusionner(self):
        """Valider l'identité déclenche la fusion DUT → DMP."""
        self.recherche.patientCorrespondant = self.patient
        self.recherche.confirmePar = self.infirmier
        self.recherche.statut = 'CONFIRMEE'
        self.recherche.save()

        self.dut.fusionner_avec_dmp(self.dmp)
        self.dut.refresh_from_db()
        self.recherche.refresh_from_db()

        self.assertEqual(self.dut.dmpRattache, self.dmp)
        self.assertEqual(self.dut.identiteConfirmee, True)
        self.assertEqual(self.dut.statut, 'FUSIONNE')
        self.assertIsNotNone(self.dut.dateFusion)


class TestImportModeles(TestCase):
    def test_modules_chargent(self):
        """Vérifie que tous les modèles urgentes sont importables."""
        from .models import (Constante, DossierUrgenceTemporaire,
                              JournalAudit, RechercheIdentite,
                              ServiceReconnaissanceFaciale, Triage)
        self.assertIsNotNone(DossierUrgenceTemporaire)
        self.assertIsNotNone(Triage)
        self.assertIsNotNone(Constante)
        self.assertIsNotNone(JournalAudit)
        self.assertIsNotNone(RechercheIdentite)
        self.assertIsNotNone(ServiceReconnaissanceFaciale)
from datetime import timedelta

from django.utils import timezone


class PolitiqueClotureDUTTest(TestCase):
    """T3 (addendum 4) — politique de clôture : EN_ATTENTE_PROLONGEE après
    72 h sans correspondance validée, JAMAIS de clôture automatique, clôture
    définitive manuelle par le médecin avec motif."""

    def setUp(self):
        self.etab = Etablissement.objects.create(
            nom='Hôpital', adresse='A', telephone='69', email='h@h.cm')
        role_med = Role.objects.create(nomRole='Médecin')
        role_inf = Role.objects.create(nomRole='Infirmier')
        self.medecin = Personnel.objects.create_user(
            email='med3@test.com', nom='Doc', prenom='Jane',
            password='Mdp123!', matricule='MED-03', etablissement=self.etab)
        self.medecin.role = role_med
        self.medecin.save()
        self.infirmier = Personnel.objects.create_user(
            email='inf3@test.com', nom='Inf', prenom='Sara',
            password='Mdp123!', matricule='INF-03', etablissement=self.etab)
        self.infirmier.role = role_inf
        self.infirmier.save()
        self.dut_ancien = DossierUrgenceTemporaire.objects.create(
            etablissement=self.etab, infirmier=self.infirmier,
            numeroDUT='DUT-OLD', informationsInitiales='Patient vague')
        DossierUrgenceTemporaire.objects.filter(pk=self.dut_ancien.pk).update(
            dateCreation=timezone.now() - timedelta(hours=73))
        self.dut_recent = DossierUrgenceTemporaire.objects.create(
            etablissement=self.etab, infirmier=self.infirmier,
            numeroDUT='DUT-NEW', informationsInitiales='Patient récent')

    def test_bascule_en_attente_prolongee_apres_72h(self):
        from .models import JournalAudit
        from .services import appliquer_politique_cloture_dut
        nb = appliquer_politique_cloture_dut()
        self.assertEqual(nb, 1)
        self.dut_ancien.refresh_from_db()
        self.assertEqual(self.dut_ancien.statut, 'EN_ATTENTE_PROLONGEE')
        self.assertTrue(JournalAudit.objects.filter(
            action='DUT_EN_ATTENTE_PROLONGEE').exists())

    def test_pas_de_bascule_avec_correspondance_confirmee(self):
        from .services import appliquer_politique_cloture_dut
        service = ServiceReconnaissanceFaciale.objects.create(nom='SRV-T3')
        RechercheIdentite.objects.create(
            dut=self.dut_ancien, etablissement=self.etab, service=service,
            statut='CONFIRMEE')
        nb = appliquer_politique_cloture_dut()
        self.assertEqual(nb, 0)
        self.dut_ancien.refresh_from_db()
        self.assertEqual(self.dut_ancien.statut, 'ACTIF')

    def test_dut_recent_ignore(self):
        from .services import appliquer_politique_cloture_dut
        nb = appliquer_politique_cloture_dut()
        self.assertEqual(nb, 1)
        self.dut_recent.refresh_from_db()
        self.assertEqual(self.dut_recent.statut, 'ACTIF')

    def test_jamais_de_cloture_automatique(self):
        from .services import appliquer_politique_cloture_dut
        appliquer_politique_cloture_dut()
        self.assertFalse(DossierUrgenceTemporaire.objects.filter(
            statut='INACTIF').exists())

    def test_cloture_manuelle_avec_motif(self):
        self.dut_ancien.cloturer(motif='Sortie du patient')
        self.dut_ancien.refresh_from_db()
        self.assertEqual(self.dut_ancien.statut, 'INACTIF')
        self.assertIsNotNone(self.dut_ancien.dateCloture)