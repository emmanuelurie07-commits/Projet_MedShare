# Reconnaissance faciale réelle (dlib) — mise en place et déploiement

MedShare bascule **automatiquement** vers le vrai moteur de reconnaissance faciale
(`face_recognition` + `dlib`, encodages faciaux 128-d) dès que ces dépendances sont
présentes dans l'environnement Python. Sans elles, un **mode démo** déterministe
(hash perceptuel Pillow) prend le relais.

- Mode actif : `MODE_RECHERCHE == 'reel'` ⇒ libellé
  « Reconnaissance faciale dlib 128-d (moteur réel) ».
- Mode démo : `MODE_RECHERCHE == 'simulation'` ⇒ « Mode démo — similarité
  perceptuelle d'image (Pillow) ».

Le mode réel est **garanti exact** : visage identique ⇒ distance dlib `0.0`
/ confiance `100.0 %` ; un visage différent passe sous le seuil (60 %, distance
max `0.40`) et n'est **jamais inventé** (`[]` si rien ne dépasse).

## Pourquoi pas la compilation MSVC ?

Il n'existe **aucun wheel** `dlib` officiel (ni pour Python 3.12/3.13/3.14).
La compilation manuelle requiert Visual Studio Build Tools (workload C++) — un
**installateur MSI**, refusé sur les postes dont le service Windows Installer est
bloqué (observé avec 360 Total Security : « Failed to create Custom Action
Server. Error 3 », exit 1603/8012), et produit un binaire **non reproductible**.

La voie retenue — **`conda-forge` via `micromamba`** — donne un `dlib` précompilé
**identique partout** (aucune compilation, aucun MSI) et **reproductible** pour le
déploiement en équipe.

## Installer (une machine, ~5 min)

`micromamba` est un exécutable portable (aucune installation système, aucun admin).

```powershell
# 1. Télécharger micromamba (win-64)
#    https://github.com/mamba-org/micromamba-releases/releases/latest
#    → asset « micromamba-win-64.exe »

# 2. Créer l'environnement (Python 3.14 + dlib 20.0.1 précompilé conda-forge)
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\mamba-root"
& "C:\Users\<vous>\micromamba\micromamba.exe" create -y `
    -p "$env:USERPROFILE\envs\medshare" `
    -c conda-forge python=3.14 dlib=20.0.1

# 3. Dépendances du projet + moteur facial
& "C:\Users\<vous>\micromamba\micromamba.exe" run -p "$env:USERPROFILE\envs\medshare" `
    python -m pip install Django pillow python-dotenv setuptools==80.9.0

# 4. Modèles pré-entraînés de face_recognition (provenant du dépôt GitHub)
& "C:\Users\<vous>\micromamba\micromamba.exe" run -p "$env:USERPROFILE\envs\medshare" `
    python -m pip install "git+https://github.com/ageitgey/face_recognition_models"

# 5. face_recognition (le paquet PyPI face-recognition-models est un STUB : ne pas l'installer)
& "C:\Users\<vous>\micromamba\micromamba.exe" run -p "$env:USERPROFILE\envs\medshare" `
    python -m pip install face-recognition numpy
```

Pour déployer sur **Linux (serveur)** : utiliser l'asset `micromamba-linux-64`,
le même procédé (Python 3.14 + dlib conda-forge + le reste) donne le même moteur.

## Vérifier

```powershell
& "C:\Users\<vous>\micromamba\micromamba.exe" run -p "$env:USERPROFILE\envs\medshare" `
    python -c "import facial_recognition as fr; print(fr.MODE_RECHERCHE, '|', fr.MODE_LIBELLE)"
```

Attendu : `reel | Reconnaissance faciale dlib 128-d (moteur réel)`.

Lancer les tests (le vrai moteur y est couvert — `TestRechercheReelleTest`,
opt-in si dlib est présent) :

```powershell
& "C:\Users\<vous>\micromamba\micromamba.exe" run -p "$env:USERPROFILE\envs\medshare"`
    python manage.py test
```

## Déploiement SaaS (Docker + PostgreSQL)

La plateforme est pensée SaaS : configuration **100 % pilotée par variables
d'environnement** (`medshare/settings.py`, aucun chemin machine), base de
données **PostgreSQL** en production, `gunicorn` en serveur WSGI. Le fichier
`.env` local n'est **jamais** embarqué dans le conteneur.

### L'image (n'importe quelle machine avec Docker)

`Dockerfile` + `docker-compose.yml` sont fournis à la racine :

```powershell
# 1. Préparer la configuration
cp .env.example .env        # puis éditer SECRET_KEY, mots de passe, ALLOWED_HOSTS

# 2. Construire + démarrer (web + base PostgreSQL 16)
docker compose up --build -d

# 3. Ouvrir la plateforme
#    http://127.0.0.1:8000
```

Ce que contient l'image (`mambaorg/micromamba`, Debian) : `python=3.14`,
`dlib=20.0.1` **précompilé** extrait de conda-forge pour `linux-64`
(`dlib-20.0.1-cpu_py314`), les vrais modèles `face_recognition_models`
(dépôt GitHub), puis l'application + `gunicorn`. Au démarrage :
migrations, collectstatic, puis gunicorn sur `:8000`. Sur un **VPS** :
installer Docker, copier le dossier, `docker compose up -d --build` —
l'équipe obtient **le même moteur, les mêmes résultats** (aucune compilation,
aucun binaire lié à une machine).

### CI (preuve pour l'équipe)

`.github/workflows/ci.yml` (GitHub Actions, `ubuntu-latest`) :
1. recrée l'env micromamba + dlib conda-forge et exécute **121 tests**
   (le vrai moteur inclus) ;
2. construit l'image Docker et vérifie dans le conteneur
   `MODE_RECHERCHE == 'reel'`.

## Détails techniques

- `dlib` conda-forge : `dlib-20.0.1-cpu_py314` (variante CPU, sans CUDA) pour
  Windows **et** Linux ; disponible aussi `py310/311/312/313`.
- `face_recognition` dépend de `face_recognition_models`, lequel nécessite
  `setuptools<81` (présence de facile `pkg_resources`) ; préférez
  `setuptools==80.9.0`.
- Le paquet **PyPI `face-recognition-models` (0.3.0) est un placeholder** qui
  écrase le vrai `face_recognition_models` : à ne **jamais** installer.
- Le reste du projet (Django, Pillow, …) tourne indifféremment dans le venv
  `env\` (mode démo) ou dans l'env micromamba (mode réel) : les deux partagent
  la même base de code et le même seuil (`60 % ⇔ distance 0,40`).
- `ALLOWED_HOSTS`, `SECRET_KEY`, `DB_*`, e-mails, `MEDIA_ROOT`/`STATIC_ROOT`
  sont tous configurables par variables d'environnement
  (voir `.env.example`).