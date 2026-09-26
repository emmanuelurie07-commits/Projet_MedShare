"""
Backend facial ONNX (MedShare — Voie 1, déployable sur Vercel).

Pipeline :
  1. Détection de visages : YuNet (face_detection_yunet_2023mar.onnx) chargé
     via cv2.FaceDetectorYN — le décodage est à l'intérieur d'OpenCV (aucune
     logique de sorties à réinventer). Retourne pour chaque visage le score,
     la boîte englobante et les 5 points-clés (œil droit, œil gauche, nez,
     bouche droite, bouche gauche — ordre identique à ArcFace).
  2. Alignement : estimation d'une transformation de similarité (scale +
     rotation + translation, cv2.estimateAffinePartial2D) entre les 5 points
     détectés et la référence ArcFace 112x112 (insightface), puis warpAffine.
  3. Embarquement : w600k_mbf.onnx (ArcFace, poids entraînés sur Glint360K),
     entrée RGB (112,112,3) normalisée (x - 127.5) / 127.5, sortie vecteur
     512-d L2-normalisé.

Distance métier : `distance = 1 - cosinus(vecteurs normalisés)`.
`confiance = (1 - distance) * 100` ; seuil 60 % ⇔ cosinus >= 0,60
(conservateur : deux visages différents donnent typiquement cos ~ 0,1 à 0,3).

Déterminisme : le pipeline est 100 % déterministe (mêmes entrées → mêmes
embarquements). Aucun aléa.
"""

import os

try:
    import numpy as np
    import cv2
    import onnxruntime as ort
    _BIBLIOTHEQUES_OK = True
except Exception:  # pragma: no cover — dépend des bibliothèques tierces
    np = None
    cv2 = None
    ort = None
    _BIBLIOTHEQUES_OK = False

_DOSSIER_MODELS = os.path.join(os.path.dirname(__file__), 'models')
_YUNET_PATH = os.path.join(_DOSSIER_MODELS, 'face_detection_yunet_2023mar.onnx')
_ARCFACE_PATH = os.path.join(_DOSSIER_MODELS, 'w600k_mbf.onnx')

_TAILLE_ARCFACE = 112
# Ordre identique YuNet ⇄ ArcFace : œil droit, œil gauche, nez,
# bouche droite, bouche gauche (référence insightface face_align.py).
_REFERENCE = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
    [41.5493, 92.3655], [70.7299, 92.2041],
], dtype=np.float64)

_DETECTEUR = None
_SESSION_ARCFACE = None
_NOM_ENTREE_ARCFACE = None
_NOM_SORTIE_ARCFACE = None
_DISPONIBLE = None


# ── Chargement paresseux des modèles ──────────────────────────────────────
def _charger_detecteur():
    """Charge YuNet une seule fois via la factory OpenCV (décodage inclus)."""
    global _DETECTEUR
    if _DETECTEUR is None:
        _DETECTEUR = cv2.FaceDetectorYN.create(
            _YUNET_PATH, "",
            (640, 640),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000,
        )
    return _DETECTEUR


def _charger_session_arcface():
    """Charge la session onnxruntime d'ArcFace une seule fois."""
    global _SESSION_ARCFACE, _NOM_ENTREE_ARCFACE, _NOM_SORTIE_ARCFACE
    if _SESSION_ARCFACE is None:
        _SESSION_ARCFACE = ort.InferenceSession(_ARCFACE_PATH)
        _NOM_ENTREE_ARCFACE = _SESSION_ARCFACE.get_inputs()[0].name
        _NOM_SORTIE_ARCFACE = _SESSION_ARCFACE.get_outputs()[0].name
    return _SESSION_ARCFACE


def est_disponible():
    """
    True si les bibliothèques sont importables et que les deux modèles ONNX
    se chargent vraiment. Vérification faite une seule fois par processus.
    """
    global _DISPONIBLE
    if _DISPONIBLE is None:
        try:
            if not _BIBLIOTHEQUES_OK:
                _DISPONIBLE = False
            elif not (os.path.isfile(_YUNET_PATH) and os.path.isfile(_ARCFACE_PATH)):
                _DISPONIBLE = False
            else:
                _charger_detecteur()
                _charger_session_arcface()
                _DISPONIBLE = True
        except Exception:
            _DISPONIBLE = False
    return _DISPONIBLE


# ── Pipeline d'encodage ───────────────────────────────────────────────────
def _meilleur_visage(img_bgr):
    """
    Détecte les visages dans une image BGR et retourne le plus fiable :
    (score, lmk(5x2)) ou None si aucun visage.
    """
    if img_bgr is None:
        raise ValueError('Impossible de lire la photo (fichier illisible).')
    detecteur = _charger_detecteur()
    # YuNet exige que la taille d'entrée soit réglée avant CHAQUE appel.
    detecteur.setInputSize((img_bgr.shape[1], img_bgr.shape[0]))
    ok, visages = detecteur.detect(img_bgr)
    if ok is None or len(visages) == 0:
        return None
    scores = visages[:, 4]
    meilleur = visages[int(np.argmax(scores))]
    lmk = meilleur[5:].reshape(5, 2).astype(np.float64)
    return float(meilleur[4]), lmk


def _embarquer(img_bgr, lmk):
    """Aligne le visage sur la référence ArcFace puis calcule le vecteur 512-d."""
    session = _charger_session_arcface()
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    transformation, _ = cv2.estimateAffinePartial2D(lmk, _REFERENCE, method=cv2.LMEDS)
    if transformation is None:
        raise ValueError('Alignement du visage impossible.')
    aligne = cv2.warpAffine(img_rgb, transformation,
                            (_TAILLE_ARCFACE, _TAILLE_ARCFACE), borderValue=0.0)
    blob = (aligne.astype(np.float32) - 127.5) / 127.5
    blob = np.transpose(blob, (2, 0, 1))[np.newaxis, ...]
    embeddings = session.run([_NOM_SORTIE_ARCFACE], {_NOM_ENTREE_ARCFACE: blob})[0]
    norme = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norme, 1e-12)
    return embeddings[0].astype(np.float64)


def encoder_photo(photo_path):
    """
    Retourne la liste des encodages faciaux 512-d normalisés de la photo.
    - Aucun visage détecté → liste vide (même contrat que face_recognition).
    - Plusieurs visages → uniquement celui au meilleur score (parité avec
      l'usage `encodages[0]` du service).
    - Fichier illisible → ValueError explicite.
    """
    if not est_disponible():
        raise RuntimeError('Le moteur ONNX (YuNet + ArcFace) n\u2019est pas disponible.')
    img_bgr = cv2.imread(photo_path)
    return _encoder_img(img_bgr)


def encoder_octets(octets):
    """
    Variante de `encoder_photo` acceptant des octets bruts (ex. contenu
    téléchargé depuis Supabase Storage) au lieu d'un chemin disque.
    Mêmes contrats (liste vide si aucun visage, ValueError si illisible).
    """
    if not est_disponible():
        raise RuntimeError('Le moteur ONNX (YuNet + ArcFace) n\u2019est pas disponible.')
    tableau = np.frombuffer(octets, dtype=np.uint8)
    img_bgr = cv2.imdecode(tableau, cv2.IMREAD_COLOR)
    return _encoder_img(img_bgr)


def _encoder_img(img_bgr):
    """Pipeline commun : détection → alignement → embedding 512-d."""
    if img_bgr is None:
        raise ValueError('Impossible de lire la photo (fichier illisible).')
    meilleur = _meilleur_visage(img_bgr)
    if meilleur is None:
        return []
    _, lmk = meilleur
    return [_embarquer(img_bgr, lmk)]