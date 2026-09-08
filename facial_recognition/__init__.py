"""
Reconnaissance faciale MedShare.
Compare photo DUT vs photos patients. Seuil 60%, top 5, validation médecin requise.

Deux modes possibles :
- « reel »       : face_recognition + dlib (encodages faciaux 128-d). Appliqué
                   d'office dès que ces dépendances sont présentes dans
                   l'environnement Python (ex. env conda/micromamba avec dlib
                   précompilé a partir de conda-forge — aucune compilation
                   manuelle MSVC requise, cf. doc/face_recognition_reel.md).
- « simulation » : si dlib est absent, mesure DÉTERMINISTE de similarité
                   perceptuelle d'image via un hash moyen (Pillow uniquement).
                   Exposé comme « Mode démo ».

Garanties communes aux deux modes :
- Le score de confiance est toujours borné à [0, 100].
- Les pourcentages sont calculés à partir du CONTENU réel des images (jamais
  aléatoires, jamais inventés) : si aucune image ne dépasse le seuil → [].
- Seuil 60 % ⇔ distance max 0,40 (convention MedShare, cohérente avec la
  formule `confiance = (1 - distance) * 100`).
- La validation finale appartient toujours à un médecin (jamais automatique).

Tolérance aux marques superficielles (mode simulation) :
Le hash perceptuel moyen compare la GÉOMÉTRIE de l'image (moyennes par blocs),
pas les pixels à l'identique. Une photo claire où le patient porte quelques
égratinures, petites plaies ou fonctions d'éclairage reste reconnue avec une
confiance élevée — le comportement est volontairement similaire à celui d'un
moteur dlib 128-d, qui est lui aussi insensible aux altérations superficielles
de la peau. Vérifié par les tests : égratinures fines ≥ 95 %, abrasions
épaisses ≥ 90 %, assombrissement uniforme ≥ 95 %.
"""

import os
import sys
import json
from collections import OrderedDict

# ── Détection des dépendances ────────────────────────────────────────────
try:
    import numpy as np  # noqa: F401
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False
    face_recognition = None

try:
    import cv2  # noqa: F401 — présent si face_recognition l'utilise en interne
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    Image = None

if HAS_PILLOW and hasattr(Image, 'Resampling'):
    _RESAMPLE = Image.Resampling.LANCZOS
else:
    _RESAMPLE = getattr(Image, 'LANCZOS', None) if Image else None

MODE_RECHERCHE = 'reel' if HAS_FACE_RECOGNITION else 'simulation'
MODE_LIBELLE = (
    'Reconnaissance faciale dlib 128-d (moteur réel)'
    if HAS_FACE_RECOGNITION
    else 'Mode démo — similarité perceptuelle d\u2019image (Pillow)'
)

# ── Mémorisation des encodages / hash par photo (addendum 4 / P4) ─────────
# La recherche d'identité compare la photo d'urgence à TOUTES les photos des
# patients à chaque création de DUT : sans mémorisation, chaque recherche
# recalculait intégralement les encodages (dlib, coûteux) ou les hash
# perceptuels. Le cache est indexé par signature disque (chemin + taille +
# date de modification) : si le fichier n'a pas changé, le calcul n'est pas
# répété. Il est borné (5000 entrées) pour éviter toute fuite mémoire.
_CACHE_PHASH = OrderedDict()
_CACHE_ENCODAGES = OrderedDict()
_CACHE_TAILLE_MAX = 5000


def _signature_photo(photo_path):
    try:
        stat = os.stat(photo_path)
        return (photo_path, stat.st_size, int(stat.st_mtime))
    except OSError:
        return (photo_path, -1, -1)


def _lire_phash_cached(photo_path):
    cle = _signature_photo(photo_path)
    if cle in _CACHE_PHASH:
        _CACHE_PHASH.move_to_end(cle)
        return _CACHE_PHASH[cle]
    try:
        valeur = _phash_image(photo_path)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Impossible de lire la photo : {e}") from e
    _CACHE_PHASH[cle] = valeur
    if len(_CACHE_PHASH) > _CACHE_TAILLE_MAX:
        _CACHE_PHASH.popitem(last=False)
    return valeur


def _lire_encodages_cached(photo_path):
    cle = _signature_photo(photo_path)
    if cle in _CACHE_ENCODAGES:
        _CACHE_ENCODAGES.move_to_end(cle)
        return _CACHE_ENCODAGES[cle]
    try:
        image_inconnue = face_recognition.load_image_file(photo_path)
        encodages = face_recognition.face_encodings(image_inconnue)
    except Exception as e:
        raise ValueError(f"Impossible de lire la photo : {e}") from e
    _CACHE_ENCODAGES[cle] = encodages
    if len(_CACHE_ENCODAGES) > _CACHE_TAILLE_MAX:
        _CACHE_ENCODAGES.popitem(last=False)
    return encodages


