from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Permission, Personnel, Patient, Role


# ── Role & Permission ────────────────────────────────────────────────────────

class RoleInline(admin.TabularInline):
    model = Role.permissions.through
    extra = 0
    verbose_name = 'Permission'
    verbose_name_plural = 'Permissions'


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('nomRole', 'description')
    inlines = [RoleInline]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('nom', 'description')
    search_fields = ('nom',)


# ── Personnel ────────────────────────────────────────────────────────────────

@admin.register(Personnel)
class PersonnelAdmin(BaseUserAdmin):
    model = Personnel
    fieldsets = BaseUserAdmin.fieldsets + (
        ('MedShare', {'fields': ('nom', 'prenom', 'telephone', 'photoProfil',
                                  'matricule', 'dateAffectation', 'statutProfessionnel', 'role')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nom', 'prenom', 'matricule', 'password1', 'password2', 'role'),
        }),
    )
    list_display = ('email', 'nom', 'prenom', 'matricule', 'statutProfessionnel', 'is_active')
    list_filter = ('statutProfessionnel', 'role')
    search_fields = ('email', 'nom', 'prenom', 'matricule')
    ordering = ('-dateCreation',)


# ── Patient ──────────────────────────────────────────────────────────────────

@admin.register(Patient)
class PatientAdmin(BaseUserAdmin):
    model = Patient
    fieldsets = BaseUserAdmin.fieldsets + (
        ('MedShare', {'fields': ('nom', 'prenom', 'telephone', 'photoProfil',
                                  'numeroPatient', 'dateNaissance', 'sexe', 'adresse',
                                  'niu', 'numeroCNI')}),
        ('Contact d\'urgence', {'fields': ('nomContactUrgencePrincipal',
                                            'telephoneContactUrgencePrincipal',
                                            'lienContactUrgencePrincipal',
                                            'nomContactUrgenceSecondaire',
                                            'telephoneContactUrgenceSecondaire',
                                            'lienContactUrgenceSecondaire')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nom', 'prenom', 'numeroPatient', 'password1', 'password2',
                       'nomContactUrgencePrincipal', 'telephoneContactUrgencePrincipal',
                       'lienContactUrgencePrincipal'),
        }),
    )
    list_display = ('email', 'nom', 'prenom', 'numeroPatient', 'sexe', 'is_active')
    list_filter = ('sexe',)
    search_fields = ('email', 'nom', 'prenom', 'numeroPatient')
    ordering = ('-dateCreation',)
