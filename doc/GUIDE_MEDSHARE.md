# MedShare — Guide complet
> Plateforme SaaS de gestion de dossiers médicaux partagés (Cameroun)
> Reconnaissance faciale réelle (dlib 128-d) + cycle DUT/DMP, multi-établissements, audit.

---

## Sommaire

1. [Ce qui a été fait](#1-ce-qui-a-été-fait)
2. [Architecture et modules](#2-architecture-et-modules)
3. [Rôles, permissions et contrôle d'accès](#3-rôles-permissions-et-contrôle-daccès)
4. [Démarrage local](#4-démarrage-local)
5. [Moteur de reconnaissance faciale](#5-moteur-de-reconnaissance-faciale)
6. [Configuration (.env) et base de données](#6-configuration-env-et-base-de-données)
7. [Ce qui peut être modifié et comment](#7-ce-qui-peut-être-modifié-et-comment)
8. [Scénarios de démonstration complets](#8-scénarios-de-démonstration-complets)
9. [Déploiement](#9-déploiement)
   - [9.1 Docker / Compose (VPS)](#91-docker--compose-vps)
   - [9.2 PythonAnywhere (procédure complète)](#92-pythonanywhere-procédure-complète)
   - [9.3 Vercel (analyse et limites)](#93-vercel-analyse-et-limites)
10. [Dépannage (FAQ)](#10-dépannage-faq)
11. [Tests automatisés](#11-tests-automatisés)

---

## 1. Ce qui a été fait

Le projet MedShare est une **plateforme SaaS camerounaise** qui permet à plusieurs
hôpitaux de partager des dossiers médicaux et de **réidentifier un patient
inconnu arrivant aux urgences** grâce à la **reconnaissance faciale**,
le tout tracé dans un journal d'audit.

Modules livrés et fonctionnels :

| Module | Contenu |
|---|---|
| **Accounts / Rôles** (`users`) | Compte unique personnalisé (`AUTH_USER_MODEL = users.Personnel`), héritage multi-table : `Personnel` (médecin, infirmier, administrateur) et `Patient`. Chaque compte a un **jeton d'accès personnel renouvelé à chaque connexion**. |
| **Établissements & SaaS** (`establishments`) | Établissements, formules, abonnements (statut ACTIF/SUSPENDU), parcours **candidat → compte personnel**, gestion du personnel. |
| **DMP** (`dmp`) | Dossier Médical Partagé, patients, consultations, prescriptions, ordonnances, historique patient. |
| **Urgences & DUT** (`urgences`) | Dossier d'Urgence Temporaire, prise de vue → recherche faciale automatique → correspondances (top 5) → triage, constantes vitales, fiche vitale, Break Glass, fusion DUT→DMP, clôture, **JournalAudit** (traçabilité RGPD). |
| **Reconnaissance faciale** (`facial_recognition`) | Moteur **réel** `face_recognition` + `dlib` (encodages 128-d) ; repli **déterministe** « Mode démo » par hash perceptuel (Pillow) si dlib absent. Jamais de résultat inventé. |
| **Super administration** (`core`) | Seule l'éditeur SaaS (super admin) : abonnements, création d'**administrateurs liés à un hôpital**, rapports d'audit **en lecture seule**. |
| **SaaS / Docker / CI** | `Dockerfile` (base `mambaorg/micromamba`, dlib 20.0.1 précompilé conda-forge), `docker-compose.yml` (web + PostgreSQL 16), `.github/workflows/ci.yml` (tests + smoke « reel » dans le conteneur), `.env.example`. |

Les dernières évolutions (à soutenance) :
- **Isolation stricte par rôle et par URL** (voir §3) : plus personne ne peut
  atteindre un dashboard « au hasard » dans la barre d'adresse.
- **Super admin recentré** : abonnements, ajout d'un administrateur d'hôpital,
  rapports d'audit consultables mais **non modifiables** (admin Django en lecture seule).
- **Textes d'interface raccourcis** (suppression des mentions « >60 % », « 0,40 »,
  « face distance », etc.) ; bouton « Postuler » remplacé par « Soumettre une demande ».
- `requirements.txt` ajouté et moteur de base de données pilotable (`DB_ENGINE`).

Évolutions de l'**addendum 4** :
- **P1 — Changement de mot de passe** : après le changement (obligatoire à la 1ʳᵉ
  connexion), l'utilisateur rejoint **directement son tableau de bord** — sa session
  est conservée (`update_session_auth_hash`), plus de retour au login. Page de
  confirmation `/compte/mot-de-passe-modifie/`.
- **T4 — Une seule session active par compte** : chaque connexion génère une clé
  `session_active_key` (compte + session). `SessionUniqueMiddleware` déconnecte
  proprement l'ancien appareil à sa prochaine requête, avec un **message explicite**
  (« remplacée par une connexion plus récente ») + journal `SESSION_REMPLACEE`.
- **T1 — Historique des accès pour le patient** : le patient consulte « Historique
  des accès » (`/dmp/mes-acces/`) : **qui** (nom, rôle, établissement), **quand**,
  **quelle action** (consultation, ordonnance, DUT, Break Glass, vote d'approbation).
  Jamais d'e-mail ni d'identifiant interne (RGPD). `JournalAudit.patient` porte la trace.
- **T2 — Robustesse e-mail** : renvoi de la notification d'approbation DMP limité
  à **3** envois avec délai de sécurité de **5 min** (bouton « Renvoyer »
  sur les écrans soignants) ; cooldown d'une **1 minute** entre deux envois de code
  2FA ; échecs de `envoyer_email` journalisés (logger `medshare.email`).
- **T3 — Politique de clôture des DUT** : un DUT resté **sans correspondance
  confirmée pendant 72 h** passe en statut `EN_ATTENTE_PROLONGEE` (jamais de clôture
  automatique). La clôture définitive reste une **décision médicale** : seul un
  Médecin peut clôturer, avec **motif obligatoire**. Commande : `manage.py politique_dut`
  (appelée aussi au login).
- **P3/P6/Accessibilité** : modale « guide photo » (1×/session) sur la création de
  patient, de DUT et la recherche d'identité ; fond de connexion en **SVG nettoyé**
  (métadonnées supprimées) ; **messages flash globalisés** dans `base_dynamic.html`
  (visibles sur tous les dashboards/pages professionnelles).

---

## 2. Architecture et modules

```
users/          Personnel, Patient, Role, Permission, middlewares (RBAC, 2FA), backends
establishments/ Etablissement, Formule, Abonnement, Candidature + vues SaaS local
dmp/            DossierMedicalPartage, Consultation, Prescription, Medicament
urgences/       DUT, Triage, Constante, RechercheIdentite, JournalAudit, fiche vitale
facial_recognition/  ServiceReconnaissanceFaciale, conversion distance⇄confiance, CLI
core/           dashboard global + vues super admin
medshare/       settings, urls racine, wsgi/asgi
templates/      base.html, base_auth.html, login, dmp/*, urgences/*, establishments/*, registration/*
core/templates/core/  dashboards par rôle + pages super admin
static/         css, icônes, service-worker, manifest (PWA)
doc/            face_recognition_reel.md, GUIDE_MEDSHARE.md (ce fichier)
uml/            diagrammes PlantUML (cas d'utilisation, classes, séquences)
```

Point d'entrée : la **racine `/`** est le portail de connexion. Après connexion,
chaque profil est redirigé vers son dashboard dédié.

---

## 3. Rôles, permissions et contrôle d'accès

### 3.1 Matrice des rôles

| Action | Patient | Infirmier | Médecin | Admin hôpital | Super Admin |
|---|---|---|---|---|---|
| Se connecter (portail `/`) | ✅ (via son jeton) | ✅ | ✅ | ✅ | ✅ (+ 2FA sur `/admin/`) |
| Consulter son DMP / ordonnances / historique | ✅ (lui seul) | — | — | — | — |
| Rechercher un patient | — | ✅ | ✅ | ✅ | **non** (bloqué) |
| Créer un patient | — | ✅ | — | ✅ | **non** |
| Créer un DUT (photo) & triage/constantes | — | ✅ | ✅ | ✅ | **non** |
| Confirmer une identité / fusion DUT→DMP | — | — | ✅ | — | — |
| Fiche vitale & Break Glass | — | ✅ (lecture) | ✅ | ✅ | **non** |
| Gérer candidatures / personnel | — | — | — | ✅ | **non** (décorateur strict) |
| Consulter l'abonnement de son hôpital | — | — | — | ✅ | — |
| Journal d'audit de SON établissement | — | — | — | ✅ | — |
| Journal d'audit GLOBAL | — | — | — | — | ✅ **lecture seule** |
| Gérer abonnements & formules | — | — | — | — | ✅ |
| Ajouter un administrateur d'hôpital | — | — | — | — | ✅ |
| Django admin `/admin/` | — | — | — | — | ✅ (2FA obligatoire) |

### 3.2 Mécanisme de contrôle d'accès

1. **`users.middleware.RBACMiddleware`** injecte `request.user_roles` (rôles de
   l'utilisateur) et `request.user_etablissement`.
2. **Décorateurs** (`users/decorators.py`) appliqués sur CHAQUE vue :
   - `@login_required` : anonyme → redirection connexion.
   - `@role_required_strict(...)` : accès aux seuls rôles listés ; **super admin
     explicitement bloqué**.
   - `@block_superadmin` : autorise tout personnel mais refuse le super admin.
   - `@admin_etablissement_required_strict` : admin de l'établissement **uniquement**
     (super admin bloqué).
   - `super_*` (vues core) : accès super admin **seulement**.
3. **Isolation patient** : dashboard patient accessible par `/compte/acces/<jeton>/`
   uniquement si `request.user.pk == patient.pk` (contrôle dans la vue).
   Les URL `mes_ordonnances/<pk>` et `mon_historique/<pk>` sont **refusées (404)**
   si l'appelant n'est pas le patient lui-même.
4. **2FA par e-mail** (addendum 3) : `DeuxFacteursMiddleware` impose la double
   authentification — après une connexion par le formulaire `MedShareLoginView`
   — au **Super Admin** et à l'**Administrateur d'établissement**. Le code à
   6 chiffres est envoyé **par e-mail uniquement** (jamais affiché à l'écran),
   il expire après 5 minutes, peut être renvoyé 3 fois au maximum, avec un
   délai de sécurité d'**1 minute** entre deux envois. Page dédiée
   `/compte/superadmin/`, URL `superadmin_2fa` / `superadmin_2fa_verifier`.
   Le Super Admin de production est `emmanuelurie07@gmail.com` (rôle « Super
   Admin », matricule `SUP-2026-0001`, créé par la migration
   `users/0008_creer_superadmin_initial`).
5. **Journal d'audit en lecture seule** : `urgences/admin.py` (`JournalAuditAdmin`)
   refuse ajout, modification et suppression.
6. **Session unique** (addendum 4/T4) : `SessionUniqueMiddleware` compare la clé
   `session_active_key` du compte à celle de la session ; en cas de divergence
   (connexion plus récente sur un autre appareil) l'ancienne session est
   déconnectée et redirigée vers le login avec un message explicite.
7. **Approbation DMP & notifications** (addendum 4/T2) : la demande d'accès
   notifie le patient dès sa création (3 renvois max, délai 5 min) ; l'écran
   soignant affiche un bouton « Renvoyer la notification au patient » tant que
   la demande est en attente.
8. **Politique de clôture DUT** (addendum 4/T3) : passage en
   `EN_ATTENTE_PROLONGEE` après 72 h sans correspondance confirmée
   (`urgences/services.py`, commande `politique_dut`) ; clôture définitive
   réservée au Médecin avec motif obligatoire (`detail_dut.html`).
9. **Historique des accès patient** (addendum 4/T1) : la « liste blanche »
   d'actions tracées pour le patient (`ACCES_DMP_ACTIONS`) s'affiche
   en lecture seule dans `/dmp/mes-acces/` (jamais d'e-mail/id interne).

### 3.3 Vérification « barre d'adresse »

Tous les chemins suivants ont été testés (`URLAccessControlTest` dans `core/tests.py`) :

- Anonyme → toute URL de dashboard/action **redirige vers la connexion** (302).
- Patient → les espaces médicaux (`/urgences/`, `/dmp/dashboard/`, `/dmp/patients/`,
  `/super/*`) redirigent vers son dashboard ou 404.
- Infirmier / Médecin / Admin → les pages `/super/*` **redirigent** vers leur dashboard.
- Super admin → les pages hôpital/médicales (candidatures, personnel, patients,
  urgences, DMP) **redirigent** vers `/dashboard/`.

---

## 4. Démarrage local

### 4.1 Simulation (venv `venv\` — prêt pour démo sans installer dlib)

```powershell
# depuis le dossier du projet
& ".\venv\Scripts\python.exe" manage.py migrate
& ".\venv\Scripts\python.exe" manage.py seed_data
& ".\venv\Scripts\python.exe" manage.py seed_demo
& ".\venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
```

- Ouvrir **http://127.0.0.1:8000/** (portail de connexion)
- Mode affiché : **Mode démo** (simulation déterministe par hash perceptuel).

### 4.2 Moteur RÉEL (env micromamba/conda-forge)

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\mamba-root"
& "C:\Users\hortense\micromamba\micromamba.exe" run -p "C:\Users\hortense\envs\medshare-fr" python manage.py migrate
& "C:\Users\hortense\micromamba\micromamba.exe" run -p "C:\Users\hortense\envs\medshare-fr" python manage.py seed_data
& "C:\Users\hortense\micromamba\micromamba.exe" run -p "C:\Users\hortense\envs\medshare-fr" python manage.py seed_demo
& "C:\Users\hortense\micromamba\micromamba.exe" run -p "C:\Users\hortense\envs\medshare-fr" python manage.py runserver 127.0.0.1:8000
```

Mode affiché : **Moteur réel (dlib)**.

### 4.3 Comptes de démonstration (mot de passe commun : `Demo@2026`)

| Profil | E-mail | Connexion cible |
|---|---|---|
| Super administrateur | `demo.superadmin@medshare.cm` | `/admin/` (avec 2FA) + dashboard `/dashboard/` |
| Administrateur hospitalier | `admin.yaounde@medshare.cm` | Dashboard personnel |
| Médecin | `dr.ngono@medshare.cm` | Dashboard personnel |
| Infirmier | `inf.fouda@medshare.cm` | Dashboard personnel |
| Patient 1 | `patient1@medshare.cm` | Lien `/compte/acces/<jeton>/` (jeton unique) |
| Patient 2 | `patient2@medshare.cm` | Lien `/compte/acces/<jeton>/` (jeton unique) |

> Le jeton patient est renouvelé à chaque connexion : après s'être connecté en
> tant que patient, l'URL d'accès change. C'est voulu (isolation).

---

## 5. Moteur de reconnaissance faciale

`facial_recognition/__init__.py` expose :

- `MODE_RECHERCHE` = `'reel'` si `face_recognition` + `dlib` importables, sinon `'simulation'`.
- `MODE_LIBELLE` : libellé affiché dans l'interface.
- `ServiceReconnaissanceFaciale` : `rechercher_correspondance(photo_path, seuil)` → top 5, seuil 60 %.
- Conversion : `confiance = (1 − distance) * 100` ; **seuil 60 % ⇔ distance max 0,40**.
- Garanties : score borné [0,100], calculé sur le contenu réel (jamais aléatoire),
  toujours une **validation médecin** avant fusion DUT→DMP.

Bon à savoir : la nuance « perceptuelle / dlib » n'apparaît plus dans l'interface
(demandé lors de la soutenance) ; le libellé reste un badge court
« Moteur réel (dlib) » / « Mode démo ».

**Comment forcer un mode ?** Il n'y a pas à configurer : le mode est détecté à
l'import. Pour forcer la simulation, retirez `dlib`/`face_recognition` de
l'environnement, ou surchargez au démarrage : `MODE_RECHERCHE='simulation'` remplace
la valeur dans vos scripts/CLI.

---

## 6. Configuration (.env) et base de données

`.env.example` → copier vers `.env`. Variables lues par `medshare/settings.py` :

| Variable | Rôle | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Django | dev (à changer en prod) |
| `DEBUG` | `True`/`False` | `False` |
| `ALLOWED_HOSTS` | Hôtes autorisés (virgule) | si vide + DEBUG → localhost |
| `DB_ENGINE` | `sqlite` / `postgresql` / `mysql` | `sqlite` si DEBUG sinon `postgresql` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Connexion BDD | — |
| `STATIC_ROOT`, `MEDIA_ROOT` | Chemins statiques/médias | `staticfiles/`, `media/` |
| `EMAIL_HOST*` | SMTP (si rempli → SMTP, sinon console) | backend console |
| `DEFAULT_FROM_EMAIL` | Expéditeur | MedShare |

- **MySQL** : le réglage `DB_ENGINE=mysql` active automatiquement
  `pymysql.install_as_MySQLdb()` (`pip install PyMySQL`) → utilisable sur
  PythonAnywhere sans compilation de `mysqlclient`.
- **PostgreSQL** : `OPTIONS = {'sslmode': 'require'}` (Supabase/Neon, etc.).

---

## 7. Ce qui peut être modifié et comment

| Élément | Où | Comment |
|---|---|---|
| Seuil de reconnaissance | `facial_recognition/__init__.py` | `SEUIL_DEFAUT = 60.0`, `TOP_K = 5` ; le seuil affiché est retiré de l'UI, mais reste la référence de filtrage. |
| Libellés d'interface courts | `templates/urgences/*.html`, `templates/registration/login.html`, `base.html` | Texte directement éditables ; badges « Moteur réel (dlib) » / « Mode démo » dans `correspondances.html` (lignes ~20-21). |
| Matrice d'accès | `users/decorators.py` + attributs de décoration dans chaque vue | Modifier une liste de rôles d'un décorateur change qui a le droit d'accéder à la vue. |
| Rôles disponibles | `users/models.py` + `seed_demo.py` | Les rôles sont des enregistrements : `Role(nomRole='Médecin')`, etc. |
| Formules / abonnements | Modèle `Formule`, `Abonnement` (admin Django ou `seed_data`) | Prix, durée, nb utilisateurs max, nb DMP max. |
| Statuts | `urgences/models.py`, `establishments/models.py` | Clés de choix (`EN_ATTENTE`, `CORRESPONDANCE_TROUVEE`, `EN_ATTENTE_PROLONGEE`, …). |
| Politique de clôture DUT | `urgences/services.py`, `urgences/management/commands/politique_dut.py` | Constantes `DUREE_72H`, `STATUT_CIBLE` ; commande à planifier (ou appelée au login). |
| Renvois de notification DMP | `dmp/models.py` | `RENVOIS_MAX = 3`, `DELAI_RENVOI = timedelta(minutes=5)` sur `AccesDMP` ; bouton dans les écrans soignants (`dmp/views.py` `renvoyer_notification_acces`). |
| Cooldown 2FA | `users/views.py` | `DELAI_2FA_RENVOI = timedelta(seconds=60)`, `CODE_2FA_RENVOIS_MAX = 3`. |
| Session unique | `users/middleware.py`, `users/views.py` (`MedShareLoginView`) | Clé `session_active_key` générée à chaque login ; middleware `SessionUniqueMiddleware` (placé après `MessageMiddleware`). |
| Historique des accès patient | `dmp/views.py` (`mon_acces_historique`), `templates/dmp/mon_acces_historique.html` | Liste blanche `ACCES_DMP_ACTIONS` ; modèle réutilisable. |
| Messages flash | `core/templates/core/base_dynamic.html`, `users/middleware.py`, `urgences/views.py`, `establishments/views.py`, `users/decorators.py` | **Flash globalisé** dans la coquille `base_dynamic.html` ; chaînes `messages.success/warning/error/info`. |
| Moteur BDD | `medshare/settings.py` | Variable `DB_ENGINE` (sqlite/postgresql/mysql). |
| E-mails | `medshare/settings.py` + `core/notifications.py` | Renseigner le SMTP dans `.env`, ou garder le backend console pour la démo. |
| Thème / PWA | `static/css/style.css`, `static/`, `core/templates/core/base_dynamic.html` | Tailwind CDN ; icônes Material Symbols ; manifest + service-worker. |
| Dashboard super admin | `core/views.py` (`_contexte_superadmin`), `core/templates/core/dashboard_superadmin.html` | Compteurs, « Gestion globale », journal récent limité à 5. |
| Création d'admin hôpital | `core/views.py` (`super_etablissements` + `_creer_admin`) | Fusionné avec la création d'établissement (« Établissements ») ; matricule `ADM-AAAAmmjj-XXXX`, rôle `Administrateur`, identifiants envoyés par e-mail. |

> Règle d'or : pour modifier le comportement métier, chercher d'abord le
> décorateur / la constante dans `users/decorators.py` et
> `facial_recognition/__init__.py`, c'est là que se concentre la logique
> transversale.

---

## 8. Scénarios de démonstration complets

### Scénario A — Vérification rapide de l'environnement
1. Lancer (voir §4), `python manage.py check` → **no issues**.
2. `python manage.py test` → **179 tests OK (6 ignorés)**.
3. Ouvrir `/` (portail de connexion) → champ e-mail + mot de passe.

### Scénario B — Parcours candidat → compte personnel (sans compte préalable)
1. Depuis `/`, cliquer **« Soumettre une demande »**.
2. Remplir le formulaire (nom, prénom, e-mail, téléphone, établissement, rôle demandé).
   Envoyer → page de confirmation avec la **référence `#ID`**.
3. Retour `/` → **« Suivre ma demande »** → saisir l'e-mail → statut **En attente**.
4. Se connecter en **Administrateur hospitalier** → « Candidatures » → « Examiner ».
   Vérifier le registre → **Accepter** (choisir le rôle).
   → Un e-mail d'identifiants est émis (backend console : visible dans le terminal) +
   message flash avec e-mail / matricule / mot de passe provisoire.
5. Se déconnecter ; se connecter avec le compte créé → le système impose le
   **changement de mot de passe** à la première connexion.

### Scénario C — Accueil d'un patient (création + DMP)
1. Infirmier → « Rechercher patient » → « Enregistrer un patient » : photo de
   profil (obligatoire — sert à la reconnaissance), identité, contacts d'urgence.
   → DMP `DMP-…` créé automatiquement + JournalAudit `CRÉATION_PATIENT`.
2. La photo sert désormais de référence faciale (encodée à la volée au moment de
   la recherche, mode réel).

### Scénario D — Urgence : DUT → identification faciale → médecin → fiche vitale
1. **Infirmier** → « Urgences » → « Nouveau DUT » : photo frontale du patient
   inconscient (obligatoire) + informations initiales → « Créer le DUT ».
   La **recherche faciale se lance automatiquement** (`_lancer_recherche_faciale`).
2. Résultats : page « Correspondances » (top 5, seuil 60 %). Moteur réel :
   distances `dlib` réelles (exemple vérifié : même photo → distance `0.0` →
   confiance `100 %`). Vue « Identification » (veille) liste les DUT en attente.
3. **Médecin** → « Correspondances » → choisir → **« Confirmer l'identité »**
   (POST, rôle Médecin uniquement) → fusion partielle vers le DMP du patient.
4. **Fiche vitale / Break Glass** : groupe sanguin, allergies, antécédents
   disponibles depuis le DMP une fois l'identité confirmée.
5. Triage (priorité C1/C2/C3), constantes vitales (FC, TA, SpO2, température), clôture.
6. Traçabilité : chaque étape crée une entrée `JournalAudit`
   (action, description, IP, utilisateur, établissement).

### Scénario E — Super admin (éditeur SaaS)
1. Connexion `demo.superadmin@medshare.cm` → redirection `/admin/` ← **2FA**
   (code à 6 chiffres, affiché pour la démo). Saisir le code.
2. `/dashboard/` → cartes : Établissements, Abonnements actifs, Utilisateurs, journal global.
3. **« Administrateurs »** → créer un compte Administrateur lié à un hôpital :
   e-mail, nom, prénom, établissement, mot de passe (ou généré).
   → Matricule `ADM-…`, compte forcé à changer son mot de passe à la 1ʳᵉ connexion.
4. **« Abonnements »** : liste des abonnements + formulés disponibles.
5. **« Rapports »** : journal d'audit **global** (tous les hôpitaux) — aucune
   modification possible (même dans `/admin/`, `JournalAuditAdmin` est read-only).
6. **Démonstration des blocages** : connecté en super admin, taper
   `/urgences/`, `/dmp/patients/`, `/etablissements/candidatures/`,
   `/etablissements/personnel/` → **redirection vers `/dashboard/`**
   (le super admin ne fait PAS le travail de l'administrateur d'hôpital ni du
   personnel médical).

### Scénario F — Patients
1. Connecter `patient1@medshare.cm` (jeton dans la sortie de `seed_demo`).
2. Dashboard patient : DMP, « Mes ordonnances », « Mon historique », **« Historique
   des accès »** (qui a consulté le dossier : nom, rôle, établissement, action, date).
3. Tentative d'accès croisé → 404 (URL `/dmp/patients/<autre_pk>/`,
   `/dmp/mes-ordonnances/<autre_pk>/`).

### Scénario G — Addendum 4 : session unique, notifications et politique DUT
1. **Session unique (T4)** : connecter un Médecin sur un navigateur A, puis sur un
   navigateur B (autre appareil). Recharger A → il est **déconnecté** avec le message
   « Votre session a été remplacée par une connexion plus récente… » ; B continue
   normalement. L'événement est tracé dans le journal (`SESSION_REMPLACEE`).
2. **Changement de mot de passe (P1)** : compte forcé (1ʳᵉ connexion), modifier le
   mot de passe → page « Mot de passe mis à jour » → bouton qui ramène **directement**
   au tableau de bord (plus d'écran de login intermédiaire).
3. **Notifications (T2)** : un soignant consulte un patient non approuvé →
   demande créée + e-mail au patient ; l'écran affiche « Renvoyer la notification ».
   Au-delà de 3 renvois (ou moins de 5 min après le dernier), le **message flash**
   explique le blocage. Sous 2FA, deux demandes de code rapprochées affichent
   « Patientez une minute ».
4. **Politique DUT (T3)** : `python manage.py politique_dut` → tout DUT actif de
   plus de 72 h sans correspondance confirmée passe en **En attente prolongée**
   (jamais de clôture automatique). Dans `detail_dut.html`, seule un **Médecin**
   peut clôturer définitivement, avec **motif obligatoire**.

---

## 9. Déploiement

### 9.1 Docker / Compose (VPS)

Prérequis : un hôte avec Docker Engine (VPS classique, machine de CI — **pas** la
machine locale où Docker Desktop ne démarre pas).

```bash
cp .env.example .env        # puis édit : SECRET_KEY, ALLOWED_HOSTS, POSTGRES_PASSWORD
docker compose up --build -d
docker compose ps
```

- `http://<IP_DU_SERVEUR>:8000/` → portail de connexion.
- PostgreSQL 16 dans un volume `db_data`, média/statiques dans
  `media_data`/`static_data` (persistants).
- `entrypoint.sh` fait `migrate` → `collectstatic` → démarre **gunicorn**
  (`--workers 3 --timeout 180`, le timeout long est indispensable pour l'inférence
  faciale au premier chargement).
- Le moteur est l'image `mambaorg/micromamba:2.9.0-debian13` avec
  `dlib=20.0.1` **conda-forge** (win-64 ET linux-64, python 3.14) :
  l'image web est reproductible partout, sans MSI ni compilation.
- CI : `.github/workflows/ci.yml` exécute déjà les tests + un smoke « reel »
  dans un conteneur Linux → c'est la **preuve de build** à présenter.
- Pour SSL : placer un reverse-proxy (Caddy/Nginx) devant le port 8000.

### 9.2 PythonAnywhere (procédure complète)

PythonAnywhere (PA) est le choix recommandé pour ce type de projet :
PHP/Django complet, MySQL gratuit, consoles Bash, plan Hacker/Freelance à petit prix.

**Étape 1 — Compte et récupération du code**
1. Créer un compte sur pythonanywhere.com (plan gratuit ou Hacker).
2. Onglet **Files** → importer le zip du projet dans `/home/<user>/Projet_MedShare`,
   ou dans une console Bash : `git clone <url> Projet_MedShare`.
3. Confirmer que `manage.py` est à la racine (`/home/<user>/Projet_MedShare/manage.py`).

**Étape 2 — Environnement virtuel**
Dans l'onglet **Consoles** → **Bash** :
```bash
cd ~/Projet_MedShare
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools==80.9.0
```

**Étape 3 — Dépendances**
```bash
pip install Django==6.1 pillow python-dotenv gunicorn PyMySQL
# Moteur réel (si compatible PA — sinon le mode démo est automatique) :
pip install --no-deps face-recognition
pip install "face_recognition_models @ https://github.com/ageitgey/face_recognition_models/archive/refs/heads/master.tar.gz"
pip install scipy click numpy
pip install dlib        # -> réussit seulement si une roue manylinux existe pour py3.12
python -c "import dlib, face_recognition; print('MOTEUR REEL OK')"
```
> Si `dlib` échoue (compilation impossible sans cmake sur PA), ce n'est pas bloquant :
> le mode passe en **simulation** (« Mode démo ») et la démo reste complète.
> Le réglage `MODE_RECHERCHE` se fait automatiquement à l'import.

**Étape 4 — Base de données (MySQL, gratuit)**
1. Onglet **Databases** → créer une base (ex. `$user$medshare`) → noter
   utilisateur/mot de passe/host (`$user.mysql.pythonanywhere-services.com`).
2. Fichier `.env` dans le projet :
```ini
SECRET_KEY=<une-longue-chaine>
DEBUG=False
ALLOWED_HOSTS=<user>.pythonanywhere.com,www.<user>.pythonanywhere.com
DB_ENGINE=mysql
DB_NAME=$user$medshare
DB_USER=$user
DB_PASSWORD=<mot de passe MySQL>
DB_HOST=$user.mysql.pythonanywhere-services.com
DB_PORT=3306
STATIC_ROOT=/home/<user>/Projet_MedShare/staticfiles
MEDIA_ROOT=/home/<user>/Projet_MedShare/media
```

**Étape 5 — Migrations, statiques, seed**
```bash
source ~/Projet_MedShare/venv/bin/activate
cd ~/Projet_MedShare
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_data
python manage.py seed_demo
```
(MySQL impose une table `auth` ; les index déjà en place sont compatibles.)

**Étape 6 — Fichier WSGI**
Dans l'onglet **Web** → votre app → **WSGI configuration file**, coller :
```python
import os, sys
BASE = '/home/<user>/Projet_MedShare'
if BASE not in sys.path:
    sys.path.append(BASE)
os.environ['DJANGO_SETTINGS_MODULE'] = 'medshare.settings'
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

**Étape 7 — Réglages Web**
- Python version : celle du venv (3.12). Virtualenv : `/home/<user>/Projet_MedShare/venv/`.
- **Static files** : URL `/static/` → répertoire `/home/<user>/Projet_MedShare/staticfiles/`.
- **Static files (médias)** : URL `/media/` → `/home/<user>/Projet_MedShare/media/`.
- **Force HTTPS** : oui. **Reload** le Web app.

**Étape 8 — Vérification**
Ouvrir `https://<user>.pythonanywhere.com/` → portail de connexion.
Les e-mails restent en backend console (visibles dans les logs serveur) tant
qu'aucun SMTP n'est configuré ; pour de vrais e-mails, ajouter les variables
`EMAIL_HOST*` dans `.env` puis reload.

### 9.3 Vercel (analyse et limites)

> **Recommandation : NE PAS déployer l'application complete sur Vercel.**
> C'est un environnement serverless pensé pour le JAMstack : fonction temporaire,
> pas de système de fichiers persistant pour `/media/` (les photos uploadées
> disparaîtraient au prochain événement), limite de temps d'exécution (60 s par
> défaut) inadaptée à l'inférence dlib (chargement des poids ~100 Mo + encodage),
> et pas de PostgreSQL managé native (il faudrait une base externe Supabase/Neon).

Si vous tenez malgré tout à une **aperçu publier du mode démo (simulation)**,
l'architecture technique serait :
1. `vercel.json` :
```json
{
  "builds": [
    { "src": "vercel_app.py", "use": "@vercel/python", "config": { "maxDuration": 60 } },
    { "src": "staticfiles/**", "use": "@vercel/static" }
  ],
  "routes": [
    { "src": "/static/(.*)", "dest": "staticfiles/$1" },
    { "src": "(.*)", "dest": "vercel_app.py" }
  ]
}
```
2. `vercel_app.py` :
```python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'medshare.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```
3. Base externe (Supabase) via `DB_ENGINE=postgresql` + variables, `DEBUG=False`.
4. Constraintes irréductibles à assumer : **pas de médias persistants** (les
   photos de patients et de DUT ne survivent pas), moteur dlib non réaliste en
   serverless, `ALLOWED_HOSTS` doit contenir `*.vercel.app`.

⇒ La réalisation du « vrai » déploiement se fait avec **PythonAnywhere (§9.2)**
ou **n'importe quel VPS + Docker (§9.1)**. Vercel est présenté ici pour la
complétude de la soutenance et non comme choix de production.

---

## 10. Dépannage (FAQ)

| Problème | Cause / Solution |
|---|---|
| `Failed to create Custom Action Server` / MSI 1603 | Installateur Windows cassé sur ce PC (360 Total Security). **Ce chemin (MSVC/dlib-from-source) est abandonné.** Utiliser l'environnement micromamba/conda-forge (cf. `doc/face_recognition_reel.md`). |
| `Distutils…` / `pkg_resources` | Installer `setuptools==80.9.0` (setuptools ≥ 81 retire `pkg_resources`, requis par `face_recognition_models`). |
| `face_recognition_models` absent en mode réel | **Ne jamais installer le paquet PyPI `face-recognition-models` (stub)** ; installer les vrais modèles depuis le dépôt GitHub (voir §9.2/Étape 3 ou Dockerfile). |
| « Aucun visage détecté » | Photo non frontale / floue / sans contraste. Reprendre une photo frontale éclairée. |
| Docker Desktop ne démarre pas (Windows) | Moteur WSL2 docker-desktop « Stopped » sur cette machine → utiliser GitHub Actions ou un VPS pour la build. |
| Connexion patient impossible | Le jeton change à chaque connexion : récupérer la nouvelle URL après `seed_demo` ou se reconnecter au portail. |
| Page blanche après déploiement | Vérifier `ALLOWED_HOSTS`, le WSGI (§9.2), `python manage.py check`, et les logs (PA : Web tab → error.log). |
| MySQL sur PythonAnywhere | `DB_ENGINE=mysql` + `pip install PyMySQL` (shim automatique dans `settings.py`). |

---

## 11. Tests automatisés

```powershell
# Env simulation (rapide) :
& ".\venv\Scripts\python.exe" manage.py test

# Env moteur réel :
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\mamba-root"
& "C:\Users\hortense\micromamba\micromamba.exe" run -p "C:\Users\hortense\envs\medshare-fr" python manage.py test
```

Suite : **179 tests — OK (6 ignorés, état 2026-09)**. Couvre notamment :
- flux candidat → acceptation → e-mail → 1ʳᵉ connexion avec changement de mot de passe ;
- parcours DUT → reconnaissance (mode réel mocké + simulation) ;
- **matrice RBAC** (`RBACTest`, `SuperAdminScopeTest`, `URLAccessControlTest`) :
  accès anonyme refusé partout, isolation patient, blocage du super admin sur les
  tâches hôpital/médicales, création d'administrateur par le super admin,
  journal d'audit en lecture seule ;
- reconnaissance faciale (`facial_recognition/tests.py`, 35 tests) : conversion
  distance⇄confiance, seuil, top K, robustesse aux marques superficielles ;
- multi-plateforme SaaS (`AbonnementSaaSFTest`) ;
- **addendum 4** : `ChangementMotDePasseFlowTest`, `SessionUniqueActiveTest` (2 appareils,
  journal, clé renouvelée), `Renvoi2FACooldownTest` (délai anti-spam 2FA),
  `AccesDMPNotificationTest` (notification dès la création, 3 renvois max, blocage),
  `MonAccesHistoriqueTest` (qui/quand/quoi, sans e-mail ni id interne),
  `PolitiqueClotureDUTTest` (72 h → `EN_ATTENTE_PROLONGEE`, jamais de clôture auto,
  clôture manuelle avec motif).