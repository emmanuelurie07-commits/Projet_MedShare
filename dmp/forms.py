from django import forms

from users.models import Patient, Personnel
from .models import (Consultation, DossierMedicalPartage, LignePrescription,
                      Medicament, Prescription)


# ──────────────────────────────────────────────
# Patient (accueil infirmier)
# ──────────────────────────────────────────────
class PatientForm(forms.ModelForm):
    """Formulaire de création/édition d'un patient par l'infirmier.
    Photo obligatoire — utilisée pour la reconnaissance faciale et affichée
    en haut à gauche du dashboard patient (maquette stitch)."""

    # Photo obligatoire (le modèle permet null pour migrations historiques)
    photoProfil = forms.ImageField(
        label='Photo de profil (obligatoire — pour reconnaissance faciale)',
        required=True,
        help_text='Photo frontale, bien éclairée.',
        widget=forms.FileInput(attrs={'accept': 'image/*', 'class': 'form-control'})
    )

    class Meta:
        model = Patient
        fields = ['photoProfil', 'nom', 'prenom', 'dateNaissance', 'sexe',
                  'email', 'telephone', 'adresse', 'niu', 'numeroCNI',
                  'groupeSanguin', 'allergies', 'antecedents', 'traitementEnCours',
                  'nomContactUrgencePrincipal', 'telephoneContactUrgencePrincipal',
                  'lienContactUrgencePrincipal',
                  'nomContactUrgenceSecondaire', 'telephoneContactUrgenceSecondaire',
                  'lienContactUrgenceSecondaire']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'ex : patient@exemple.com'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ex : 6 XX XX XX XX'}),
            'dateNaissance': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'sexe': forms.Select(attrs={'class': 'form-select'}),
            'adresse': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Quartier, ville…'}),
            'niu': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NIU (si disponible)'}),
            'numeroCNI': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'N° CNI (si disponible)'}),
            'groupeSanguin': forms.Select(attrs={'class': 'form-select'}),
            'allergies': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Ex : PÉNICILLINE (choc), ASPIRINE — séparées par virgule'}),
            'antecedents': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Ex : Diabète type 2, Hypertension — séparées par virgule'}),
            'traitementEnCours': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Ex : Metformine 500mg 1x/jour'}),
            'nomContactUrgencePrincipal': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'telephoneContactUrgencePrincipal': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ex : 6 XX XX XX XX'}),
            'lienContactUrgencePrincipal': forms.Select(attrs={'class': 'form-select'}),
            'nomContactUrgenceSecondaire': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'telephoneContactUrgenceSecondaire': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ex : 6 XX XX XX XX'}),
            'lienContactUrgenceSecondaire': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_photoProfil(self):
        photo = self.cleaned_data.get('photoProfil')
        if not photo and not self.instance.pk:
            raise forms.ValidationError('La photo de profil est obligatoire (recherche faciale + dashboard).')
        # Si édition et pas de nouvelle photo mais ancienne existe → OK
        if not photo and self.instance.pk and self.instance.photoProfil:
            return self.instance.photoProfil
        if not photo:
            raise forms.ValidationError('La photo de profil est obligatoire.')
        # Validation taille < 5 MB
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Photo trop volumineuse (max 5 MB).')
        return photo


class PatientRechercheForm(forms.Form):
    query = forms.CharField(
        label='Rechercher un patient',
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Nom, prénom, n° patient, e-mail…'})
    )


# ──────────────────────────────────────────────
# Consultation (médecin)
# ──────────────────────────────────────────────
class ConsultationForm(forms.ModelForm):
    class Meta:
        model = Consultation
        fields = ['motif', 'informationsCliniques', 'observations', 'diagnostic',
                  'conduiteATenir', 'compteRendu', 'recommandations']
        widgets = {
            'motif': forms.TextInput(attrs={'placeholder': 'Motif de la consultation'}),
            'informationsCliniques': forms.Textarea(attrs={'rows': 3}),
            'observations': forms.Textarea(attrs={'rows': 3}),
            'conduiteATenir': forms.Textarea(attrs={'rows': 2}),
            'compteRendu': forms.Textarea(attrs={'rows': 3}),
            'recommandations': forms.Textarea(attrs={'rows': 2}),
        }


# ──────────────────────────────────────────────
# Prescription / Ordonnance
# ──────────────────────────────────────────────
class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ['instructions']
        widgets = {
            'instructions': forms.Textarea(attrs={'rows': 2,
                'placeholder': 'Instructions générales (posologie, hygiène, régime…)'}),
        }


class LignePrescriptionForm(forms.ModelForm):
    class Meta:
        model = LignePrescription
        fields = ['medicament', 'posologie', 'frequence', 'duree', 'quantite']
        widgets = {
            'medicament': forms.Select(attrs={'class': 'form-control'}),
        }


LignePrescriptionFormSet = forms.inlineformset_factory(
    Prescription, LignePrescription,
    form=LignePrescriptionForm,
    extra=1,
    can_delete=True,
)
