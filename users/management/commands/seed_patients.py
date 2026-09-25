"""
Management command : seed_patients

Pipeline « Photos d'identité » — 100 profils patients dont la photo est
GARANTIE exploitable par Dlib (reconnaissance faciale MedShare).

Remplace l'ancien pipeline FairFace (224×224 de faible qualité) : on ne
déploie plus des comptes dans PostgreSQL avec des photos dont Dlib ne peut
pas produire d'encodage.

Déroulement (de A à Z) :

 1. SOURCING STRICT (100 images)
      • --source api   (défaut) : StyleGAN2/FFHQ-like « thispersondoesnotexist.com »
        — portraits photoréalistes 1024×1024, livrés sans clé ni quota, tirés
        aléatoirement à chaque requête.
      • --source dossier : dossier local d'images haute qualité (FFHQ, etc.) ;
        chaque fichier est passé au même banc de validation.
    Chaque image brute est validée par Dlib/face_recognition :
        - exactement UN visage détecté (dlib.get_frontal_face_detector) ;
        - score de détection « face » élevé (>= --score-min, défaut 1.0) ;
        - encodage facial produit (face_encodings) sur l'image brute PUIS sur
          le recadrage final (double gate : ce que le moteur stockera doit
          obligatoirement encoder).
    L'image est ensuite recalibrée en photo d'identité : carré 4:4 centré sur
    le visage (marge de confort pour le menton/les cheveux), redimensionnée à
    la taille finale, RGB, JPEG qualité 92.
    Toute image corrompue, trop floue, non-frontale ou multi-visages est
    rejetée ; le pipeline passe à l'image suivante et ne s'arrête qu'avec
    `nombre` photos validées.

 2. GÉNÉRATION + INJECTION PostgreSQL
      • Métadonnées Faker('fr_FR') : prénom, nom, email professionnel
        (prenom.nom@medshare-demo.cm), sexe, date de naissance (18–80 ans),
        adresse, CNI, groupe sanguin, contacts d'urgence, code.
      • Répartition STRICTE 50/50 : les 50 premières photos validées → l'un
        des deux hôpitaux, les 50 suivantes → l'autre (aucun aléa).
      • Modèles MedShare EXISTANTS (aucune migration) : Patient — qui porte
        l'authentification Django (set_password) et les données métier dans
        une seule hiérarchie (le concept « PatientProfile » n'existe pas :
        tout est sur Patient). `photoProfil` prend le chemin relatif
        `patients_avatars/patient_0XX.jpg`.

 3. EXPORT — identifiants_patients.csv à la racine du projet :
      « Nom complet » | « Email/Identifiant » | « Mot de passe » |
      « Hôpital d'affectation » | « Chemin de l'image » | « Validé par Dlib »
    (délimiteur « ; », UTF-8 avec BOM, compatible Excel).

Nettoyage de l'existant :
      --purge supprime AUTOMATIQUEMENT tous les patients dont la photo est
    sous `patients_avatars/` (les anciens comptes du seed FairFace, y compris
    ceux déjà déployés). Les vrais comptes utilisateurs (photos « profiles/ »)
    ne sont jamais touchés.

Usage :
    python manage.py seed_patients                          # source API, 100 photos
    python manage.py seed_patients --purge                  # purge l'ancien seed puis recrée
    python manage.py seed_patients --source dossier --photos-dossier "chemin/vers/ffhq"
    python manage.py seed_patients --nombre 50 --score-min 1.0

Options utiles :
    --source {api,dossier}   origine des photos brutes (défaut « api »)
    --photos-dossier PATH    dossier local (avec --source dossier)
    --nombre N               nombre de patients à créer, défaut 100
    --taille N               côté final en pixels (carré 4:4), défaut 300
    --score-min S            seuil de confiance Dlib, défaut 1.0 (strict)
    --mot-de-passe MDP       mot de passe commun, défaut « MedShare@2026! »
    --graine N               graine Faker (reproductibilité)
    --purge                  supprime d'abord les patients « patients_avatars/ »
    --tolere-partiel         créer moins de `nombre` patients si la source
                             s'épuise (au lieu d'abandonner)
    --journal FICHIER        journal de progression (append), défaut
                             data/seed_patients.log
    --dry-run                collecte + identités, sans purge ni écriture en base
    --only-new               ne pas réécrire le CSV s'il existe déjà

Contrainte : nécessite dlib + face_recognition (validation stricte). Sur
Render (dlib absent) cette commande ne peut pas produire de photo validée ;
elle s'en sert uniquement pour l'exécution locale des données de démo.
"""