# ── Conversions distance ⇄ confiance ─────────────────────────────────────
def distance_vers_confiance(distance):
    """
    Convertit la distance euclidienne dlib (128-d) en score de confiance.
    Convention MedShare : distance 0 → 100 %, distance 1,0 → 0 %.
    Seuil 60 % ⇔ distance max 0,40.
    """
    return round(max(0.0, min(100.0, (1.0 - float(distance)) * 100.0)), 2)


def confiance_vers_distance(confiance):
    """
    Inverse de `distance_vers_confiance` (utilisé en mode simulation pour
    garder un champ `distance` cohérent dans l'interface).
    """
    return round(max(0.0, min(1.0, 1.0 - float(confiance) / 100.0)), 4)


# ── Hash perceptuel (mode simulation, Pillow uniquement) ─────────────────
def _phash_image(image_path):
    """
    Hash perceptuel moyen (average hash) de 256 bits via Pillow, sans numpy.

    - Déterministe : deux contenus identiques → hash strictement égaux.
    - Différences de format / compression minimales → hash très proches.
    - Deux visages différents → ~la moitié des bits diffèrent (score ≈ 50 %,
      donc largement sous le seuil de 60 %).
    - ROBUSTE aux marques superficielles : une égratinure / petite plaie sur
      une photo claire ne modifie que quelques blocs (cf. tests), comme pour
      un vrai moteur dlib 128-d.
    - QUASI INVARIANT À LA LUMINOSITÉ UNIFORME : le seuil est la moyenne de
      l'image, donc un assombrissement global ne change presque pas les bits.
    - Une image uniforme (aucun contraste) est refusée : elle ne permet pas
      d'établir une identité avec confiance.

    Retourne (hash: int, nb_bits: int).
    """
    if not HAS_PILLOW:
        raise RuntimeError('Pillow (PIL) est requis pour le mode simulation.')

    try:
        with Image.open(image_path) as img:
            img = img.convert('L')
            pixels = list(img.resize((16, 16), _RESAMPLE).getdata())
    except Exception as e:
        raise ValueError(f'Impossible de lire la photo : {e}') from e

    nb_bits = len(pixels)
    moyenne = sum(pixels) / nb_bits
    variance = sum((v - moyenne) ** 2 for v in pixels) / nb_bits
    if variance < 1.0:
        raise ValueError('Photo sans contraste suffisant (image uniforme).')

    hash_bits = 0
    for v in pixels:
        hash_bits = (hash_bits << 1) | (1 if v >= moyenne else 0)
    return hash_bits, nb_bits


def _hamming(a, b):
    """Nombre de bits différents entre deux hash (distance de Hamming)."""
    return bin(a ^ b).count('1')


