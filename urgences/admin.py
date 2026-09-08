from django.contrib import admin

from .models import (Constante, DossierUrgenceTemporaire, JournalAudit,
                      RechercheIdentite, ServiceReconnaissanceFaciale, Triage)


@admin.register(DossierUrgenceTemporaire)
class DutAdmin(admin.ModelAdmin):
    list_display = ('numeroDUT', 'etablissement', 'infirmier', 'statut',
                     'identiteConfirmee', 'dateCreation')
    list_filter = ('statut', 'etablissement')
    search_fields = ('numeroDUT',)


@admin.register(Triage)
class TriageAdmin(admin.ModelAdmin):
    list_display = ('idTriage', 'dut', 'priorite', 'motifArrivee', 'dateHeure')
    list_filter = ('priorite',)


@admin.register(Constante)
class ConstanteAdmin(admin.ModelAdmin):
    list_display = ('idConstante', 'dut', 'frequenceCardiaque', 'temperature',
                     'saturationOxygene', 'date')


@admin.register(ServiceReconnaissanceFaciale)
class ServiceReconnaissanceAdmin(admin.ModelAdmin):
    list_display = ('nom', 'urlEndpoint')


@admin.register(RechercheIdentite)
class RechercheIdentiteAdmin(admin.ModelAdmin):
    list_display = ('idRecherche', 'dut', 'statut', 'patientCorrespondant',
                     'confiance', 'dateRecherche')
    list_filter = ('statut',)


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    """Journal d'audit en lecture seule : consultable, jamais modifiable."""
    list_display = ('idJournal', 'dateHeure', 'action', 'etablissement',
                    'utilisateur', 'adresseIP')
    list_filter = ('action', 'etablissement')
    search_fields = ('action', 'description')
    readonly_fields = ('dateHeure', 'action', 'description', 'adresseIP',
                       'etablissement', 'utilisateur')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