import csv
import io
import os
import time
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# ── Source externe haute qualité (StyleGAN2 / FFHQ-like) ────────────────────
# Livre un portrait photoréaliste 1024×1024 par GET, sans clé ni quota.
SOURCE_API = 'https://thispersondoesnotexist.com/random-person.jpeg'
USER_AGENT = 'Mozilla/5.0 (MedShare-seed; Django)'

# ── Banc de validation Dlib (strict) ────────────────────────────────────────
TAILLE_PHOTO = 300           # côté du carré final (4:4)
FACTEUR_MARGE = 1.35         # marge autour du cadre facial (menton/cheveux)
SCORE_MIN = 1.0              # « indice de confiance élevé » du détecteur HOG
MAX_TENTATIVES = 400         # garde-fou : tentatives brutes avant abandon

# ── Paramètres métier MedShare ──────────────────────────────────────────────
DOSSIER_AVATARS = 'patients_avatars'
NOMS_HOPITAUX = ['Hôpital A', 'Hôpital B']
GROUPES_SANGUINS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

try:
    import dlib                                # noqa: F401
    import face_recognition                    # noqa: F401
    _DLIB_OK = True
except ImportError:
    _DLIB_OK = False

_detecteur = None


def _get_detecteur():
    """Détecteur de visage frontal (HOG) partagé par toutes les validations."""
    global _detecteur
    if _detecteur is None:
        _detecteur = dlib.get_frontal_face_detector()
    return _detecteur


def _encodage_facial_ok(tableau):
    """True si dlib parvient à produire un encodage (photo exploitable)."""
    try:
        return bool(face_recognition.face_encodings(tableau))
    except Exception:
        return False


