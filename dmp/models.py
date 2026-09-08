from datetime import timedelta

from django.db import models


# ──────────────────────────────────────────────
# Médicament (catalogue de référence)
# ──────────────────────────────────────────────
class Medicament(models.Model):
    idMedicament = models.AutoField(primary_key=True)
    nomCommercial = models.CharField(max_length=200, verbose_name='Nom commercial')
    forme = models.CharField(max_length=100, blank=True, verbose_name='Forme (comprimé, sirop…)')

    class Meta:
        verbose_name = 'Médicament'
        verbose_name_plural = 'Médicaments'

    def __str__(self):
        return self.nomCommercial


# ──────────────────────────────────────────────
# DMP — Dossier Médical Partagé
# ──────────────────────────────────────────────
class DossierMedicalPartage(models.Model):
    idDMP = models.AutoField(primary_key=True)
    patient = models.OneToOneField('users.Patient', on_delete=models.CASCADE,
                                    related_name='dmp', verbose_name='Patient')
    numeroDMP = models.CharField(max_length=50, unique=True, verbose_name='Numéro DMP')
    dateCreation = models.DateTimeField(auto_now_add=True, verbose_name='Date de création')
    dateMiseAJour = models.DateTimeField(auto_now=True, verbose_name='Date de mise à jour')
    statut = models.CharField(
        max_length=20,
        choices=[
            ('ACTIF', 'Actif'),
            ('ARCHIVE', 'Archivé'),
        ],
        default='ACTIF',
        verbose_name='Statut'
    )

    class Meta:
        verbose_name = 'Dossier Médical Partagé'
        verbose_name_plural = 'Dossiers Médicaux Partagés'

    def __str__(self):
        return f"DMP {self.numeroDMP} — {self.patient}"

    def consulter_historique(self):
        return self.consultations.all()

    def archiver(self):
        self.statut = 'ARCHIVE'
        self.save(update_fields=['statut'])


