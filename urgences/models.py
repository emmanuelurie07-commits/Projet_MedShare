from django.db import models


# ──────────────────────────────────────────────
# DUT — Dossier d'Urgence Temporaire
# Pour les patients inconnus / non identifiés.
# ──────────────────────────────────────────────
class DossierUrgenceTemporaire(models.Model):
    class Statut(models.TextChoices):
        ACTIF = 'ACTIF', 'Actif'
        EN_ATTENTE_PROLONGEE = 'EN_ATTENTE_PROLONGEE', 'En attente prolongée'
        FUSIONNE = 'FUSIONNE', 'Fusionné'
        INACTIF = 'INACTIF', 'Inactif'

    idDUT = models.AutoField(primary_key=True)
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       related_name='duts', verbose_name='Établissement')
    infirmier = models.ForeignKey('users.Personnel', on_delete=models.PROTECT,
                                   related_name='duts_crees', verbose_name='Infirmier')
    numeroDUT = models.CharField(max_length=50, unique=True, verbose_name='Numéro DUT')
    informationsInitiales = models.TextField(blank=True, verbose_name='Informations initiales')
    photo = models.ImageField(upload_to='dut/photos/', null=True, blank=True,
                               verbose_name='Photo du patient')
    dateCreation = models.DateTimeField(auto_now_add=True, verbose_name='Date de création')
    dateCloture = models.DateTimeField(null=True, blank=True, verbose_name='Date de clôture')
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.ACTIF,
                               verbose_name='Statut')
    dmpRattache = models.ForeignKey('dmp.DossierMedicalPartage', on_delete=models.SET_NULL,
                                     null=True, blank=True, verbose_name='DMP rattaché')
    identiteConfirmee = models.BooleanField(default=False, verbose_name='Identité confirmée')
    dateFusion = models.DateTimeField(null=True, blank=True, verbose_name='Date de fusion')

    class Meta:
        verbose_name = 'Dossier d\'Urgence Temporaire'
        verbose_name_plural = 'Dossiers d\'Urgence Temporaires'
        indexes = [
            models.Index(fields=['dateCreation']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f"DUT {self.numeroDUT}"

    def cloturer(self, motif=''):
        from django.utils import timezone
        self.dateCloture = timezone.now()
        self.statut = self.Statut.INACTIF
        self.save(update_fields=['dateCloture', 'statut'])

    def fusionner_avec_dmp(self, dmp):
        from django.utils import timezone
        self.dmpRattache = dmp
        self.identiteConfirmee = True
        self.dateFusion = timezone.now()
        self.statut = self.Statut.FUSIONNE
        self.save(update_fields=['dmpRattache', 'identiteConfirmee', 'dateFusion', 'statut'])


# ──────────────────────────────────────────────
# Triage
# ──────────────────────────────────────────────
class Triage(models.Model):
    idTriage = models.AutoField(primary_key=True)
    dut = models.OneToOneField(DossierUrgenceTemporaire, on_delete=models.CASCADE,
                                related_name='triage', verbose_name='DUT')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       null=True, blank=True, related_name='triages',
                                       verbose_name='Établissement')
    priorite = models.CharField(
        max_length=20,
        choices=[
            ('ROUGE', 'Réanimation'),
            ('ORANGE', 'Très urgent'),
            ('JAUNE', 'Urgent'),
            ('VERT', 'Peu urgent'),
            ('BLEU', 'Non urgent'),
        ],
        verbose_name='Priorité'
    )
    motifArrivee = models.CharField(max_length=255, verbose_name='Motif d\'arrivée')
    observations = models.TextField(blank=True, verbose_name='Observations')
    dateHeure = models.DateTimeField(auto_now_add=True, verbose_name='Date et heure')

    class Meta:
        verbose_name = 'Triage'
        verbose_name_plural = 'Triages'

    def __str__(self):
        return f"Triage {self.dut.numeroDUT} — {self.priorite}"

    def modifier(self, **kwargs):
        for attr, value in kwargs.items():
            if hasattr(self, attr) and attr != 'idTriage':
                setattr(self, attr, value)
        self.save()


# ──────────────────────────────────────────────
# Constante (signes vitaux)
# ──────────────────────────────────────────────
class Constante(models.Model):
    idConstante = models.AutoField(primary_key=True)
    dut = models.ForeignKey(DossierUrgenceTemporaire, on_delete=models.CASCADE,
                             related_name='constantes', verbose_name='DUT')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       null=True, blank=True, related_name='constantes',
                                       verbose_name='Établissement')
    frequenceCardiaque = models.IntegerField(null=True, blank=True,
                                              verbose_name='Fréquence cardiaque (bpm)')
    tensionArterielle = models.CharField(max_length=20, blank=True,
                                          verbose_name='Tension artérielle')
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                       verbose_name='Température (°C)')
    saturationOxygene = models.IntegerField(null=True, blank=True,
                                             verbose_name='Saturation O₂ (%)')
    frequenceRespiratoire = models.IntegerField(null=True, blank=True,
                                                 verbose_name='Fréquence respiratoire')
    poids = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                 verbose_name='Poids (kg)')
    date = models.DateTimeField(auto_now_add=True, verbose_name='Date de mesure')

    class Meta:
        verbose_name = 'Constante'
        verbose_name_plural = 'Constantes'

    def __str__(self):
        return f"Constantes DUT {self.dut.numeroDUT} — {self.date:%d/%m/%Y %H:%M}"


