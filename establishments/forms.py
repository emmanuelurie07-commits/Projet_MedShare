from django import forms

from users.models import Role

from .models import Candidature, Etablissement


class CandidatureForm(forms.ModelForm):
    etablissement = forms.ModelChoiceField(
        queryset=Etablissement.objects.filter(statut='ACTIF'),
        empty_label='-- Sélectionner un établissement --',
        label='Établissement',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Candidature
        fields = ['nom', 'prenom', 'email', 'telephone', 'etablissement',
                  'roleDemande']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'votre@gmail.com'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control'}),
            'roleDemande': forms.Select(attrs={'class': 'form-select'}),
        }

    ROLES_CANDIDAT = ['Médecin', 'Infirmier']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        disponibles = set(
            Role.objects.filter(nomRole__in=self.ROLES_CANDIDAT)
                        .values_list('nomRole', flat=True))
        roles = [('', '-- Sélectionner un rôle --')]
        roles += [(nom, nom) for nom in self.ROLES_CANDIDAT if nom in disponibles]
        self.fields['roleDemande'].widget.choices = roles


class CandidatureDecisionForm(forms.Form):
    CHOICES = [
        ('ACCEPTEE', 'Accepter'),
        ('REFUSEE', 'Refuser'),
    ]
    decision = forms.ChoiceField(choices=CHOICES, label='Décision')
    role = forms.CharField(max_length=50, label='Rôle à attribuer', required=False,
                           help_text='Obligatoire si acceptation')
    motifRefus = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}),
                                  label='Motif du refus', required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'ACCEPTEE' and not cleaned.get('role'):
            self.add_error('role', 'Le rôle est obligatoire pour une acceptation.')
        return cleaned