# ──────────────────────────────────────────────
# AccesDMP — approbation patient / autorisation d'accès
# L'accès au dossier d'un patient identifié est subordonné à une
# approbation EXPRESSE du patient (itération 3, addendum). La saisie d'un
# PIN par le soignant est abolie : c'est le patient qui consent, en ligne.
# ──────────────────────────────────────────────
class AccesDMP(models.Model):
    class Statut(models.TextChoices):
        EN_ATTENTE = 'EN_ATTENTE', 'En attente'
        ACCORDE = 'ACCORDE', 'Accordé'
        REFUSE = 'REFUSE', 'Refusé'
        REVOQUE = 'REVOQUE', 'Révoqué'
        EXPIRE = 'EXPIRE', 'Expiré'

    idAcces = models.AutoField(primary_key=True)
    patient = models.ForeignKey('users.Patient', on_delete=models.CASCADE,
                                 related_name='acces_dmp', verbose_name='Patient')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       related_name='acces_dmp', verbose_name='Établissement')
    demandeur = models.ForeignKey('users.Personnel', on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='demandes_dmp',
                                   verbose_name='Demandeur')
    statut = models.CharField(max_length=20, choices=Statut.choices,
                               default=Statut.EN_ATTENTE, verbose_name='Statut')
    motif = models.CharField(max_length=255, blank=True, verbose_name='Motif')
    dateDemande = models.DateTimeField(auto_now_add=True, verbose_name='Date de demande')
    dateDecision = models.DateTimeField(null=True, blank=True, verbose_name='Date de décision')

    # T2 (addendum 4) — robustesse e-mail : suivi des renvois de la
    # notification envoyée au patient (limite de 3, puis délai d'attente).
    nbNotificationsEnvoyees = models.PositiveIntegerField(
        default=0, verbose_name='Notifications e-mail envoyées')
    dernierEnvoiNotification = models.DateTimeField(
        null=True, blank=True, verbose_name='Dernière notification envoyée')

    # Limite de renvois et délai entre deux envois (politique anti-spam).
    RENVOIS_MAX = 3
    DELAI_RENVOI = timedelta(minutes=5)

    class Meta:
        verbose_name = 'Accès DMP'
        verbose_name_plural = 'Accès DMP'
        ordering = ['-dateDemande']

    def __str__(self):
        return f"Accès {self.patient} ↔ {self.etablissement} — {self.get_statut_display()}"

    @property
    def est_actif(self):
        return self.statut in (self.Statut.ACCORDE,)

    def approuver(self, utilisateur=None):
        """Consentement explicite du patient (ou ré-approbation par l'admin)."""
        from django.utils import timezone
        self.statut = self.Statut.ACCORDE
        self.dateDecision = timezone.now()
        self.save(update_fields=['statut', 'dateDecision'])
        self._journal('APPROBATION_DMP', utilisateur)

    def refuser(self, utilisateur=None):
        from django.utils import timezone
        self.statut = self.Statut.REFUSE
        self.dateDecision = timezone.now()
        self.save(update_fields=['statut', 'dateDecision'])
        self._journal('REFUS_DMP', utilisateur)

    def revoquer(self, utilisateur=None):
        from django.utils import timezone
        self.statut = self.Statut.REVOQUE
        self.dateDecision = timezone.now()
        self.save(update_fields=['statut', 'dateDecision'])
        self._journal('REVOCATION_DMP', utilisateur)

    def peut_renvoyer_notification(self):
        """Renvoi possible tant que la limite de 3 n'est pas atteinte et que le
        délai de sécurité (5 min) est respecté."""
        from django.utils import timezone
        if self.nbNotificationsEnvoyees >= self.RENVOIS_MAX:
            return False
        if self.dernierEnvoiNotification and \
                timezone.now() - self.dernierEnvoiNotification < self.DELAI_RENVOI:
            return False
        return True

    def notifier_patient(self, request=None):
        """Envoie (ou renvoie) au patient la notification l'invitant à ouvrir
        son espace et à approuver la demande d'accès à son dossier."""
        from django.utils import timezone
        from core.notifications import envoyer_email
        sujet = 'Une demande d\'accès à votre dossier Medical partagé'
        corps = (
            f'Bonjour {self.patient.prenom} {self.patient.nom},\n\n'
            f'Un professionnel de l\'établissement '
            f'{self.etablissement.nom if self.etablissement else "de soins"} a '
            f'demandé l\'accès à votre dossier médical partagé (DMP).\n\n'
            f'Connectez-vous à votre espace patient MedShare pour approuver '
            f'ou refuser cette demande. Aucune consultation ne peut avoir lieu '
            f'sans votre accord explicite.\n\n'
            f'Cordialement,\nl\'équipe MedShare'
        )
        ok = envoyer_email(request, self.patient.email, sujet, corps)
        if ok:
            self.nbNotificationsEnvoyees += 1
            self.dernierEnvoiNotification = timezone.now()
            self.save(update_fields=['nbNotificationsEnvoyees',
                                     'dernierEnvoiNotification'])
        return ok

    def _journal(self, action, utilisateur):
        try:
            from urgences.models import JournalAudit
            JournalAudit.objects.create(
                action=action,
                description=f'{self.get_statut_display()} : accès DMP du patient '
                            f'{self.patient.numeroPatient} par {self.etablissement.nom}',
                utilisateur=utilisateur,
                etablissement=self.etablissement,
                patient=self.patient,
            )
        except Exception:
            pass