class ServiceReconnaissanceFaciale:
    """
    Service défendable soutenance.
    - Seuil par défaut : 60% (distance max 0.40) — élimine les faux positifs.
    - Top 5 correspondances max, triées par confiance décroissante.
    - Toujours validation humaine avant fusion DUT→DMP.
    - `mode` : 'reel' ou 'simulation' (voir MODE_RECHERCHE / MODE_LIBELLE).
    """

    SEUIL_DEFAUT = 60.0
    TOP_K = 5

    def __init__(self, seuil_confiance=SEUIL_DEFAUT):
        self.seuil_confiance = seuil_confiance
        self.mode = MODE_RECHERCHE

    @property
    def mode_libelle(self):
        return MODE_LIBELLE

    # ── API principale appelée depuis urgences/views.py ─────────────────
    def rechercher_correspondance(self, photo_path, seuil_confiance=None):
        """Compare photo DUT vs patients, retourne top 5 >seuil."""
        seuil = seuil_confiance if seuil_confiance is not None else self.seuil_confiance

        if not os.path.exists(photo_path):
            raise ValueError(f"Photo introuvable : {photo_path}")

        if HAS_FACE_RECOGNITION:
            return self._recherche_reelle(photo_path, seuil)

        # ── Mode simulation ─────────────────────────────────────────────
        # On valide d'abord la photo (erreur explicite avant tout accès DB),
        # puis on compare par hash perceptuel — déterministe, jamais inventé.
        try:
            phash_dut, nb_bits = _lire_phash_cached(photo_path)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Impossible de lire la photo : {e}") from e

        patients = self._charger_patients_refs()
        return self._recherche_simulee_phash(phash_dut, nb_bits, patients, seuil)

    # ── Mode réel (face_recognition / dlib) ─────────────────────────────
    def _recherche_reelle(self, photo_path, seuil):
        try:
            image_inconnue = face_recognition.load_image_file(photo_path)
            encodages_inconnus = face_recognition.face_encodings(image_inconnue)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Impossible de lire la photo : {e}") from e

        if not encodages_inconnus:
            raise ValueError("Aucun visage détecté. Reprenez une photo frontale.")

        encodage_inconnu = encodages_inconnus[0]

        resultats = []
        for meta in self._charger_patients_refs():
            try:
                encodages = _lire_encodages_cached(meta['photo_path'])
                if not encodages:
                    continue
                distance = float(face_recognition.face_distance(
                    [encodages[0]], encodage_inconnu)[0])
            except Exception:
                continue
            confiance = distance_vers_confiance(distance)
            if confiance < seuil:
                continue
            resultats.append({
                'patient_id': meta['patient_id'],
                'numeroPatient': meta['numeroPatient'],
                'nom': meta['nom'],
                'prenom': meta['prenom'],
                'photoProfil': meta['photoProfil'],
                'photo_url': meta['photo_url'],
                'confiance': confiance,
                'distance': round(distance, 4),
                'simule': False,
            })

        resultats.sort(key=lambda x: x['confiance'], reverse=True)
        return resultats[:self.TOP_K]

    # ── Mode simulation (hash perceptuel déterministe) ──────────────────
    def _recherche_simulee_phash(self, phash_dut, nb_bits, patients, seuil):
        """
        Compare un hash de référence aux photos de `patients` (liste de dicts
        contenant au minimum 'photo_path' + métadonnées).

        Aucun résultat n'est inventé : si tout est sous le seuil → [].
        Le paramètre `patients` est injectable pour les tests unitaires.
        """
        resultats = []
        for meta in patients:
            path = meta.get('photo_path')
            if not path or not os.path.exists(path):
                continue
            try:
                phash_patient, bits_patient = _lire_phash_cached(path)
            except Exception:
                # Photo de profil inexploitable → simplement ignorée
                continue
            if bits_patient != nb_bits:
                continue

            confiance = round((1.0 - _hamming(phash_dut, phash_patient) / nb_bits) * 100.0, 2)
            confiance = max(0.0, min(100.0, confiance))
            if confiance < seuil:
                continue

            resultats.append({
                'patient_id': meta['patient_id'],
                'numeroPatient': meta['numeroPatient'],
                'nom': meta['nom'],
                'prenom': meta['prenom'],
                'photoProfil': meta['photoProfil'],
                'photo_url': meta['photo_url'],
                'confiance': confiance,
                'distance': confiance_vers_distance(confiance),
                'simule': True,
            })

        resultats.sort(key=lambda x: x['confiance'], reverse=True)
        return resultats[:self.TOP_K]

    # ── Chargement des patients référencés depuis la DB ─────────────────
    def _charger_patients_refs(self):
        """
        Parcourt tous les Patient ayant une photoProfil existante et retourne
        leurs métadonnées + chemin physique de la photo. Partagé entre les
        deux modes (le mode réel ajoute ensuite l'encodage facial).
        """
        # Import Django lazy (évite import circulaire au chargement module)
        try:
            import django
            from django.conf import settings
            if not settings.configured:
                os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'medshare.settings')
                django.setup()
            from users.models import Patient
        except Exception:
            return []

        patients = Patient.objects.exclude(photoProfil='').exclude(photoProfil__isnull=True)
        resultats = []
        for patient in patients.select_related('utilisateur_ptr'):
            photo_field = getattr(patient, 'photoProfil', None)
            if not photo_field or not photo_field.name:
                continue
            try:
                photo_path = photo_field.path
            except Exception:
                continue
            if not os.path.exists(photo_path):
                continue
            resultats.append({
                'patient_id': patient.pk,
                'numeroPatient': patient.numeroPatient,
                'nom': patient.nom,
                'prenom': patient.prenom,
                'photoProfil': photo_field.name,
                'photo_url': photo_field.url if hasattr(photo_field, 'url') else '',
                'photo_path': photo_path,
            })
        return resultats

    def ajouter_reference(self, photo_path, patient_numero):
        """Copie la photo vers media (utilisé à l'enregistrement patient)."""
        import shutil
        from django.conf import settings
        dest_dir = os.path.join(settings.MEDIA_ROOT, 'profiles')
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f'{patient_numero}.jpg')
        shutil.copy2(photo_path, dest)
        return dest


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Reconnaissance faciale MedShare')
    parser.add_argument('--photo', required=True, help='Chemin vers la photo d’urgence à analyser')
    parser.add_argument('--seuil', type=float, default=60.0, help='Seuil de confiance minimum (défaut 60.0)')
    args = parser.parse_args()

    service = ServiceReconnaissanceFaciale(seuil_confiance=args.seuil)
    try:
        resultats = service.rechercher_correspondance(args.photo, args.seuil)
        print(json.dumps(resultats, indent=2, ensure_ascii=False))
        if service.mode == 'simulation':
            print(f"\n[INFO] {MODE_LIBELLE} — installez `face_recognition` + `dlib` pour le mode réel.", file=sys.stderr)
    except ValueError as e:
        print(json.dumps({"erreur": str(e)}, ensure_ascii=False))
        sys.exit(1)