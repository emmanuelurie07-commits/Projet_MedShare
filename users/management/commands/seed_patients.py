"""
Management command : seed_patients

Crée 100 comptes patients fictifs (à partir du jeu de données FairFace) et
les rattache par tirage aléatoire aux établissements EXISTANTS « Hôpital A »
et « Hôpital B » (présents en base — aucune création).

Sélection (50 noires + 50 blanches, chaque race au mieux moitié hommes /
femmes, soit 25 + 25 + 25 + 25 = 100) :
  • source par défaut « hf »     : API Hugging Face (Datasets Server) sur
    HuggingFaceM4/FairFace (config 0.25, split validation). Les lignes sont
    lues à la demande par lots de 100 (pas de parquet complet à
    télécharger) : images + labels (age, gender, race) extraits en
    correspondance ligne par ligne, puis mis en cache local dans
    data/fairface_hf/ (labels.csv). Les lancements suivants sont instantanés
    et fonctionnent même hors ligne.
  • source « csv » (repli)       : dossier local contenant
    fairface_label_val.csv + val/ (--fairface-dir).

Photos copiées physiquement dans media/patients_avatars/.

Répartition : chaque patient est attribué ALEATOIREMENT à « Hôpital A » ou
« Hôpital B » (établissements existants) — les deux races sont forcément
mélangées DANS chaque hôpital et le total n'est pas figé à 50/50.

Si le dataset fournit moins d'images que le quota, ajoutez --tolere-partiel
pour créer le maximum disponible (moins de 100 patients) au lieu d'échouer.

Usage :
    python manage.py seed_patients
    python manage.py seed_patients --source csv --fairface-dir "chemin/vers/fairface"

Options utiles :
    --source {hf,csv}           origine des photos, défaut « hf »
    --fairface-dir PATH         dossier local (utile seulement avec --source csv)
    --quota-par-groupe N        nombre de patients par (race × sexe), défaut 25
    --mot-de-passe MDP          mot de passe commun, défaut « Patient@2026! »
    --only-new                  ne pas ré-écrire le CSV s'il existe déjà (avance rapide)
    --dry-run                   sélection + identités, sans toucher à la base

Le fichier identifiants_patients.csv est écrit à la racine du projet
(délimiteur « ; » compatible Excel, encodage UTF-8 avec BOM).
"""
import csv
import io
import os
import random
import shutil
import time
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# ── Paramètres du jeu FairFace ──────────────────────────────────────────────
# Colonnes attendues dans fairface_label_val.csv (dataset officiel).
COLONNES = {
    'file': 'file',
    'gender': 'gender',
    'race': 'race',
}
RACES_A_TIRER = ('Black', 'White')
SEXES_CSV = {'Male': 'M', 'Female': 'F'}

# ── Paramètres de la source Hugging Face (HuggingFaceM4/FairFace) ─────────
ENSEMBLE_HF = 'HuggingFaceM4/FairFace'
CONFIG_HF = '0.25'  # sous-ensemble par défaut (deux disponibles : 0.25 / 1.25)
SPLIT_HF = 'validation'
# Indices officiels du dataset (vérifiés sur la fiche du jeu de données) :
#   race : 0 East Asian, 1 Indian, 2 Black, 3 White, 4 Middle Eastern,
#          5 Latino_Hispanic, 6 Southeast Asian
RACE_HF = {
    0: 'East Asian', 1: 'Indian', 2: 'Black', 3: 'White',
    4: 'Middle Eastern', 5: 'Latino_Hispanic', 6: 'Southeast Asian',
}
GENRE_HF = {0: 'M', 1: 'F'}  # 0 = homme, 1 = femme
# Tranches d'âge liées à l'indice `age` (0 → « 0-2 », … 8 → « more than 70 »),
# utilisées pour déduire une date de naissance réaliste.
TRANCHE_AGE_HF = [
    (0, 2), (3, 9), (10, 19), (20, 29), (30, 39),
    (40, 49), (50, 59), (60, 69), (70, 95),
]

