"""Création du compte Super Admin de démarrage (addendum 3, T1).

Compte unique créé par migration de données :
    e-mail   : emmanuelurie07@gmail.com
    rôle     : « Super Admin » (rôle applicatif, en plus de is_superuser)
    matricule: SUP-2026-0001

Décisions explicites :
- le mot de passe initial (provisoire) est haché avec make_password et n'est
  JAMAIS stocké en clair dans le dépôt : il provient de l'environnement
  (SUPERADMIN_INITIAL_PASSWORD dans .env) ou, à défaut, d'une valeur forte
  aléatoire générée à l'exécution.
- la classe historique de migration n'exécute pas le save() custom de
  Utilisateur, le hachage doit donc être appliqué ici.
- « doitChangerMotDePasse=True » : le premier changement de mot de passe est
  imposé (politique T8.1). Le parcours 2FA n'est pas bloqué grâce à
  l'exemption '/compte/superadmin/' ajoutée à ChangerMotDePasseMiddleware.
- Les éventuels super administrateurs existants (ex. demo.superadmin@… du
  seed_demo, su@test.com des tests) sont CONSERVÉS : comptes de test/dev
  jetables, pas de suppression de données (principe de non-suppression).
- reverse_code n'efface jamais : il désactive simplement le compte créé ici
  (statutCompte=False), sans le supprimer ni toucher aux autres comptes.
"""

import os
import secrets

from django.contrib.auth.hashers import make_password
from django.db import migrations

EMAIL_SUPERADMIN = 'emmanuelurie07@gmail.com'
MATRICULE_SUPERADMIN = 'SUP-2026-0001'

# Sécurité : aucun mot de passe en clair dans le dépôt. Lecture depuis
# l'environnement (.env → SUPERADMIN_INITIAL_PASSWORD) ; à défaut, une valeur
# forte aléatoire est générée (doitChangerMotDePasse=True impose ensuite le
# remplacement à la première connexion).
MOT_DE_PASSE_SUPERADMIN = os.getenv('SUPERADMIN_INITIAL_PASSWORD', '').strip()
if not MOT_DE_PASSE_SUPERADMIN:
    MOT_DE_PASSE_SUPERADMIN = secrets.token_urlsafe(16)


def creer_superadmin(apps, schema_editor):
    Personnel = apps.get_model('users', 'Personnel')
    Role = apps.get_model('users', 'Role')

    # Idempotent : ne recrée jamais un compte déjà présent.
    if Personnel.objects.filter(email__iexact=EMAIL_SUPERADMIN).exists():
        return

    role_super_admin, _ = Role.objects.get_or_create(
        nomRole='Super Admin',
        defaults={'description': 'Administrateur global de la plateforme MedShare'})

    Personnel.objects.create(
        nom='Urie',
        prenom='Emmanuel',
        email=EMAIL_SUPERADMIN,
        telephone='',
        password=make_password(MOT_DE_PASSE_SUPERADMIN),
        matricule=MATRICULE_SUPERADMIN,
        statutProfessionnel='ACTIF',
        statutCompte=True,
        is_staff=True,
        is_superuser=True,
        role=role_super_admin,
        doitChangerMotDePasse=True,
    )


def annuler(apps, schema_editor):
    """Annulation par désactivation (jamais de suppression)."""
    Personnel = apps.get_model('users', 'Personnel')
    Personnel.objects.filter(email__iexact=EMAIL_SUPERADMIN).update(
        statutCompte=False, statutProfessionnel='INACTIF',
        is_superuser=False, is_staff=False)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_utilisateur_nbechecsconnexion_and_more'),
    ]

    operations = [
        migrations.RunPython(creer_superadmin, annuler),
    ]