# ──────────────────────────────────────────────
# ServiceReconnaissanceFaciale (service externe)
# ──────────────────────────────────────────────
class ServiceReconnaissanceFaciale(models.Model):
    """
    Représente l'interaction avec l'API/Service externe de reconnaissance faciale.
    Ce n'est pas un service interne Django — c'est un modèle de traçabilité.
    """
    idService = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=200, verbose_name='Nom du service')
    urlEndpoint = models.URLField(blank=True, verbose_name='URL de l\'API')

    class Meta:
        verbose_name = 'Service de reconnaissance faciale'
        verbose_name_plural = 'Services de reconnaissance faciale'

    def __str__(self):
        return self.nom

    def rechercher_correspondance(self, photo_path):
        """
        Appel à l'API externe. Retourne une liste de correspondances possibles.
        La décision finale appartient toujours à un professionnel habilité.
        """
        # Implémentation réelle : appel API Python/OpenCV
        # Pour le prototype, retourne une structure vide
        return []


# ──────────────────────────────────────────────
# RechercheIdentité
# ──────────────────────────────────────────────
class RechercheIdentite(models.Model):
    class Statut(models.TextChoices):
        EN_RECHERCHE = 'EN_RECHERCHE', 'En recherche'
        CORRESPONDANCE_TROUVEE = 'CORRESPONDANCE_TROUVEE', 'Correspondance trouvée'
        CONFIRMEE = 'CONFIRMEE', 'Confirmée'
        AUCUNE = 'AUCUNE', 'Aucune correspondance'
        REJETEE = 'REJETEE', 'Rejetée'

    idRecherche = models.AutoField(primary_key=True)
    dut = models.ForeignKey(DossierUrgenceTemporaire, on_delete=models.CASCADE,
                             related_name='recherches_identite', verbose_name='DUT')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       null=True, blank=True, related_name='recherches_identite',
                                       verbose_name='Établissement')
    service = models.ForeignKey(ServiceReconnaissanceFaciale, on_delete=models.SET_NULL,
                                 null=True, blank=True, verbose_name='Service utilisé')
    statut = models.CharField(max_length=30, choices=Statut.choices, default=Statut.EN_RECHERCHE,
                               verbose_name='Statut')
    patientCorrespondant = models.ForeignKey('users.Patient', on_delete=models.SET_NULL,
                                              null=True, blank=True,
                                              verbose_name='Patient correspondant')
    confiance = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                     verbose_name='Score de confiance (%)')
    dateRecherche = models.DateTimeField(auto_now_add=True, verbose_name='Date de recherche')
    dateConfirmation = models.DateTimeField(null=True, blank=True,
                                             verbose_name='Date de confirmation')
    confirmePar = models.ForeignKey('users.Personnel', on_delete=models.SET_NULL,
                                     null=True, blank=True,
                                     related_name='confirmations_identite',
                                     verbose_name='Confirmé par')

    class Meta:
        verbose_name = 'Recherche d\'identité'
        verbose_name_plural = 'Recherches d\'identité'

    def __str__(self):
        return f"Recherche DUT {self.dut.numeroDUT} — {self.get_statut_display()}"


# ──────────────────────────────────────────────
# JournalAudit
# ──────────────────────────────────────────────
class JournalAudit(models.Model):
    idJournal = models.AutoField(primary_key=True)
    dateHeure = models.DateTimeField(auto_now_add=True, verbose_name='Date et heure')
    action = models.CharField(max_length=255, verbose_name='Action')
    description = models.TextField(blank=True, verbose_name='Description')
    adresseIP = models.GenericIPAddressField(null=True, blank=True, verbose_name='Adresse IP')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.SET_NULL,
                                       null=True, blank=True, verbose_name='Établissement')
    utilisateur = models.ForeignKey('users.Utilisateur', on_delete=models.SET_NULL,
                                    null=True, blank=True, verbose_name='Utilisateur')
    # T1 (addendum 4) : patient concerné par l'événement — permet au patient
    # de consulter qui a accédé à son DMP (aucun e-mail / identifiant interne).
    patient = models.ForeignKey('users.Patient', on_delete=models.SET_NULL,
                                null=True, blank=True, verbose_name='Patient concerné',
                                related_name='journaux_patient')

    class Meta:
        verbose_name = 'Journal d\'audit'
        verbose_name_plural = 'Journaux d\'audit'
        ordering = ['-dateHeure']
        indexes = [
            models.Index(fields=['dateHeure']),
            models.Index(fields=['patient', 'dateHeure']),
        ]

    def __str__(self):
        return f"[{self.dateHeure:%d/%m/%Y %H:%M}] {self.action}"

    def enregistrer(self):
        self.save()
