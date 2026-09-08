from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from .models import Utilisateur
from .security import est_compte_verrouille


class MedShareAuthenticationForm(AuthenticationForm):
    """Formulaire de connexion MedShare : message dédié lorsqu'un compte
    est verrouillé après plusieurs échecs (politique de verrouillage)."""

    error_messages = {
        'invalid_login': (
            'Adresse e-mail ou mot de passe incorrect. '
            'Après 5 échecs consécutifs, le compte est verrouillé 15 minutes.'
        ),
        'inactive': 'Ce compte est désactivé.',
        'verrouille': (
            'Ce compte est temporairement verrouillé après plusieurs '
            'tentatives. Réessayez dans 15 minutes ou réinitialisez '
            'votre mot de passe.'
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.verrouille = False

    def clean(self):
        email = self.cleaned_data.get('username')
        if email:
            try:
                compte = Utilisateur.objects.get(email__iexact=email)
            except Utilisateur.DoesNotExist:
                compte = None
            if compte is not None and est_compte_verrouille(compte):
                self.verrouille = True
                raise forms.ValidationError(
                    self.error_messages['verrouille'], code='verrouille')
        return super().clean()


class ChangerMotDePasseForm(forms.Form):
    ancien_mot_de_passe = forms.CharField(
        label='Mot de passe actuel',
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )
    nouveau_mot_de_passe = forms.CharField(
        label='Nouveau mot de passe',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        min_length=8,
    )
    confirmer_mot_de_passe = forms.CharField(
        label='Confirmer le nouveau mot de passe',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        nouveau = cleaned.get('nouveau_mot_de_passe')
        confirmer = cleaned.get('confirmer_mot_de_passe')
        if nouveau and confirmer and nouveau != confirmer:
            self.add_error('confirmer_mot_de_passe', 'Les mots de passe ne correspondent pas.')
        return cleaned

    def clean_ancien_mot_de_passe(self):
        ancien = self.cleaned_data.get('ancien_mot_de_passe')
        if not self.user.verifier_mot_de_passe(ancien):
            raise forms.ValidationError('Le mot de passe actuel est incorrect.')
        return ancien

    def save(self):
        nouveau = self.cleaned_data['nouveau_mot_de_passe']
        self.user.definir_mot_de_passe(nouveau)
        if hasattr(self.user, 'doitChangerMotDePasse'):
            self.user.doitChangerMotDePasse = False
            self.user.save(update_fields=['doitChangerMotDePasse'])
        return True


class MotDePasseOublieForm(forms.Form):
    """Formulaire « mot de passe oublié » : on ne demande que l'e-mail."""

    email = forms.EmailField(
        label='Adresse e-mail',
        widget=forms.EmailInput(attrs={'placeholder': 'votre@email.com'}),
    )


class ReinitialiserMotDePasseForm(forms.Form):
    """Choix du nouveau mot de passe protégé par le lien signé."""

    nouveau_mot_de_passe = forms.CharField(
        label='Nouveau mot de passe',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        min_length=8,
    )
    confirmer_mot_de_passe = forms.CharField(
        label='Confirmer le nouveau mot de passe',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, utilisateur, *args, **kwargs):
        self.utilisateur = utilisateur
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        nouveau = cleaned.get('nouveau_mot_de_passe')
        confirmer = cleaned.get('confirmer_mot_de_passe')
        if nouveau and confirmer and nouveau != confirmer:
            self.add_error('confirmer_mot_de_passe',
                           'Les mots de passe ne correspondent pas.')
        if nouveau:
            try:
                validate_password(nouveau, self.utilisateur)
            except forms.ValidationError as erreurs:
                self.add_error('nouveau_mot_de_passe', erreurs)
        return cleaned

    def save(self):
        """Applique le nouveau mot de passe, réinitialise le compteur d'échecs
        et renouvelle le jeton (invalide dossiers/dashboard liés à l'ancien).
        Le lien signé devient lui-même inutilisable (préfixe de hachage)."""
        nouvel_mot_de_passe = self.cleaned_data['nouveau_mot_de_passe']
        self.utilisateur.set_password(nouvel_mot_de_passe)
        self.utilisateur.nbEchecsConnexion = 0
        self.utilisateur.verrouillageJusqua = None
        self.utilisateur.regenerer_jeton(commit=False)
        champs = ['password', 'nbEchecsConnexion', 'verrouillageJusqua', 'jeton_acces']
        if hasattr(self.utilisateur, 'doitChangerMotDePasse'):
            self.utilisateur.doitChangerMotDePasse = False
            champs.append('doitChangerMotDePasse')
        self.utilisateur.save(update_fields=champs)
        return True
