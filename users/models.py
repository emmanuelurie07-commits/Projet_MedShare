from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UtilisateurManager(BaseUserManager):
    def create_user(self, email, nom, prenom, password=None, **extra_fields):
        if not email:
            raise ValueError('L\'adresse e-mail est obligatoire')
        email = self.normalize_email(email)
        user = self.model(email=email, nom=nom, prenom=prenom, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, nom, prenom, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Le super administrateur doit avoir is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Le super administrateur doit avoir is_superuser=True')
        return self.create_user(email, nom, prenom, password, **extra_fields)


# ──────────────────────────────────────────────
# Permission
# ──────────────────────────────────────────────
class Permission(models.Model):
    idPermission = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=150, unique=True, verbose_name='Nom')
    description = models.TextField(blank=True, verbose_name='Description')

    class Meta:
        verbose_name = 'Permission'
        verbose_name_plural = 'Permissions'

    def __str__(self):
        return self.nom


# ──────────────────────────────────────────────
# Role
# ──────────────────────────────────────────────
class Role(models.Model):
    idRole = models.AutoField(primary_key=True)
    nomRole = models.CharField(max_length=50, unique=True, verbose_name='Nom du rôle')
    description = models.TextField(blank=True, verbose_name='Description')
    permissions = models.ManyToManyField(Permission, blank=True, related_name='roles',
                                         verbose_name='Permissions')

    class Meta:
        verbose_name = 'Rôle'
        verbose_name_plural = 'Rôles'

    def __str__(self):
        return self.nomRole

    def get_permissions(self):
        return self.permissions.all()

    def attribuer_permission(self, permission):
        self.permissions.add(permission)


# ──────────────────────────────────────────────
# Utilisateur — modèle concret de base
# Hérite d'AbstractBaseUser + PermissionsMixin.
# Personnel et Patient héritent de cette table.
# ──────────────────────────────────────────────
class Utilisateur(AbstractBaseUser, PermissionsMixin):
    nom = models.CharField(max_length=100, verbose_name='Nom')
    prenom = models.CharField(max_length=100, verbose_name='Prénom')
    email = models.EmailField(unique=True, verbose_name='Adresse e-mail')
    telephone = models.CharField(max_length=20, blank=True, verbose_name='Téléphone')
    dateCreation = models.DateTimeField(default=timezone.now, verbose_name='Date de création')
    statutCompte = models.BooleanField(default=True, verbose_name='Compte actif')
    photoProfil = models.ImageField(upload_to='profiles/', null=True, blank=True,
                                     verbose_name='Photo de profil')

    is_staff = models.BooleanField(default=False, verbose_name='Accès admin Django')
    is_superuser = models.BooleanField(default=False, verbose_name='Super administrateur')
    date_joined = models.DateTimeField(default=timezone.now, verbose_name='Date d\'inscription')

    jeton_acces = models.CharField(
        max_length=64, blank=True, editable=False,
        verbose_name='Jeton d\'accès personnel'
    )

    # T4 — une seule session active par compte : stocke la clé de session
    # Django autorisée. Toute autre session est fermée avec un message
    # explicite lors de son prochain accès (SessionUniqueMiddleware).
    session_active_key = models.CharField(
        max_length=64, blank=True, default='', editable=False,
        verbose_name='Session active'
    )

    # ── Sécurité des connexions ────────────────────────────────────────
    # Échecs consécutifs de connexion : au-delà du seuil (5), le compte est
    # verrouillé pendant 15 minutes (politique de verrouillage T8.2).
    nbEchecsConnexion = models.PositiveIntegerField(
        default=0, verbose_name='Échecs de connexion consécutifs')
    verrouillageJusqua = models.DateTimeField(
        null=True, blank=True, verbose_name='Compte verrouillé jusqu\'à')

    objects = UtilisateurManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nom', 'prenom']

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'

    def __str__(self):
        return f"{self.prenom} {self.nom}"

    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith('pbkdf2_'):
            from django.contrib.auth.hashers import make_password
            self.password = make_password(self.password)
        if not self.jeton_acces:
            self.regenerer_jeton(commit=False)
        super().save(*args, **kwargs)

    def regenerer_jeton(self, commit=True):
        """Génère un nouveau jeton d'accès personnel (renouvelé au login).
        Le jeton n'est jamais exposé dans les URLs publiques et
        devient invalide pour toute session autre que celle du propriétaire."""
        import secrets
        self.jeton_acces = secrets.token_urlsafe(48)
        if commit:
            self.save(update_fields=['jeton_acces'])
        return self.jeton_acces

    def definir_mot_de_passe(self, mot_de_passe):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(mot_de_passe)
        self.save(update_fields=['password'])

    def verifier_mot_de_passe(self, mot_de_passe):
        return self.check_password(mot_de_passe)

    def modifier_mot_de_passe(self, ancien, nouveau):
        if not self.verifier_mot_de_passe(ancien):
            return False
        self.definir_mot_de_passe(nouveau)
        return True

    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()

    def get_short_name(self):
        return self.prenom


