"""
Tests de fiabilité du moteur de reconnaissance faciale.

Vérifie que les pourcentages sont toujours corrects et sûrs :
- bornés à [0, 100] et déterministes (jamais aléatoires) ;
- un contenu identique → forte confiance, un contenu différent → sous le seuil ;
- aucune correspondance n'est jamais inventée (pas de fallback factice) ;
- tri décroissant + top 5 respectés ;
- conversions distance ⇄ confiance cohérentes avec le seuil métier (60 % ⇔ 0,40).
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from django.core.files import File
from django.test import SimpleTestCase, TestCase, override_settings

import facial_recognition as fr
from facial_recognition import (MODE_LIBELLE, MODE_RECHERCHE,
                                ServiceReconnaissanceFaciale,
                                confiance_vers_distance, distance_vers_confiance,
                                _hamming, _phash_image)


def _generer_image(chemin, largeur=64, hauteur=64, modele=1):
    """Crée une image JPEG avec un motif déterministe et contrasté."""
    from PIL import Image
    img = Image.new('L', (largeur, hauteur))
    px = img.load()
    for x in range(largeur):
        for y in range(hauteur):
            if modele == 1:
                px[x, y] = (x * 7 + y * 13) % 256
            else:
                px[x, y] = (x * 3 + y * 5 + 40) % 256
    img.save(chemin, 'JPEG')


def _ajouter_egratinures(source, dest, epais=False, assombrir=False):
    """Copie source en y dessinant des égratinures (photo 'claire mais griffée')."""
    from PIL import Image, ImageDraw
    img = Image.open(source).convert('RGB')
    if assombrir:
        img = img.point(lambda p: int(p * 0.45))
    w, h = img.size
    d = ImageDraw.Draw(img)
    nb = 14 if epais else 6
    largeur = max(1, (w // 40) if epais else (w // 120))
    for i in range(nb):
        x = w * (0.25 + (i * 0.035) % 0.5)
        y = h * (0.15 + (i * 0.05) % 0.7)
        d.line([(x, y), (x + w * 0.06, y + h * 0.12)], fill=(255, 255, 255), width=largeur)
        d.line([(x + w * 0.01, y + h * 0.02), (x + w * 0.06, y + h * 0.11)],
               fill=(180, 40, 30), width=max(1, largeur // 2))
    img.save(dest, 'JPEG', quality=90)


class TestConversionsTest(SimpleTestCase):
    def test_distance_vers_confiance_seuil_metier(self):
        self.assertEqual(distance_vers_confiance(0.40), 60.0)

    def test_distance_vers_confiance_bornes(self):
        self.assertEqual(distance_vers_confiance(0.0), 100.0)
        self.assertEqual(distance_vers_confiance(1.0), 0.0)
        self.assertEqual(distance_vers_confiance(1.4), 0.0)
        self.assertEqual(distance_vers_confiance(-0.2), 100.0)

    def test_distance_vers_confiance_arrondi(self):
        self.assertEqual(distance_vers_confiance(0.1234), 87.66)

    def test_confiance_vers_distance_inverse(self):
        self.assertEqual(confiance_vers_distance(100.0), 0.0)
        self.assertEqual(confiance_vers_distance(60.0), 0.4)
        self.assertEqual(confiance_vers_distance(0.0), 1.0)
        self.assertEqual(confiance_vers_distance(150.0), 0.0)


class TestPhashTest(SimpleTestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix='mphash_')
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.a = os.path.join(self.dossier, 'a.jpg')
        self.b = os.path.join(self.dossier, 'b.jpg')
        self.plain = os.path.join(self.dossier, 'plain.jpg')
        self.a_fin = os.path.join(self.dossier, 'a_griffes_fines.jpg')
        self.a_epais = os.path.join(self.dossier, 'a_abrasions.jpg')
        self.a_sombre = os.path.join(self.dossier, 'a_sombre.jpg')
        _generer_image(self.a, modele=1)
        _generer_image(self.b, modele=2)
        _ajouter_egratinures(self.a, self.a_fin, epais=False)
        _ajouter_egratinures(self.a, self.a_epais, epais=True)
        _ajouter_egratinures(self.a, self.a_sombre, assombrir=True)
        from PIL import Image
        Image.new('L', (64, 64), color=128).save(self.plain, 'JPEG')

    def test_determinisme(self):
        self.assertEqual(_phash_image(self.a), _phash_image(self.a))

    def test_meme_fichier_identique(self):
        ha, n = _phash_image(self.a)
        hb, m = _phash_image(self.a)
        self.assertEqual(n, m)
        self.assertEqual(_hamming(ha, hb), 0)

    def test_images_differentes_elignees(self):
        ha, n = _phash_image(self.a)
        hb, m = _phash_image(self.b)
        self.assertEqual(n, m)
        # Deux contenus différents → au moins 20 % des bits diffèrent
        self.assertGreater(_hamming(ha, hb), n * 20 // 100)

    def test_image_uniforme_refusee(self):
        with self.assertRaises(ValueError):
            _phash_image(self.plain)

    def test_egratinures_fines_alterent_peu_le_hash(self):
        """Une photo claire mais griffée reste ~identique géométriquement."""
        ha, n = _phash_image(self.a)
        hb, _ = _phash_image(self.a_fin)
        self.assertLessEqual(_hamming(ha, hb), n * 5 // 100)
        confiance = round((1 - _hamming(ha, hb) / n) * 100.0, 2)
        self.assertGreaterEqual(confiance, 95.0)

    def test_abrasions_epaisses_alterent_peu_le_hash(self):
        ha, n = _phash_image(self.a)
        hb, _ = _phash_image(self.a_epais)
        self.assertLessEqual(_hamming(ha, hb), n * 12 // 100)
        confiance = round((1 - _hamming(ha, hb) / n) * 100.0, 2)
        self.assertGreaterEqual(confiance, 88.0)

    def test_assombrissement_uniforme_quasi_invariant(self):
        """Le seuil moyen par image rend le hash quasi invariant à la luminosité."""
        ha, n = _phash_image(self.a)
        hb, _ = _phash_image(self.a_sombre)
        self.assertLessEqual(_hamming(ha, hb), n * 4 // 100)
        confiance = round((1 - _hamming(ha, hb) / n) * 100.0, 2)
        self.assertGreaterEqual(confiance, 96.0)


class TestRechercheSimuleeTest(SimpleTestCase):
    """Tests unitaires du matcher simulation (patients injectés, sans DB)."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix='msim_')
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.dut_path = os.path.join(self.dossier, 'dut.jpg')
        self.autre_path = os.path.join(self.dossier, 'autre.jpg')
        self.griffes_fines = os.path.join(self.dossier, 'dut_griffes.jpg')
        self.abrasions = os.path.join(self.dossier, 'dut_abrasions.jpg')
        self.sombre = os.path.join(self.dossier, 'dut_sombre.jpg')
        _generer_image(self.dut_path, modele=1)
        _generer_image(self.autre_path, modele=2)
        _ajouter_egratinures(self.dut_path, self.griffes_fines, epais=False)
        _ajouter_egratinures(self.dut_path, self.abrasions, epais=True)
        _ajouter_egratinures(self.dut_path, self.sombre, assombrir=True)

    def _patient(self, patient_id, photo_path, numero='PAT'):
        return {
            'patient_id': patient_id,
            'numeroPatient': f'{numero}-{patient_id:03d}',
            'nom': 'TEST',
            'prenom': f'P{patient_id}',
            'photoProfil': f'profiles/{patient_id}.jpg',
            'photo_url': f'/media/profiles/{patient_id}.jpg',
            'photo_path': photo_path,
        }

    def test_meme_photo_confiance_maximale(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [self._patient(1, self.dut_path)]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]['patient_id'], 1)
        self.assertEqual(resultats[0]['confiance'], 100.0)
        self.assertEqual(resultats[0]['distance'], 0.0)
        self.assertTrue(resultats[0]['simule'])

    def test_photo_differente_aucun_resultat(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [
            self._patient(1, self.autre_path),
            self._patient(2, self.autre_path),
            self._patient(3, self.autre_path),
        ]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertEqual(resultats, [])

    def test_melange_depasse_et_non(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [
            self._patient(1, self.autre_path),
            self._patient(2, self.dut_path),
            self._patient(3, self.autre_path),
        ]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertEqual([r['patient_id'] for r in resultats], [2])

    def test_top5_et_tri_decroissant(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [self._patient(i, self.dut_path) for i in range(1, 9)]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertLessEqual(len(resultats), svc.TOP_K)
        self.assertEqual(len(resultats), 5)
        confiances = [r['confiance'] for r in resultats]
        self.assertEqual(confiances, sorted(confiances, reverse=True))

    def test_confiance_toujours_bornee(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [self._patient(1, self.dut_path), self._patient(2, self.autre_path)]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 0.0)
        self.assertTrue(resultats)
        for r in resultats:
            self.assertGreaterEqual(r['confiance'], 0.0)
            self.assertLessEqual(r['confiance'], 100.0)

    def test_determinisme(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(self.dut_path)
        patients = [self._patient(1, self.dut_path)]
        r1 = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        r2 = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertEqual(r1, r2)

    def _confiance_scenario(self, dut_clair_chemin):
        """Scénario : photo claire du patient (propre) en DB, DUT = même photos griffée."""
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        phash, bits = _phash_image(dut_clair_chemin)
        patients = [self._patient(1, self.dut_path)]
        resultats = svc._recherche_simulee_phash(phash, bits, patients, 60.0)
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]['patient_id'], 1)
        return resultats[0]['confiance']

    def test_egratinures_fines_reconnaissance_maintenue(self):
        confiance = self._confiance_scenario(self.griffes_fines)
        self.assertGreaterEqual(confiance, 95.0)

    def test_abrasions_epaisses_reconnaissance_maintenue(self):
        confiance = self._confiance_scenario(self.abrasions)
        self.assertGreaterEqual(confiance, 88.0)

    def test_photo_obscurcie_reconnaissance_maintenue(self):
        confiance = self._confiance_scenario(self.sombre)
        self.assertGreaterEqual(confiance, 95.0)


class TestModeEtAttributsTest(SimpleTestCase):
    def test_mode_declare(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        self.assertIn(svc.mode, ('reel', 'simulation'))
        self.assertEqual(svc.mode, MODE_RECHERCHE)
        self.assertTrue(MODE_LIBELLE)

    def test_seuil_defaut(self):
        self.assertEqual(ServiceReconnaissanceFaciale.SEUIL_DEFAUT, 60.0)
        svc = ServiceReconnaissanceFaciale()
        self.assertEqual(svc.seuil_confiance, 60.0)


class TestServiceInterfacesTest(TestCase):
    """Tests d'entrées/sorties publiques du service (erreurs explicites)."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix='msvc_')
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.photo = os.path.join(self.dossier, 'photo.jpg')
        self.absente = os.path.join(self.dossier, 'absente.jpg')
        self.corrompue = os.path.join(self.dossier, 'corrompue.jpg')
        self.uniforme = os.path.join(self.dossier, 'uniforme.jpg')
        _generer_image(self.photo, modele=1)
        with open(self.corrompue, 'wb') as f:
            f.write(b'ceci n est pas une image JPEG')
        from PIL import Image
        Image.new('L', (64, 64), color=90).save(self.uniforme, 'JPEG')

    def test_photo_inexistante(self):
        svc = ServiceReconnaissanceFaciale()
        with self.assertRaises(ValueError):
            svc.rechercher_correspondance(self.absente)

    def test_photo_corrompue(self):
        svc = ServiceReconnaissanceFaciale()
        with self.assertRaises(ValueError):
            svc.rechercher_correspondance(self.corrompue)

    def test_photo_uniforme(self):
        svc = ServiceReconnaissanceFaciale()
        with self.assertRaises(ValueError):
            svc.rechercher_correspondance(self.uniforme)


class TestIntegrationPatientDB(TestCase):
    """Test de bout en bout : patient en DB avec photo de profil.

    Le moteur réel (dlib) n'est PAS déterministe vis-à-vis des images
    générées sans visage humain : ces tests forcent donc le mode simulation
    (déterministe), quelle que soit la présence de dlib dans l'environnement.
    """

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix='mint_')
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.media = tempfile.mkdtemp(prefix='mmedia_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.settings_override = override_settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        # Forcer le mode simulation pour rester déterministe (voir doc classe).
        self._force_sim_msi = mock.patch.object(fr, 'HAS_FACE_RECOGNITION', False)
        self._force_sim_mode = mock.patch.object(fr, 'MODE_RECHERCHE', 'simulation')
        self._force_sim_msi.start()
        self._force_sim_mode.start()
        self.addCleanup(self._force_sim_msi.stop)
        self.addCleanup(self._force_sim_mode.stop)

        self.photo = os.path.join(self.dossier, 'dut.jpg')
        self.autre = os.path.join(self.dossier, 'autre.jpg')
        _generer_image(self.photo, modele=1)
        _generer_image(self.autre, modele=2)

    def _creer_patient(self, numero, photo_path):
        from users.models import Patient
        patient = Patient.objects.create_user(
            email=f'{numero.lower()}@test.cm', nom='TEST', prenom=numero,
            password='Mdp123!', numeroPatient=numero,
            nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='690000000',
            lienContactUrgencePrincipal='Mère',
        )
        with open(photo_path, 'rb') as f:
            patient.photoProfil.save(f'profil_{numero}.jpg', File(f), save=True)
        return patient

    def test_meme_photo_reconnue(self):
        patient = self._creer_patient('PAT-01', self.photo)
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        resultats = svc.rechercher_correspondance(self.photo, seuil_confiance=60.0)
        ids = [r['patient_id'] for r in resultats]
        self.assertIn(patient.pk, ids)
        r = next(x for x in resultats if x['patient_id'] == patient.pk)
        self.assertGreaterEqual(r['confiance'], 95.0)
        self.assertTrue(r['simule'])

    def test_photo_differente_aucun_fabrique(self):
        self._creer_patient('PAT-02', self.photo)
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        resultats = svc.rechercher_correspondance(self.autre, seuil_confiance=60.0)
        self.assertEqual(resultats, [])

    def test_multiple_patients_top5(self):
        for i in range(1, 8):
            self._creer_patient(f'PAT-{i:02d}', self.photo)
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        resultats = svc.rechercher_correspondance(self.photo, seuil_confiance=60.0)
        self.assertLessEqual(len(resultats), svc.TOP_K)
        self.assertEqual(len(resultats), svc.TOP_K)
        confiances = [r['confiance'] for r in resultats]
        self.assertEqual(confiances, sorted(confiances, reverse=True))

    def test_aucun_patient(self):
        svc = ServiceReconnaissanceFaciale(seuil_confiance=60.0)
        resultats = svc.rechercher_correspondance(self.photo, seuil_confiance=60.0)
        self.assertEqual(resultats, [])


try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None
    _HAS_NUMPY = False


@unittest.skipUnless(fr.HAS_FACE_RECOGNITION and _HAS_NUMPY,
                     'moteur réel (dlib + numpy) requis')
class TestRechercheReelleTest(TestCase):
    """
    Tests du moteur RÉEL (dlib 128-d) : la partie rochée de
    face_recognition est simulée, la logique du service (seuil, tri, top 5,
    signature des résultats, aucun résultat inventé) est vérifiée réellement.
    """

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix='mreel_')
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.media = tempfile.mkdtemp(prefix='mmedia_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.settings_override = override_settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.photo = os.path.join(self.dossier, 'dut.jpg')
        _generer_image(self.photo, modele=1)

    def _creer_patient(self, numero, photo_path=None):
        from users.models import Patient
        patient = Patient.objects.create_user(
            email=f'{numero.lower()}@test.cm', nom='TEST', prenom=numero,
            password='Mdp123!', numeroPatient=numero,
            nomContactUrgencePrincipal='Mère',
            telephoneContactUrgencePrincipal='690000000',
            lienContactUrgencePrincipal='Mère',
        )
        with open(photo_path or self.photo, 'rb') as f:
            patient.photoProfil.save(f'profil_{numero}.jpg', File(f), save=True)
        return patient

    def _simuler(self, distance):
        """Mocke face_recognition : 1 visage, distance donnée pour tout couple."""
        image = np.zeros((120, 120, 3), dtype=np.uint8)
        vecteur = np.zeros(128)
        dist = np.array([distance], dtype=float)
        return mock.patch.object(fr.face_recognition, 'load_image_file', return_value=image), \
            mock.patch.object(fr.face_recognition, 'face_encodings', return_value=[vecteur]), \
            mock.patch.object(fr.face_recognition, 'face_distance', return_value=dist)

    def test_visage_identique_confiance_maximale_exacte(self):
        patient = self._creer_patient('PAT-REEL')
        d1, d2, d3 = self._simuler(0.0)
        with d1, d2, d3:
            resultats = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=60.0)
        self.assertEqual(len(resultats), 1)
        r = resultats[0]
        self.assertEqual(r['patient_id'], patient.pk)
        self.assertEqual(r['confiance'], 100.0)
        self.assertEqual(r['distance'], 0.0)
        self.assertFalse(r['simule'])
        self.assertEqual(r['numeroPatient'], 'PAT-REEL')

    def test_visage_pres_identique_confiance_elevee(self):
        self._creer_patient('PAT-REEL')
        d1, d2, d3 = self._simuler(0.10)
        with d1, d2, d3:
            resultats = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=60.0)
        self.assertEqual(len(resultats), 1)
        self.assertGreaterEqual(resultats[0]['confiance'], 90.0)
        self.assertLess(resultats[0]['confiance'], 100.0)

    def test_visage_different_exclu_aucun_resultat(self):
        self._creer_patient('PAT-REEL')
        d1, d2, d3 = self._simuler(0.65)
        with d1, d2, d3:
            resultats = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=60.0)
        self.assertEqual(resultats, [])

    def test_seuil_personnalise_du_cote_appelant(self):
        self._creer_patient('PAT-REEL')
        d1, d2, d3 = self._simuler(0.30)
        with d1, d2, d3:
            strict = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=80.0)
            souple = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=60.0)
        self.assertEqual(strict, [])
        self.assertEqual(len(souple), 1)

    def test_top5_trie_par_confiance_decroissante(self):
        for i in range(1, 8):
            self._creer_patient(f'PAT-{i:02d}')
        d1, d2, d3 = self._simuler(0.05)
        with d1, d2, d3:
            resultats = ServiceReconnaissanceFaciale().rechercher_correspondance(
                self.photo, seuil_confiance=60.0)
        self.assertLessEqual(len(resultats), 5)
        confiances = [r['confiance'] for r in resultats]
        self.assertEqual(confiances, sorted(confiances, reverse=True))
        self.assertTrue(all(r['simule'] is False for r in resultats))

    def test_aucun_visage_dans_la_photo_dut_erreur_explicite(self):
        self._creer_patient('PAT-REEL')
        image = np.zeros((120, 120, 3), dtype=np.uint8)
        with mock.patch.object(fr.face_recognition, 'load_image_file', return_value=image), \
                mock.patch.object(fr.face_recognition, 'face_encodings', return_value=[]):
            with self.assertRaises(ValueError):
                ServiceReconnaissanceFaciale().rechercher_correspondance(self.photo)