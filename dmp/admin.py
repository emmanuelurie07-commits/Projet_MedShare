from django.contrib import admin

from .models import (Consultation, DossierMedicalPartage, LignePrescription,
                      Medicament, Prescription)


class ConsultationInline(admin.TabularInline):
    model = Consultation
    extra = 0


class LignePrescriptionInline(admin.TabularInline):
    model = LignePrescription
    extra = 0


@admin.register(Medicament)
class MedicamentAdmin(admin.ModelAdmin):
    list_display = ('nomCommercial', 'forme')
    search_fields = ('nomCommercial',)


@admin.register(DossierMedicalPartage)
class DmpAdmin(admin.ModelAdmin):
    list_display = ('numeroDMP', 'patient', 'statut', 'dateCreation', 'dateMiseAJour')
    list_filter = ('statut',)
    search_fields = ('numeroDMP', 'patient__nom', 'patient__prenom')
    inlines = [ConsultationInline]


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ('idConsultation', 'dmp', 'medecin', 'etablissement', 'dateHeure', 'motif')
    list_filter = ('etablissement', 'dateHeure')
    search_fields = ('motif', 'diagnostic')


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('idPrescription', 'consultation', 'datePrescription')
    inlines = [LignePrescriptionInline]


@admin.register(LignePrescription)
class LignePrescriptionAdmin(admin.ModelAdmin):
    list_display = ('idLigne', 'prescription', 'medicament', 'posologie', 'duree')