class Command(BaseCommand):
    help = ('Crée des patients fictifs dont les photos sont validées par Dlib '
            'photo d\'identité 4:4 (300×300) et injecte les 100 profils en base.')

    def add_arguments(self, parser):
        parser.add_argument('--source', type=str, choices=['api', 'dossier'],
                            default='api',
                            help='Origine des photos brutes : « api » '
                                 '(thispersondoesnotexist, défaut) ou « dossier » '
                                 '(photos locales haute qualité).')
        parser.add_argument('--photos-dossier', type=str, default=None,
                            help='Dossier d\'images brutes (avec --source dossier).')
        parser.add_argument('--nombre', type=int, default=100,
                            help='Nombre de patients (défaut 100).')
        parser.add_argument('--taille', type=int, default=TAILLE_PHOTO,
                            help='Côté final du carré photo (4:4). Défaut 300.')
        parser.add_argument('--score-min', type=float, default=SCORE_MIN,
                            help='Seuil de confiance Dlib (défaut 1.0).')
        parser.add_argument('--mot-de-passe', type=str, default='MedShare@2026!',
                            help='Mot de passe commun des comptes créés.')
        parser.add_argument('--graine', type=int, default=2026,
                            help='Graine aléatoire Faker (reproductibilité).')
        parser.add_argument('--purge', action='store_true',
                            help='Supprimer d\'abord les patients dont la photo '
                                 'est sous patients_avatars/ (ancien seed) — '
                                 'les vrais comptes utilisateurs sont épargnés.')
        parser.add_argument('--tolere-partiel', action='store_true',
                            help='Créer moins de patients si la source s\'épuise.')
        parser.add_argument('--journal', type=str, default=None,
                            help='Journal de progression (append). Défaut : '
                                 'data/seed_patients.log sous le projet.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Collecte + identités, sans purge ni écriture en base.')
        parser.add_argument('--only-new', action='store_true',
                            help='Ne pas réécrire le CSV s\'il existe déjà.')

    # ── Coeur de la commande ────────────────────────────────────────────────
    def handle(self, *args, **options):
        from users.models import Patient

        if not _DLIB_OK:
            raise CommandError(
                'dlib + face_recognition sont requis pour valider les photos : '
                'lancez « pip install dlib face-recognition ».')
        self._initialiser_journal(options)

        nombre = options['nombre']
        if nombre < 1:
            raise CommandError('--nombre doit être ≥ 1.')
        taille = options['taille']
        score_min = options['score_min']
        self.taille = taille

        if options['source'] == 'dossier' and not options['photos_dossier']:
            raise CommandError('--source dossier exige --photos-dossier PATH.')

        # 1) Purge de l'ancien seed (uniquement si demandé).
        if options['purge']:
            self._purger_anciens_patients(dry_run=options['dry_run'])

        # 2) Établissements existants (« Hôpital A » / « Hôpital B »).
        hopitaux = self._resoudre_hopitaux() if not options['dry_run'] else []

        # 3) Sourcing + validation stricte Dlib jusqu'à `nombre` photos.
        dest_avatars = Path(settings.MEDIA_ROOT) / DOSSIER_AVATARS
        dest_avatars.mkdir(parents=True, exist_ok=True)
        photos = self._collecter_photos_validees(nombre, taille, score_min,
                                                 options, dest_avatars)

        # 4) Identités Faker + injection (50/50 strict entre les deux hôpitaux).
        faker = self._fabriquer_faker(options['graine'])
        emails_utilises = {e.lower() for e in Patient.objects.values_list('email', flat=True)}

        lignes_csv = []
        crees, existants = 0, 0

        for indice, (photo_relative, octets_jpeg) in enumerate(photos):
            identite = self._fabriquer_identite(faker)
            email = self._email_pro(identite['prenom'], identite['nom'], emails_utilises)
            identite['email'] = email

            if options['dry_run']:
                lignes_csv.append(self._ligne_csv(identite, mot_de_passe=options['mot_de_passe'],
                                                  hopital='', photo=photo_relative))
                continue

            # Répartition 50/50 stricte : 1re moitié → hôpital A, 2e → hôpital B.
            hopital = hopitaux[0] if indice < len(photos) // 2 else hopitaux[1]

            (dest_avatars / photo_relative.split('/')[-1]).write_bytes(octets_jpeg)

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
                doitChangerMotDePasse=False,
            )
            pat.set_password(options['mot_de_passe'])
            pat.save()
            crees += 1
            if crees % 10 == 0 or crees == len(photos):
                self._log(f'  ... {crees}/{len(photos)} compte(s) créé(s)')

            lignes_csv.append(self._ligne_csv(identite, mot_de_passe=options['mot_de_passe'],
                                              hopital=hopital.nom, photo=photo_relative))

        if options['dry_run']:
            self._log('')
            self._log(self.style.WARNING(
                f'[dry-run] {len(lignes_csv)} patients simulés (base intacte).'))
            self._repartition(lignes_csv)
            return

        if not options['only_new'] or not Path(
                settings.BASE_DIR, 'identifiants_patients.csv').exists():
            self._ecrire_csv(lignes_csv)

        self._log('')
        self._log(self.style.SUCCESS(
            f'\n{crees} patient(s) créé(s), {existants} déjà présent(s).'))
        self._log(f'Mot de passe commun : {options["mot_de_passe"]}')
        self._log('Export : ' + str(Path(settings.BASE_DIR, 'identifiants_patients.csv')))
        self._repartition(lignes_csv)

    # ── Source + validation stricte (Cœur 1) ───────────────────────────────
    def _collecter_photos_validees(self, nombre, taille, score_min, options, dest_avatars):
        """Récupère exactement `nombre` photos validées par Dlib.

        Boucle sur la source : chaque image brute est passée au banc de
        validation (1 visage frontal, score élevé, encodage garanti avant ET
        après le recadrage 4:4). Les images non conformes sont rejetées et
        comptées par motif ; la collection s'arrête à `nombre` réussites.

        Renvoie une liste de tuples (photo_relative, octets_jpeg_final).
        """
        rejets = defaultdict(int)
        photos = []
        tentative = 0
        patient_courant = 0
        sel = self._construire_source(options)

        while patient_courant < nombre:
            tentative += 1
            if tentative > MAX_TENTATIVES:
                if options['tolere_partiel'] and photos:
                    self._log(self.style.WARNING(
                        f'Source épuisée : {len(photos)} photo(s) validée(s) '
                        f'seulement (--tolere-partiel).'))
                    return photos
                detail = ', '.join(f'{motif}: {n}' for motif, n in sorted(rejets.items()))
                raise CommandError(
                    f'Validation Dlib : impossible d\'obtenir {nombre} photos '
                    f'après {MAX_TENTATIVES} tentatives. Rejets ({detail}). '
                    'Relancez avec --tolere-partiel pour garder l\'avance.')

            contenu = sel.suivante()
            if contenu is None:
                if options['tolere_partiel'] and photos:
                    self._log(self.style.WARNING(
                        f'Source épuisée : {len(photos)} photo(s) validée(s) '
                        f'seulement (--tolere-partiel).'))
                    return photos
                raise CommandError('Source épuisée avant d\'atteindre le quota. '
                                   'Relancez avec --tolere-partiel pour créer le maximum '
                                   'disponible.')

            try:
                octets_jpeg = self._fabriquer_photo_de_profil(contenu, taille, score_min)
            except ValueError as exc:
                rejets[str(exc)] += 1
                self._log(self.style.WARNING(
                    f'    photo rejetée ({exc}) — image suivante.'))
                continue

            patient_courant += 1
            nom_image = f'patient_{patient_courant - 1:03d}.jpg'
            photo_relative = f'{DOSSIER_AVATARS}/{nom_image}'
            photos.append((photo_relative, octets_jpeg))
            self._log(f'  photo {patient_courant}/{nombre} : {nom_image} validée '
                      f'({taille}×{taille})')

        if rejets:
            res = ', '.join(f'{k}: {v}' for k, v in sorted(rejets.items()))
            self._log(f'Images rejetées par le banc Dlib → {res}')
        return photos

    def _fabriquer_photo_de_profil(self, octets, taille, score_min):
        """Banc de validation Dlib STRICT + recadrage photo d'identité 4:4.

        Étapes :
          1. décodage RGB (image corrompue → ValueError) ;
          2. détection frontale : EXACTEMENT un visage + score >= score_min ;
          3. encodage facial produit sur l'image brute ;
          4. recadrage carré centré sur le visage (marge de confort) ;
          5. redimensionnement à `taille`×`taille` et NOUVEL encodage du
             résultat (le fichier final DOIT être exploitable par le moteur) ;
        Renvoie les octets JPEG du carré final (qualité 92).
        """
        from PIL import Image
        import numpy as np

        try:
            image = Image.open(io.BytesIO(octets)).convert('RGB')
        except Exception as exc:
            raise ValueError(f'image illisible ({type(exc).__name__})')
        if image.size[0] < 320 or image.size[1] < 320:
            raise ValueError(f'résolution insuffisante {image.size[0]}×{image.size[1]}')

        tableau = np.array(image)

        rects, scores, _ = _get_detecteur().run(tableau, 0)
        if len(rects) != 1:
            raise ValueError(f'{len(rects)} visage(s) détecté(s)')
        score = float(scores[0])
        if score < score_min:
            raise ValueError(f'score Dlib {score:.2f} < {score_min:.2f}')
        if not _encodage_facial_ok(tableau):
            raise ValueError('encodage facial impossible sur l\'original')

        recadre = self._recadrer_identite(image, rects[0])
        carre = recadre.resize((taille, taille), self._resample())
        if not _encodage_facial_ok(np.array(carre)):
            raise ValueError('encodage impossible après recadrage 4:4')

        sortie = io.BytesIO()
        carre.save(sortie, 'JPEG', quality=92)
        return sortie.getvalue()

    @staticmethod
    def _resample():
        from PIL import Image
        return (Image.Resampling.LANCZOS if hasattr(Image, 'Resampling')
                else Image.LANCZOS)

    @staticmethod
    def _recadrer_identite(image, visage):
        """Carré 4:4 centré sur le visage, avec marge (menton/cheveux)."""
        largeur, hauteur = image.size
        base = max(abs(visage.right() - visage.left()),
                   abs(visage.bottom() - visage.top()))
        cote = int(base * FACTEUR_MARGE)
        if cote >= min(largeur, hauteur):
            cote = int(min(largeur, hauteur) * 0.92)
        milieu_x = (visage.left() + visage.right()) / 2.0
        milieu_y = (visage.top() + visage.bottom()) / 2.0
        gauche = int(max(0, min(milieu_x - cote / 2.0, largeur - cote)))
        haut = int(max(0, min(milieu_y - cote / 2.0, hauteur - cote)))
        return image.crop((gauche, haut, gauche + cote, haut + cote))

    # ── Sources ─────────────────────────────────────────────────────────────
    def _construire_source(self, options):
        if options['source'] == 'api':
            return _SourceAPI()
        return _SourceDossier(Path(options['photos_dossier']))

    # ── Purge de l'ancien seed ──────────────────────────────────────────────
    def _purger_anciens_patients(self, dry_run=False):
        """Supprime les patients dont photoProfil est sous patients_avatars/.

        Critère prudent : les vrais comptes (avatars uploadés sous
        media/profiles/) ne sont JAMAIS supprimés. Ceci retire proprement
        l'ancien seed FairFace, y compris ses comptes déjà déployés.
        """
        from users.models import Patient
        queryset = Patient.objects.filter(
            photoProfil__startswith=f'{DOSSIER_AVATARS}/')
        total = queryset.count()
        suffixe = ' (simulation dry-run)' if dry_run else ''
        self._log(self.style.WARNING(
            f'[purge] {total} patient(s) avec photo sous {DOSSIER_AVATARS}/ '
            f'trouvé(s){suffixe}.'))
        if not dry_run:
            queryset.delete()
            self._log(self.style.SUCCESS('[purge] anciens comptes supprimés.'))

    # ── Identités Faker fr_FR ───────────────────────────────────────────────
    def _fabriquer_faker(self, graine):
        from faker import Faker
        faker = Faker('fr_FR')
        faker.seed_instance(graine)
        return faker

    def _fabriquer_identite(self, faker):
        if faker.boolean():
            sexe, nom_prenom = 'M', faker.first_name_male()
        else:
            sexe, nom_prenom = 'F', faker.first_name_female()
        return {
            'nom': faker.last_name(),
            'prenom': nom_prenom,
            'sexe': sexe,
            'dateNaissance': faker.date_of_birth(minimum_age=18, maximum_age=80),
            'adresse': ' '.join(faker.address().split('\n')),
            'numeroCNI': faker.numerify('################')[:14],
            'groupeSanguin': faker.random_element(GROUPES_SANGUINS),
            'telephone': faker.numerify('+237 6## ### ###'),
            'contactNom': faker.name(),
            'contactTel': faker.numerify('+237 6## ### ###'),
            'contactLien': 'Membre de la famille',
            'codeConfirmation': faker.numerify('######'),
        }

    @staticmethod
    def _normaliser_nom(nom):
        """Minuscules, sans accents, sans espaces superflus."""
        import unicodedata
        sans_accents = ''.join(
            c for c in unicodedata.normalize('NFD', nom)
            if unicodedata.category(c) != 'Mn'
        )
        return ' '.join(sans_accents.lower().split())

    def _email_pro(self, prenom, nom, utilises):
        """Email professionnel déterministe : prenom.nom@medshare-demo.cm."""
        base = (self._normaliser_nom(prenom) + '.' + self._normaliser_nom(nom))
        base = base.replace(' ', '.')[:48].strip('.')
        email = f'{base}@medshare-demo.cm'
        suffixe = 1
        while email in utilises:
            email = f'{base}{suffixe}@medshare-demo.cm'
            suffixe += 1
        utilises.add(email)
        return email

    # ── Export CSV ──────────────────────────────────────────────────────────
    @staticmethod
    def _ligne_csv(identite, mot_de_passe, hopital, photo):
        return {
            'nom_complet': f"{identite['prenom']} {identite['nom']}",
            'email': identite['email'],
            'mot_de_passe': mot_de_passe,
            'hopital': hopital,
            'photo': photo,
            'statut': 'OUI — 1 visage frontal, encodage Dlib OK (300×300)',
        }

    def _ecrire_csv(self, lignes):
        chemin = Path(settings.BASE_DIR, 'identifiants_patients.csv')
        with open(chemin, 'w', newline='', encoding='utf-8-sig') as fh:
            ecrivain = csv.DictWriter(fh, fieldnames=[
                'nom_complet', 'email', 'mot_de_passe', 'hopital', 'photo', 'statut'],
                delimiter=';')
            ecrivain.writerow({
                'nom_complet': 'Nom complet',
                'email': 'Email/Identifiant',
                'mot_de_passe': 'Mot de passe',
                'hopital': "Hôpital d'affectation",
                'photo': 'Chemin de l\'image',
                'statut': 'Validé par Dlib',
            })
            ecrivain.writerows(lignes)

    def _repartition(self, lignes):
        if not lignes:
            return
        par_hopital = defaultdict(int)
        for ligne in lignes:
            par_hopital[ligne['hopital'] or '—'] += 1
        for cle, n in sorted(par_hopital.items()):
            self._log(f'  • {cle} : {n} patient(s)')

    def _resoudre_hopitaux(self):
        """Établissements EXISTANTS « Hôpital A » / « Hôpital B » (aucune création)."""
        from establishments.models import Etablissement
        index = {self._normaliser_nom(e.nom): e for e in Etablissement.objects.all()}
        resolus = []
        manquants = []
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
                f'. Établissements connus en base : {connus}.')
        return resolus

    # ── Journal (progression persistante même si la console est tuée) ───────
    def _log(self, message):
        self.stdout.write(str(message), ending='\n')
        self.stdout.flush()
        chemin = getattr(self, '_journal', None)
        if chemin:
            try:
                with open(chemin, 'a', encoding='utf-8') as fh:
                    fh.write(f'{time.strftime("%H:%M:%S")} {message}\n')
            except OSError:
                pass

    def _initialiser_journal(self, options):
        if options['journal']:
            chemin = Path(options['journal'])
        else:
            chemin = Path(settings.BASE_DIR, 'data', 'seed_patients.log')
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._journal = chemin


