from django import forms

from .models import Candidature, Etablissement


class CandidatureForm(forms.ModelForm):
    etablissement = forms.ModelChoiceField(
        queryset=Etablissement.objects.filter(statut='ACTIF'),
        empty_label='-- Sélectionner un établissement --',
        label='Établissement',
    )

    class Meta:
        model = Candidature
        fields = ['nom', 'prenom', 'email', 'telephone', 'etablissement',
                  'roleDemande']


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
