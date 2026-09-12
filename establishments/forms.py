from django import forms

from users.models import ROLE_INFIRMIER, ROLE_MEDECIN, Role

from .models import Candidature, Etablissement

# Rôles attribuables à un candidat accepté. Ancrés sur les noms canoniques
# (constants) et non sur l'existant en base : le rôle est créé si nécessaire
# par _accepter_candidature via get_or_create. Ceci empêche les doublons du
# type « Infirmière » tout en restant fonctionnel sur une base vierge.
ROLES_CANDIDAT = (ROLE_MEDECIN, ROLE_INFIRMIER)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        disponibles = set(
            Role.objects.filter(nomRole__in=ROLES_CANDIDAT)
                        .values_list('nomRole', flat=True))
        roles = [('', '-- Sélectionner un rôle --')]
        roles += [(nom, nom) for nom in ROLES_CANDIDAT if nom in disponibles]
        self.fields['roleDemande'].widget.choices = roles


class CandidatureDecisionForm(forms.Form):
    CHOICES = [
        ('ACCEPTEE', 'Accepter'),
        ('REFUSEE', 'Refuser'),
    ]
    decision = forms.ChoiceField(choices=CHOICES, label='Décision')
    # Champ limité aux noms de rôles canoniques (constants), pas aux rôles
    # présents en base : un champ libre aurait permis de recréer des doublons
    # (ex. « Infirmière » au lieu de « Infirmier ») et de casser le routage
    # des rôles ; le rôle canonique est créé à l'acceptation si nécessaire.
    role = forms.ChoiceField(
        choices=[('', '-- Sélectionner le rôle --')] + [(r, r) for r in ROLES_CANDIDAT],
        label='Rôle à attribuer', required=False,
        help_text='Obligatoire si acceptation')
    motifRefus = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}),
                                  label='Motif du refus', required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'ACCEPTEE' and not cleaned.get('role'):
            self.add_error('role', 'Le rôle est obligatoire pour une acceptation.')
        return cleaned