# ──────────────────────────────────────────────
# Personnel
# ──────────────────────────────────────────────
class Personnel(Utilisateur):
    idPersonnel = models.AutoField(primary_key=True)
    matricule = models.CharField(max_length=50, unique=True, verbose_name='Matricule')
    dateAffectation = models.DateField(null=True, blank=True, verbose_name='Date d\'affectation')
    statutProfessionnel = models.CharField(
        max_length=20,
        choices=[
            ('ACTIF', 'Actif'),
            ('INACTIF', 'Inactif'),
            ('CONGE', 'En congé'),
            ('SUSPENDU', 'Suspendu'),
        ],
        default='ACTIF',
        verbose_name='Statut professionnel'
    )
    role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='personnel', verbose_name='Rôle'
    )
    etablissement = models.ForeignKey(
        'establishments.Etablissement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='personnel', verbose_name='Établissement'
    )
    doitChangerMotDePasse = models.BooleanField(
        default=False, verbose_name='Doit changer son mot de passe'
    )

    # Champs hérités de Utilisateur renommés pour la multi-table inheritance
    utilisateur_ptr = models.OneToOneField(
        Utilisateur, on_delete=models.CASCADE,
        parent_link=True, related_name='personnel_child'
    )

    class Meta:
        verbose_name = 'Personnel'
        verbose_name_plural = 'Personnel'

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.matricule})"

    def consulter_profil(self):
        return {
            'nom': self.nom,
            'prenom': self.prenom,
            'email': self.email,
            'matricule': self.matricule,
            'statut': self.statutProfessionnel,
            'role': self.role.nomRole if self.role else None,
        }

    def mettre_a_jour_profil(self, **kwargs):
        for attr, value in kwargs.items():
            if hasattr(self, attr) and attr not in ('matricule', 'idPersonnel'):
                setattr(self, attr, value)
        self.save()

    def a_permission(self, permission_nom):
        if self.role:
            return self.role.permissions.filter(nom=permission_nom).exists()
        return False

    @property
    def est_medecin(self):
        return self.role and self.role.nomRole == 'Médecin'

    @property
    def est_infirmier(self):
        return self.role and self.role.nomRole == 'Infirmier'

    @property
    def est_admin_hospital(self):
        return self.role and self.role.nomRole == 'Administrateur'

    @property
    def est_super_admin(self):
        # Super Admin natif Django (is_superuser) OU rôle applicatif
        # « Super Admin » créé par la migration de démarrage (addendum 3).
        return self.is_superuser or (
            self.role is not None and self.role.nomRole == 'Super Admin')