# ── Qualité des photos de profil (reconnaissance faciale) ────────────────
# Les photos de profil MedShare doivent être : frontales (un seul visage),
# bien éclairées et nettes — cf. consigne « Photo frontale, bien éclairée ».
# Le seed normalise chaque image (détection du visage → recadrage centré →
# agrandissement carré) et rejette les fichiers inexploitables.
TAILLE_PHOTO = 512          # photo de profil carrée 512×512
LUMINOSITE_MIN = 45         # image « éclairée » : refus sous cette moyenne
VARIANCE_MIN = 500          # refus des images uniformes (aucun contraste)

try:
    import face_recognition  # noqa: F401
    _FACE_RECOGNITION_OK = True
except ImportError:
    _FACE_RECOGNITION_OK = False


def _normaliser_photo_hf(contenu, taille=TAILLE_PHOTO):
    """Valide et normalise une photo pour la reconnaissance faciale.

    Consigne MedShare : « Photo frontale, bien éclairée » — un visage unique,
    exploitable par dlib. Chaque photo doit DÉCLENCHER un encodage facial :
    le seed teste toujours l'image avec `face_recognition` et rejette
    (ValueError) les fichiers inexploitables (visage absent, trop sombre,
    image uniforme) — l'appelant passe alors à l'image suivante.

    Si l'agrandissement carré à `taille`×`taille` reste exploitable, on le
    conserve (uniformité d'affichage) ; sinon on garde la photo native
    (un crop FairFace 224 rend bien aux tailles d'avatar MedShare ≤ 96 px).

    Sans dlib/face_recognition (ex. Render en mode simulation), on applique
    une validation Pillow seule (contrôles luminosité/contraste + carré).
    """
    from PIL import Image
    if not _FACE_RECOGNITION_OK:
        return _normaliser_photo_pil_seule(contenu, taille)

    image = Image.open(io.BytesIO(contenu)).convert('RGB')
    gris = image.convert('L')
    pixels = list(gris.getdata())
    moyenne = sum(pixels) / len(pixels)
    variance = sum((p - moyenne) ** 2 for p in pixels) / len(pixels)
    if moyenne < LUMINOSITE_MIN:
        raise ValueError(f'photo trop sombre (luminosité {moyenne:.0f})')
    if variance < VARIANCE_MIN:
        raise ValueError('photo sans contraste suffisant (image uniforme)')
    if not _encodage_facial_ok(image):
        raise ValueError('visage inexploitable pour la reconnaissance faciale')

    resample = (Image.Resampling.LANCZOS
                if hasattr(Image, 'Resampling') else Image.LANCZOS)
    carre = _cadrer_carre(image).resize((taille, taille), resample)
    if _encodage_facial_ok(carre):
        sortie = io.BytesIO()
        carre.save(sortie, 'JPEG', quality=92)
        return sortie.getvalue()
    sortie = io.BytesIO()
    image.save(sortie, 'JPEG', quality=90)
    return sortie.getvalue()


def _encodage_facial_ok(image):
    """True si dlib parvient à produire un encodage (photo utilisable)."""
    import numpy as np
    tableau = np.array(image)
    try:
        return bool(face_recognition.face_encodings(tableau))
    except Exception:
        return False


def _cadrer_carre(image):
    cote = min(image.width, image.height)
    gauche = (image.width - cote) // 2
    haut = (image.height - cote) // 2
    return image.crop((gauche, haut, gauche + cote, haut + cote))


def _normaliser_photo_pil_seule(contenu, taille=TAILLE_PHOTO):
    """Repli sans dlib : carré `taille`×`taille` + contrôle luminosité/contraste."""
    from PIL import Image
    image = Image.open(io.BytesIO(contenu)).convert('RGB')
    gris = image.convert('L')
    pixels = list(gris.getdata())
    moyenne = sum(pixels) / len(pixels)
    variance = sum((p - moyenne) ** 2 for p in pixels) / len(pixels)
    if moyenne < LUMINOSITE_MIN:
        raise ValueError(f'photo trop sombre (luminosité {moyenne:.0f})')
    if variance < VARIANCE_MIN:
        raise ValueError('photo sans contraste suffisant (image uniforme)')
    resample = (Image.Resampling.LANCZOS
                if hasattr(Image, 'Resampling') else Image.LANCZOS)
    largeur, hauteur = image.size
    cote = min(largeur, hauteur)
    gauche = (largeur - cote) // 2
    haut = (hauteur - cote) // 2
    carre = image.crop((gauche, haut, gauche + cote, haut + cote))
    carre = carre.resize((taille, taille), resample)
    sortie = io.BytesIO()
    carre.save(sortie, 'JPEG', quality=92)
    return sortie.getvalue()