# ──────────────────────────────────────────────
# Consultation
# ──────────────────────────────────────────────
class Consultation(models.Model):
    idConsultation = models.AutoField(primary_key=True)
    dmp = models.ForeignKey(DossierMedicalPartage, on_delete=models.CASCADE,
                             related_name='consultations', verbose_name='DMP')
    etablissement = models.ForeignKey('establishments.Etablissement', on_delete=models.PROTECT,
                                       related_name='consultations', verbose_name='Établissement')
    medecin = models.ForeignKey('users.Personnel', on_delete=models.PROTECT,
                                 related_name='consultations', verbose_name='Médecin')
    dateHeure = models.DateTimeField(auto_now_add=True, verbose_name='Date et heure')
    motif = models.CharField(max_length=255, verbose_name='Motif')
    informationsCliniques = models.TextField(blank=True, verbose_name='Informations cliniques')
    observations = models.TextField(blank=True, verbose_name='Observations')
    diagnostic = models.CharField(max_length=255, blank=True, verbose_name='Diagnostic')
    conduiteATenir = models.TextField(blank=True, verbose_name='Conduite à tenir')
    compteRendu = models.TextField(blank=True, verbose_name='Compte rendu')
    recommandations = models.TextField(blank=True, verbose_name='Recommandations')
    statut = models.CharField(
        max_length=20,
        choices=[
            ('ACTIVE', 'Active'),
            ('ANNULEE', 'Annulée'),
        ],
        default='ACTIVE',
        verbose_name='Statut'
    )

    class Meta:
        verbose_name = 'Consultation'
        verbose_name_plural = 'Consultations'
        ordering = ['-dateHeure']

    def __str__(self):
        return f"Consultation du {self.dateHeure:%d/%m/%Y %H:%M} — {self.motif}"

    def modifier(self, **kwargs):
        for attr, value in kwargs.items():
            if hasattr(self, attr) and attr != 'idConsultation':
                setattr(self, attr, value)
        self.save()

    def annuler(self):
        """Jamais de suppression définitive (itération 3) : l'acte est marqué
        ANNULEE pour préserver la traçabilité RGPD et l'historique patient."""
        self.statut = 'ANNULEE'
        self.save(update_fields=['statut'])


# ──────────────────────────────────────────────
# Prescription / Ordonnance
# ──────────────────────────────────────────────
class Prescription(models.Model):
    idPrescription = models.AutoField(primary_key=True)
    consultation = models.OneToOneField(Consultation, on_delete=models.CASCADE,
                                         related_name='prescription', verbose_name='Consultation')
    datePrescription = models.DateTimeField(auto_now_add=True, verbose_name='Date de prescription')
    instructions = models.TextField(blank=True, verbose_name='Instructions')
    statut = models.CharField(
        max_length=20,
        choices=[
            ('ACTIVE', 'Active'),
            ('ANNULEE', 'Annulée'),
        ],
        default='ACTIVE',
        verbose_name='Statut'
    )

    class Meta:
        verbose_name = 'Prescription'
        verbose_name_plural = 'Prescriptions'

    def __str__(self):
        return f"Prescription — {self.consultation}"

    def generer_ordonnance(self):
        return {
            'consultation': self.consultation,
            'date': self.datePrescription,
            'instructions': self.instructions,
            'lignes': list(self.lignes.all()),
        }

    def modifier(self, **kwargs):
        for attr, value in kwargs.items():
            if hasattr(self, attr) and attr != 'idPrescription':
                setattr(self, attr, value)
        self.save()

    def annuler(self):
        """Jamais de suppression définitive (itération 3) : l'ordonnance est
        marquée ANNULEE pour préserver la traçabilité RGPD."""
        self.statut = 'ANNULEE'
        self.save(update_fields=['statut'])


# ──────────────────────────────────────────────
# LignePrescription
# ──────────────────────────────────────────────
class LignePrescription(models.Model):
    idLigne = models.AutoField(primary_key=True)
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE,
                                      related_name='lignes', verbose_name='Prescription')
    medicament = models.ForeignKey(Medicament, on_delete=models.PROTECT,
                                    related_name='lignes_prescription', verbose_name='Médicament')
    posologie = models.CharField(max_length=200, verbose_name='Posologie')
    frequence = models.CharField(max_length=100, blank=True, verbose_name='Fréquence')
    duree = models.CharField(max_length=100, blank=True, verbose_name='Durée du traitement')
    quantite = models.CharField(max_length=50, blank=True, verbose_name='Quantité')

    class Meta:
        verbose_name = 'Ligne de prescription'
        verbose_name_plural = 'Lignes de prescription'

    def __str__(self):
        return f"{self.medicament} — {self.posologie}"