# ──────────────────────────────────────────────
# Patient
# ──────────────────────────────────────────────
class Patient(Utilisateur):
    idPatient = models.AutoField(primary_key=True)
    numeroPatient = models.CharField(max_length=50, unique=True, verbose_name='Numéro patient')
    dateNaissance = models.DateField(null=True, blank=True, verbose_name='Date de naissance')
    sexe = models.CharField(
        max_length=1,
        choices=[('M', 'Masculin'), ('F', 'Féminin'), ('A', 'Autre')],
        blank=True,
        verbose_name='Sexe'
    )
    adresse = models.TextField(blank=True, verbose_name='Adresse')
    niu = models.CharField(max_length=20, blank=True, verbose_name='NIU')
    numeroCNI = models.CharField(max_length=20, blank=True, verbose_name='Numéro CNI')

    # ── Sécurité des accès patient ───────────────────────────────────
    # Le patient doit changer son mot de passe à la première connexion,
    # comme tout personnel (cohérence de la politique de sécurité).
    doitChangerMotDePasse = models.BooleanField(
        default=True, verbose_name='Doit changer son mot de passe à la première connexion')
    # Code de confirmation (PIN) demandé au soignant avant une action sur
    # le dossier du patient identifié (consultation, ordonnance, triage…).
    codeConfirmation = models.CharField(
        max_length=6, blank=True, default='', verbose_name='Code de confirmation patient')

    # ── Données vitales (Break Glass) ─────────────────────────────────
    GROUPE_SANGUIN_CHOICES = [
        ('', '— Non renseigné'),
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-'),
    ]
    groupeSanguin = models.CharField(max_length=3, choices=GROUPE_SANGUIN_CHOICES,
                                      blank=True, default='', verbose_name='Groupe sanguin')
    allergies = models.TextField(blank=True, default='',
                                  verbose_name='Allergies (séparées par virgule)')
    antecedents = models.TextField(blank=True, default='',
                                    verbose_name='Antécédents / Pathologies chroniques')
    traitementEnCours = models.TextField(blank=True, default='',
                                          verbose_name='Traitement en cours')

    # Contact d'urgence principal (obligatoire)
    nomContactUrgencePrincipal = models.CharField(max_length=200, verbose_name='Nom contact urgence')
    telephoneContactUrgencePrincipal = models.CharField(max_length=20,
                                                         verbose_name='Téléphone contact urgence')
    lienContactUrgencePrincipal = models.CharField(max_length=50, verbose_name='Lien de parenté')

    # Contact d'urgence secondaire (facultatif)
    nomContactUrgenceSecondaire = models.CharField(max_length=200, blank=True,
                                                    verbose_name='Nom contact urgence secondaire')
    telephoneContactUrgenceSecondaire = models.CharField(max_length=20, blank=True,
                                                          verbose_name='Téléphone contact urgence secondaire')
    lienContactUrgenceSecondaire = models.CharField(max_length=50, blank=True,
                                                     verbose_name='Lien de parenté secondaire')

    utilisateur_ptr = models.OneToOneField(
        Utilisateur, on_delete=models.CASCADE,
        parent_link=True, related_name='patient_child'
    )

    class Meta:
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.numeroPatient})"

    @property
    def age(self):
        if not self.dateNaissance:
            return None
        from datetime import date
        today = date.today()
        return today.year - self.dateNaissance.year - (
            (today.month, today.day) < (self.dateNaissance.month, self.dateNaissance.day)
        )

    @property
    def liste_allergies(self):
        if not self.allergies:
            return []
        return [a.strip() for a in self.allergies.split(',') if a.strip()]

    @property
    def liste_antecedents(self):
        if not self.antecedents:
            return []
        return [a.strip() for a in self.antecedents.split(',') if a.strip()]

    def consulter_profil(self):
        return {
            'nom': self.nom,
            'prenom': self.prenom,
            'email': self.email,
            'numeroPatient': self.numeroPatient,
            'dateNaissance': self.dateNaissance,
            'sexe': self.sexe,
            'groupeSanguin': self.groupeSanguin,
            'allergies': self.allergies,
            'antecedents': self.antecedents,
        }
