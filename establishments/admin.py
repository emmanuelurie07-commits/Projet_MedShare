from django.contrib import admin

from .models import Abonnement, Candidature, Etablissement, Formule


@admin.register(Etablissement)
class EtablissementAdmin(admin.ModelAdmin):
    list_display = ('nom', 'adresse', 'telephone', 'statut')
    list_filter = ('statut',)
    search_fields = ('nom',)


@admin.register(Candidature)
class CandidatureAdmin(admin.ModelAdmin):
    list_display = ('prenom', 'nom', 'etablissement', 'roleDemande', 'statut', 'dateSoumission')
    list_filter = ('statut', 'roleDemande', 'etablissement')
    search_fields = ('nom', 'prenom', 'email')
    readonly_fields = ('dateSoumission',)


@admin.register(Formule)
class FormuleAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prix', 'dureeMois', 'nbUtilisateursMax', 'nbDMPMax')


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ('etablissement', 'formule', 'dateDebut', 'dateFin', 'statut')
    list_filter = ('statut',)
