from django.db import models


# ──────────────────────────────────────────────
# Etablissement
# ──────────────────────────────────────────────
class Etablissement(models.Model):
    idEtablissement = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=200, verbose_name='Nom de l\'établissement')
    adresse = models.CharField(max_length=255, verbose_name='Adresse')
    telephone = models.CharField(max_length=20, verbose_name='Téléphone')
    email = models.EmailField(verbose_name='Email de contact')
    statut = models.CharField(
        max_length=20,
        choices=[
            ('ACTIF', 'Actif'),
            ('INACTIF', 'Inactif'),
            ('SUSPENDU', 'Suspendu'),
        ],
        default='ACTIF',
        verbose_name='Statut'
    )
    # Motif de la suspension : ABONNEMENT_EXPIRE (automatique) ou une
    # décision manuscrite du Super Admin (SUSPENSION_MANUELLE).
    motifSuspension = models.CharField(
        max_length=50, blank=True, default='', verbose_name='Motif de la suspension'
    )

    class Meta:
        verbose_name = 'Établissement'
        verbose_name_plural = 'Établissements'

    def __str__(self):
        return self.nom

    def modifier_informations(self, **kwargs):
        for attr, value in kwargs.items():
            if hasattr(self, attr) and attr != 'idEtablissement':
                setattr(self, attr, value)
        self.save()

    def valider(self):
        self.statut = 'ACTIF'
        self.save(update_fields=['statut'])

    def suspendre(self, motif=''):
        self.statut = 'SUSPENDU'
        self.motifSuspension = motif or 'SUSPENSION_MANUELLE'
        self.save(update_fields=['statut', 'motifSuspension'])

    def reactiver(self):
        """Réactivation explicite (Super Admin) : lève toute suspension,
        quel qu'en soit le motif."""
        self.statut = 'ACTIF'
        self.motifSuspension = ''
        self.save(update_fields=['statut', 'motifSuspension'])


# ──────────────────────────────────────────────
# Candidature
# Le Candidat n'a PAS de compte MedShare.
# Il soumet ses informations via ce modèle.
# ──────────────────────────────────────────────
class Candidature(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = 'EN_ATTENTE', 'En attente'
        ACCEPTEE = 'ACCEPTEE', 'Acceptée'
        REFUSEE = 'REFUSEE', 'Refusée'

    idCandidature = models.AutoField(primary_key=True)

    # Informations du candidat (pas de FK vers User — il n'a pas de compte)
    nom = models.CharField(max_length=100, verbose_name='Nom')
    prenom = models.CharField(max_length=100, verbose_name='Prénom')
    email = models.EmailField(verbose_name='Adresse e-mail')
    telephone = models.CharField(max_length=20, blank=True, verbose_name='Téléphone')

    etablissement = models.ForeignKey(Etablissement, on_delete=models.CASCADE,
                                       related_name='candidatures',
                                       verbose_name='Établissement')
    roleDemande = models.CharField(max_length=50, verbose_name='Rôle demandé')
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE,
                               verbose_name='Statut')
    dateSoumission = models.DateTimeField(auto_now_add=True, verbose_name='Date de soumission')
    dateDecision = models.DateTimeField(null=True, blank=True, verbose_name='Date de décision')
    motifRefus = models.TextField(blank=True, verbose_name='Motif du refus')

    class Meta:
        verbose_name = 'Candidature'
        verbose_name_plural = 'Candidatures'

    def __str__(self):
        return f"{self.prenom} {self.nom} → {self.etablissement} ({self.get_statut_display()})"

    def accepter(self):
        from django.utils import timezone
        self.statut = self.Statut.ACCEPTEE
        self.dateDecision = timezone.now()
        self.save(update_fields=['statut', 'dateDecision'])

    def refuser(self, motif=''):
        from django.utils import timezone
        self.statut = self.Statut.REFUSEE
        self.dateDecision = timezone.now()
        self.motifRefus = motif
        self.save(update_fields=['statut', 'dateDecision', 'motifRefus'])

    def annuler(self):
        from django.utils import timezone
        self.statut = self.Statut.REFUSEE
        self.dateDecision = timezone.now()
        self.motifRefus = 'Candidature annulée par le candidat'
        self.save(update_fields=['statut', 'dateDecision', 'motifRefus'])


# ──────────────────────────────────────────────
# Formule (offre SaaS)
# ──────────────────────────────────────────────
class Formule(models.Model):
    idFormule = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=100, verbose_name='Nom de la formule')
    description = models.TextField(blank=True, verbose_name='Description')
    prix = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Prix (FCFA)')
    dureeMois = models.PositiveIntegerField(verbose_name='Durée (mois)')
    nbUtilisateursMax = models.PositiveIntegerField(verbose_name='Nombre max d\'utilisateurs')
    nbDMPMax = models.PositiveIntegerField(verbose_name='Nombre max de DMP')

    class Meta:
        verbose_name = 'Formule'
        verbose_name_plural = 'Formules'

    def __str__(self):
        return f'{self.nom} — {self.prix} FCFA / {self.dureeMois} mois'


# ──────────────────────────────────────────────
# Abonnement (un établissement ↔ une formule)
# ──────────────────────────────────────────────
class Abonnement(models.Model):
    class Statut(models.TextChoices):
        ACTIF = 'ACTIF', 'Actif'
        SUSPENDU = 'SUSPENDU', 'Suspendu'
        EXPIRE = 'EXPIRE', 'Expiré'

    idAbonnement = models.AutoField(primary_key=True)
    etablissement = models.OneToOneField(Etablissement, on_delete=models.CASCADE,
                                          related_name='abonnement',
                                          verbose_name='Établissement')
    formule = models.ForeignKey(Formule, on_delete=models.PROTECT,
                                 related_name='abonnements', verbose_name='Formule')
    dateDebut = models.DateField(verbose_name='Date de début')
    dateFin = models.DateField(verbose_name='Date de fin')
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.ACTIF,
                               verbose_name='Statut')
    datePaiement = models.DateTimeField(null=True, blank=True, verbose_name='Date du paiement')

    class Meta:
        verbose_name = 'Abonnement'
        verbose_name_plural = 'Abonnements'

    def __str__(self):
        return f'{self.etablissement} — {self.formule.nom} ({self.get_statut_display()})'

    def activer(self):
        self.statut = self.Statut.ACTIF
        self.save(update_fields=['statut'])

    def suspendre(self):
        self.statut = self.Statut.SUSPENDU
        self.save(update_fields=['statut'])

    def expirer(self):
        """Expiration automatique (date de fin dépassée sans renouvellement)."""
        self.statut = self.Statut.EXPIRE
        self.save(update_fields=['statut'])

    def renouveler(self, nouvelle_date_fin, date_debut=None):
        """Renouvellement de l'abonnement (paiement simulé).
        Prolonge la période, repasse en ACTIF et journalise.
        L'établissement n'est réactivé ici QUE s'il avait été suspendu pour
        un abonnement expiré — jamais pour une décision manuscrite."""
        from django.utils import timezone
        if date_debut is None:
            date_debut = timezone.now().date()
        self.dateDebut = date_debut
        self.dateFin = nouvelle_date_fin
        self.datePaiement = timezone.now()
        self.statut = self.Statut.ACTIF
        self.save(update_fields=['dateDebut', 'dateFin', 'datePaiement', 'statut'])

    def simuler_paiement(self):
        from django.utils import timezone
        self.datePaiement = timezone.now()
        self.statut = self.Statut.ACTIF
        self.save(update_fields=['datePaiement', 'statut'])