# ── Paramètres métier MedShare ─────────────────────────────────────────────
DOSSIER_AVATARS = 'patients_avatars'
# Établissements déjà présents en base (« Hôpital A » / « Hôpital B »).
# Le matching se fait sans tenir compte ni des accents ni de la casse
# (la base peut contenir « Hopital A » comme « Hôpital A »).
NOMS_HOPITAUX = ['Hôpital A', 'Hôpital B']
GROUPES_SANGUINS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']


class Command(BaseCommand):
    help = 'Crée des patients fictifs (FairFace) rattachés à « Hôpital A » ou « Hôpital B ».'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, choices=['hf', 'csv'], default='hf',
                            help='Origine des photos : « hf » (API Hugging Face, défaut) '
                                 'ou « csv » (dossier local sectorisé).')
        parser.add_argument('--fairface-dir', type=str, default=None,
                            help='Dossier contenant fairface_label_val.csv et val/ '
                                 '(uniquement avec --source csv).')
        parser.add_argument('--quota-par-groupe', type=int, default=25,
                            help='Nb de patients par (race × sexe). Défaut 25 → 100 au total.')
        parser.add_argument('--mot-de-passe', type=str, default='Patient@2026!',
                            help='Mot de passe commun des comptes créés.')
        parser.add_argument('--graine', type=int, default=2026,
                            help='Graine aléatoire Faker (reproductibilité).')
        parser.add_argument('--doit-changer-mdp', action='store_true',
                            help='Forcer le changement de mot de passe à la 1re connexion '
                                 '(défaut : comptes seed directement utilisables).')
        parser.add_argument('--tolere-partiel', action='store_true',
                            help='Ne pas échouer si le dataset contient moins d\'images '
                                 'que le quota : on crée le maximum disponible puis on prévient.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Sélectionne les images et génère les identités, sans écrire en base.')
        parser.add_argument('--only-new', action='store_true',
                            help='N\'écrit pas le CSV s\'il existe déjà (avance rapide).')
        parser.add_argument('--rafraichir-photos', action='store_true',
                            help='Recopie les photos normalisées du cache sur les avatars '
                                 'existants (mêmes noms) sans recréer les comptes. '
                                 'Réservé à --source hf.')

    # ──────────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        from establishments.models import Etablissement
        from users.models import Patient

        quota = options['quota_par_groupe']
        if quota < 1:
            raise CommandError('--quota-par-groupe doit être ≥ 1.')
        total_vise = quota * len(RACES_A_TIRER) * 2  # races × sexes
        mot_de_passe = options['mot_de_passe']

        if options['source'] == 'hf':
            selections = self._selectionner_hf(quota, options['tolere_partiel'])
        else:
            if options['rafraichir_photos']:
                raise CommandError('--rafraichir-photos est réservé à --source hf.')
            dossier_fairface = self._localiser_fairface(options['fairface_dir'])
            selections = self._selectionner_images(dossier_fairface, quota,
                                                   options['tolere_partiel'])

        dest_avatars = Path(settings.MEDIA_ROOT) / DOSSIER_AVATARS
        dest_avatars.mkdir(parents=True, exist_ok=True)

        hopitaux = self._resoudre_hopitaux() if not options['dry_run'] else []
        # Répartition HOPITAL : tirage aléatoire indépendant (graine+1) pour un
        # mélange des races DANS chaque hôpital et un total non figé à 50/50.
        rand_hopital = random.Random(options['graine'] + 1)

        faker = self._fabriquer_faker(options['graine'])
        emails_utilises = {e.lower() for e in Patient.objects.values_list('email', flat=True)}

        lignes_csv = []
        crees, existants = 0, 0

        for race, sexe_sexe, age_index, src_image in selections:
            hopital = rand_hopital.choice(hopitaux) if not options['dry_run'] else None
            nom_image = src_image.name
            photo_relative = f'{DOSSIER_AVATARS}/{nom_image}'

            age_min, age_max = 18, 80
            if age_index is not None and 0 <= age_index < len(TRANCHE_AGE_HF):
                age_min, age_max = TRANCHE_AGE_HF[age_index]
            if age_max < age_min:
                age_max = age_min

            email = self._email_unique(faker, emails_utilises)
            identite = {
                'email': email,
                'nom': faker.last_name(),
                'prenom': faker.first_name_male() if sexe_sexe == 'M' else faker.first_name_female(),
                'dateNaissance': faker.date_of_birth(minimum_age=age_min,
                                                     maximum_age=max(age_max, age_min)),
                'sexe': sexe_sexe,
                'adresse': ' '.join(faker.address().split('\n')),
                'numeroCNI': faker.numerify('################')[:14],
                'groupeSanguin': faker.random_element(GROUPES_SANGUINS),
                'telephone': faker.numerify('+237 6## ### ###'),
                'contactNom': faker.name(),
                'contactTel': faker.numerify('+237 6## ### ###'),
                'contactLien': 'Membre de la famille',
                'codeConfirmation': faker.numerify('######'),
            }

            if options['dry_run']:
                lignes_csv.append({
                    'nom_complet': f"{identite['prenom']} {identite['nom']}",
                    'hopital': race,          # dry-run : on affiche la race/sexe au lieu de l'hôpital
                    'email': email,
                    'mot_de_passe': mot_de_passe,
                    'code': identite['codeConfirmation'],
                    'photo': photo_relative,
                })
                continue

            # Copie physique de l'image, puis création en base.
            try:
                shutil.copy2(src_image, dest_avatars / nom_image)
            except OSError as exc:
                raise CommandError(f'Copie impossible de {src_image} : {exc}')

            if Patient.objects.filter(email__iexact=email).exists():
                existants += 1
                continue

            from core.generateurs import generer_numero_patient
            pat = Patient(
                email=email,
                nom=identite['nom'],
                prenom=identite['prenom'],
                numeroPatient=generer_numero_patient(),
                dateNaissance=identite['dateNaissance'],
                sexe=identite['sexe'],
                adresse=identite['adresse'],
                numeroCNI=identite['numeroCNI'],
                groupeSanguin=identite['groupeSanguin'],
                photoProfil=photo_relative,
                etablissement=hopital,
                nomContactUrgencePrincipal=identite['contactNom'],
                telephoneContactUrgencePrincipal=identite['contactTel'],
                lienContactUrgencePrincipal=identite['contactLien'],
                codeConfirmation=identite['codeConfirmation'],
                doitChangerMotDePasse=options['doit_changer_mdp'],
            )
            pat.set_password(mot_de_passe)
            pat.save()
            crees += 1
            if crees % 10 == 0 or crees == len(selections):
                self.stdout.write(f'  ... {crees} compte(s) créé(s) sur {len(selections)}')

            lignes_csv.append({
                'nom_complet': f"{identite['prenom']} {identite['nom']}",
                'hopital': hopital.nom if hopital else '',
                'email': email,
                'mot_de_passe': mot_de_passe,
                'code': identite['codeConfirmation'],
                'photo': photo_relative,
            })

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(f'[dry-run] {len(lignes_csv)} patients simulés '
                                                 '(rien n\'a été écrit).'))
            self._repartition(lignes_csv)
            return

        if not options['only_new'] or not Path(settings.BASE_DIR, 'identifiants_patients.csv').exists():
            self._ecrire_csv(lignes_csv)

        self.stdout.write(self.style.SUCCESS(
            f'\n{crees} patient(s) créé(s), {existants} déjà présent(s).'))
        self.stdout.write(f'Mot de passe commun : {mot_de_passe}')
        self.stdout.write('Export : ' + str(Path(settings.BASE_DIR, 'identifiants_patients.csv')))
        self._repartition(lignes_csv)

        if options['rafraichir_photos'] and not options['dry_run']:
            self._rafraichir_photos()

    def _rafraichir_photos(self):
        """Recopie les photos normalisées du cache sur les avatars existants.

        Utile quand des comptes ont déjà été créés avec d'anciennes photos :
        on réapplique les fichiers normalisés (mêmes noms → mêmes URLs),
        sans toucher aux comptes.
        """
        cache = Path(settings.BASE_DIR, 'data', 'fairface_hf')
        if not cache.is_dir():
            raise CommandError('Cache FairFace introuvable : lancez d\'abord '
                               'le seed (--source hf).')
        dest = Path(settings.MEDIA_ROOT) / DOSSIER_AVATARS
        dest.mkdir(parents=True, exist_ok=True)
        copies = 0
        for chemin in sorted(cache.glob('patient_*.jpg')):
            try:
                shutil.copy2(chemin, dest / chemin.name)
            except OSError as exc:
                raise CommandError(f'Copie impossible de {chemin} : {exc}')
            copies += 1
        self.stdout.write(self.style.SUCCESS(
            f'{copies} photo(s) de profil rafraîchie(s) dans {dest}.'))

    # ──────────────────────────────────────────────────────────────
    def _localiser_fairface(self, chemin_donne):
        """Résout le dossier FairFace (option CLI > env > défaut projet)."""
        candidats = [chemin_donne, os.getenv('FAIRFACE_DIR'),
                     str(Path(settings.BASE_DIR) / 'data' / 'fairface')]
        for candidat in candidats:
            if not candidat:
                continue
            dossier = Path(candidat)
            if (dossier / 'fairface_label_val.csv').exists() and (dossier / 'val').is_dir():
                return dossier
        raise CommandError(
            'Introuvable : fairface_label_val.csv + dossier val/. '
            'Passez --fairface-dir "chemin/vers/fairface" (ou FAIRFACE_DIR).'
        )

    def _selectionner_images(self, dossier, quota, tolere_partiel=False):
        """Lit le CSV, remplit les groupes (race × sexe) jusqu'au quota.

        Parcourt une seule fois le fichier dans l'ordre : garantit une
        sélection équilibrée même si le CSV n'est pas parfaitement mélangé.

        Si le dataset fournit moins d'images que le quota :
          • sans --tolere-partiel → erreur nette (aucune écriture) ;
          • avec --tolere-partiel → on prend le maximum disponible par groupe
            et on prévient (création d'un nombre de patients < 100).

        Retourne : liste de tuples (race, sexe_courts, age_index, Path_image),
        age_index valant None pour la source CSV.
        """
        fichier_csv = dossier / 'fairface_label_val.csv'
        dossier_val = dossier / 'val'
        compteur = defaultdict(int)
        selections = []
        manquantes = []

        with open(fichier_csv, newline='', encoding='utf-8') as fh:
            lecteur = csv.DictReader(fh)
            for ligne in lecteur:
                race = (ligne.get(COLONNES['race']) or '').strip()
                sexe = SEXES_CSV.get((ligne.get(COLONNES['gender']) or '').strip())
                cle = (race, sexe)
                if race not in RACES_A_TIRER or not sexe:
                    continue
                if compteur[cle] >= quota:
                    continue
                image = dossier_val / os.path.basename(ligne.get(COLONNES['file'], ''))
                if not image.exists():
                    manquantes.append(image.name)
                    continue
                compteur[cle] += 1
                selections.append((race, sexe, None, image))

        pour_chaque = {(r, s): quota for r in RACES_A_TIRER for s in ('M', 'F')}
        non_remplies = {cle: pour_chaque[cle] - compteur.get(cle, 0)
                        for cle in pour_chaque if compteur.get(cle, 0) < pour_chaque[cle]}
        if non_remplies:
            detail = ', '.join(f'{r}/{s}: -{v}'
                               for (r, s), v in sorted(non_remplies.items()))
            if manquantes:
                detail += f' (+ {len(manquantes)} fichier(s) absent(s), ex. {manquantes[0]})'
            if not tolere_partiel:
                raise CommandError(
                    f'CSV insuffisant pour remplir les quotas ({detail}). '
                    'Fournissez un CSV complet du dataset FairFace, ou relancez '
                    'avec --tolere-partiel pour créer le maximum disponible.'
                )
            self.stderr.write(self.style.WARNING(
                f'Dataset partiel ({detail}) : création du maximum disponible.'
            ))
            if manquantes:
                self.stderr.write(self.style.WARNING(
                    f'{len(manquantes)} image(s) référencée(s) absente(s) du dossier val/.'
                ))
        return selections

    # ── Source Hugging Face ────────────────────────────────────────────────
    SERVER_DATASETS = 'https://datasets-server.huggingface.co'

    def _selectionner_hf(self, quota, tolere_partiel=False):
        """Récupère les photos + labels depuis Hugging Face (en cache ici).

        Utilise l'API « rows » du Datasets Server (lots de 100 lignes) : seules
        les lignes nécessaires sont parcourues, l'image est récupérée via son
        URL côté CDN. Aucun parquet complet n'est téléchargé — adapté aux
        connexions lentes. Le cache data/fairface_hf/ rend les lancements
        suivants instantanés et hors ligne.
        """
        cache = Path(settings.BASE_DIR, 'data', 'fairface_hf')
        cache.mkdir(parents=True, exist_ok=True)
        labels_fichier = cache / 'labels.csv'

        selections = self._lire_cache_hf(labels_fichier, cache)
        compteur = defaultdict(int)
        pour_chaque = {(r, s): quota for r in RACES_A_TIRER for s in ('M', 'F')}
        for race, sexe, _age, _chemin in selections:
            compteur[(race, sexe)] += 1
        besoin = {cle: pour_chaque[cle] - compteur[cle]
                  for cle in pour_chaque if compteur[cle] < pour_chaque[cle]}
        if not besoin:
            return selections

        try:
            import requests
            from PIL import Image
        except ImportError:
            raise CommandError(
                'Paquet requis manquant : lancez "pip install requests pillow".'
            )
        self.stderr.write(self.style.NOTICE(
            'Récupération des photos depuis Hugging Face '
            f'({ENSEMBLE_HF}, config {CONFIG_HF}, split {SPLIT_HF})...'))
        rejets = 0
        restant = sum(besoin.values())
        offset = 0
        try:
            while restant > 0:
                url = (f'{self.SERVER_DATASETS}/rows'
                       f'?dataset={ENSEMBLE_HF}&config={CONFIG_HF}&split={SPLIT_HF}'
                       f'&offset={offset}&length=100')
                reponse = requests.get(url, timeout=60)
                reponse.raise_for_status()
                lignes = reponse.json().get('rows') or []
                if not lignes:
                    break
                for entree in lignes:
                    ligne = entree['row']
                    genre = GENRE_HF.get(int(ligne['gender']))
                    race = RACE_HF.get(int(ligne['race']))
                    cle = (race, genre)
                    if cle not in besoin or besoin[cle] <= 0:
                        continue
                    source = ligne.get('image')
                    source = source.get('src') if isinstance(source, dict) else None
                    if not source:
                        continue
                    contenu = requests.get(source, timeout=120).content
                    try:
                        traite = _normaliser_photo_hf(contenu)
                    except ValueError as exc:
                        rejets += 1
                        self.stderr.write(
                            self.style.WARNING(
                                f'Photo rejetée ({exc}) — image suivante.'))
                        continue
                    nom = f'patient_{len(selections):03d}.jpg'
                    (cache / nom).write_bytes(traite)
                    selections.append((cle[0], cle[1], int(ligne['age']), cache / nom))
                    besoin[cle] -= 1
                    restant -= 1
                offset += len(lignes)
                time.sleep(0.2)
        except Exception as exc:
            raise CommandError(f'Échec de la récupération Hugging Face : {exc}')
        if rejets:
            self.stdout.write(f'{rejets} photo(s) rejetée(s) pour qualité insuffisante.')

        self._ecrire_cache_hf(labels_fichier, selections, cache)

        compteur_final = defaultdict(int)
        for race, sexe, _age, _chemin in selections:
            compteur_final[(race, sexe)] += 1
        non_remplies = {cle: pour_chaque[cle] - compteur_final[cle]
                        for cle in pour_chaque if compteur_final[cle] < pour_chaque[cle]}
        if non_remplies:
            detail = ', '.join(f'{r}/{s}: -{v}'
                               for (r, s), v in sorted(non_remplies.items()))
            if not tolere_partiel:
                raise CommandError(
                    f"Le dataset Hugging Face ne fournit pas assez d'images ({detail}). "
                    'Relancez avec --tolere-partiel pour créer le maximum disponible.'
                )
            self.stderr.write(self.style.WARNING(
                f'Dataset partiel ({detail}) : création du maximum disponible.'
            ))
        return selections

    def _lire_cache_hf(self, labels_fichier, cache):
        """Relit le cache local data/fairface_hf/labels.csv s'il existe."""
        if not labels_fichier.exists():
            return []
        selections = []
        with open(labels_fichier, newline='', encoding='utf-8-sig') as fh:
            for ligne in csv.DictReader(fh, delimiter=';'):
                chemin = cache / ligne['file']
                if not chemin.exists():
                    continue
                age = (ligne.get('age') or '').strip()
                age_index = int(age) if age.isdigit() else None
                selections.append((ligne['race'], ligne['sexe'], age_index, chemin))
        return selections

    def _ecrire_cache_hf(self, labels_fichier, selections, cache):
        """Écrit le cache local (labels.csv) pour garder la correspondance ligne par ligne."""
        with open(labels_fichier, 'w', newline='', encoding='utf-8-sig') as fh:
            ecrivain = csv.writer(fh, delimiter=';')
            ecrivain.writerow(['file', 'age', 'race', 'sexe'])
            for race, sexe, age_index, chemin in selections:
                ecrivain.writerow([
                    chemin.name,
                    age_index if age_index is not None else '',
                    race, sexe,
                ])

    def _fabriquer_faker(self, graine):
        from faker import Faker
        faker = Faker('fr_FR')
        faker.seed_instance(graine)
        return faker

    def _email_unique(self, faker, utilises):
        base = faker.email().lower()
        email = base
        suffixe = 1
        while email in utilises:
            email = base.replace('@', f'{suffixe}@')
            suffixe += 1
        utilises.add(email)
        return email

    @staticmethod
    def _normaliser_nom(nom):
        """Nettoyage : minuscules, sans accents, sans espaces superflus."""
        import unicodedata
        sans_accents = ''.join(
            c for c in unicodedata.normalize('NFD', nom)
            if unicodedata.category(c) != 'Mn'
        )
        return ' '.join(sans_accents.lower().split())

    def _resoudre_hopitaux(self):
        """Récupère les établissements EXISTANTS « Hôpital A » et « Hôpital B ».

        Aucune création : on s'appuie sur les enregistrements présents en base
        (déjà remplis par l'utilisateur). Échoue proprement si l'un manque.
        """
        from establishments.models import Etablissement
        index = {self._normaliser_nom(e.nom): e for e in Etablissement.objects.all()}
        manquants = []
        resolus = []
        for nom_voulu in NOMS_HOPITAUX:
            objet = index.get(self._normaliser_nom(nom_voulu))
            if objet is None:
                manquants.append(nom_voulu)
            else:
                resolus.append(objet)
        if manquants:
            connus = ', '.join(sorted(index)) if index else 'aucun'
            raise CommandError(
                'Établissement(s) introuvable(s) : ' + ', '.join(manquants) +
                f'. Établissements connus en base : {connus}.'
            )
        return resolus

    def _ecrire_csv(self, lignes):
        chemin = Path(settings.BASE_DIR, 'identifiants_patients.csv')
        with open(chemin, 'w', newline='', encoding='utf-8-sig') as fh:
            ecrivain = csv.DictWriter(fh, fieldnames=[
                'nom_complet', 'hopital', 'email', 'mot_de_passe', 'code', 'photo'],
                delimiter=';')
            ecrivain.writeheader()
            ecrivain.writerows(lignes)

    def _repartition(self, lignes):
        if not lignes:
            return
        par_hopital = defaultdict(int)
        for ligne in lignes:
            par_hopital[ligne['hopital']] += 1
        for cle, n in sorted(par_hopital.items()):
            self.stdout.write(f'  • {cle} : {n} patient(s)')