# ── Sources d'images brutes ─────────────────────────────────────────────────
class _SourceAPI:
    """Source case : portraits StyleGAN2 1024×1024 téléchargés à la demande."""

    def __init__(self):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        self.requetes = requests.Session()
        self.requetes.headers['User-Agent'] = USER_AGENT
        tenacite = Retry(total=6, backoff_factor=0.8,
                         status_forcelist=[429, 500, 502, 503, 504],
                         allowed_methods=frozenset(['GET']))
        adaptateur = HTTPAdapter(max_retries=tenacite)
        self.requetes.mount('https://', adaptateur)

    def suivante(self):
        try:
            reponse = self.requetes.get(SOURCE_API, timeout=90)
            reponse.raise_for_status()
            contenu = reponse.content
            if contenu[:2] != b'\xff\xd8':  # pas un JPEG → image refusée
                raise ValueError('réponse non-JPEG')
            return contenu
        except Exception as exc:
            print('    (source API indisponible, nouvel essai…)', exc)
            return b''


class _SourceDossier:
    """Source dossier : images locales passées une à une (FFHQ, etc.)."""

    EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

    def __init__(self, dossier):
        if not dossier.is_dir():
            raise CommandError(f'--photos-dossier introuvable : {dossier}')
        self.fichiers = sorted(
            p for p in dossier.iterdir()
            if p.suffix.lower() in self.EXTENSIONS)
        self.indice = 0
        if not self.fichiers:
            raise CommandError(
                f'Aucune image ({", ".join(sorted(self.EXTENSIONS))}) dans '
                f'{dossier}.')

    def suivante(self):
        if self.indice >= len(self.fichiers):
            return None
        chemin = self.fichiers[self.indice]
        self.indice += 1
        try:
            return chemin.read_bytes()
        except OSError as exc:
            print(f'    (lecture impossible : {chemin.name} → {exc})')
            return b''