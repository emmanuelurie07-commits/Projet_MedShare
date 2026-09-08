from django import forms

from .models import Constante, DossierUrgenceTemporaire, Triage


class DUTForm(forms.ModelForm):
    """Création d'un Dossier d'Urgence Temporaire pour patient inconnu.
    Étape 1 : Prise de vue & Recherche automatique — la photo est OBLIGATOIRE."""
    photo = forms.ImageField(
        label='Photo du patient inconscient (obligatoire)',
        required=True,
        help_text='Photo frontale prise à l’admission.',
        widget=forms.FileInput(attrs={'accept': 'image/*'})
    )

    class Meta:
        model = DossierUrgenceTemporaire
        fields = ['informationsInitiales', 'photo']
        widgets = {
            'informationsInitiales': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Description physique, vêtements, accessoires, motif d’arrivée…'
            }),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if not photo:
            raise forms.ValidationError('La photo du patient est obligatoire pour la reconnaissance faciale.')
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Photo trop volumineuse (max 5 MB).')
        return photo


class TriageForm(forms.ModelForm):
    class Meta:
        model = Triage
        fields = ['priorite', 'motifArrivee', 'observations']
        widgets = {
            'motifArrivee': forms.TextInput(attrs={'placeholder': 'Motif d\'arrivée'}),
            'observations': forms.Textarea(attrs={'rows': 2}),
        }


class ConstanteForm(forms.ModelForm):
    class Meta:
        model = Constante
        fields = ['frequenceCardiaque', 'tensionArterielle', 'temperature',
                  'saturationOxygene', 'frequenceRespiratoire', 'poids']
        widgets = {
            'frequenceCardiaque': forms.NumberInput(attrs={'placeholder': 'bpm'}),
            'tensionArterielle': forms.TextInput(attrs={'placeholder': 'ex: 12/8'}),
            'temperature': forms.NumberInput(attrs={'placeholder': '°C', 'step': '0.1'}),
            'saturationOxygene': forms.NumberInput(attrs={'placeholder': '%'}),
            'frequenceRespiratoire': forms.NumberInput(attrs={'placeholder': 'resp/min'}),
            'poids': forms.NumberInput(attrs={'placeholder': 'kg', 'step': '0.1'}),
        }


class RechercheIdentiteForm(forms.Form):
    """Formulaire de recherche d'identité (déclenche l'API faciale).
    Photo optionnelle : si vide, on relance avec la photo du DUT."""
    photo = forms.ImageField(label='Nouvelle photo (optionnel — sinon relance DUT)', required=False)
