"""
Management command : seed_data
Peuple la base avec des données de test (médicaments, formules, établissements).
Usage : python manage.py seed_data
"""
import secrets
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from dmp.models import Medicament
from establishments.models import Etablissement, Formule
from users.models import Role, Permission


MEDICAMENTS = [
    ('Paracétamol 500mg', 'Comprimé'),
    ('Ibuprofène 400mg', 'Comprimé'),
    ('Amoxicilline 1g', 'Gélule'),
    ('Azithromycine 250mg', 'Comprimé'),
    ('Métronidazole 500mg', 'Comprimé'),
    ('Omeprazole 20mg', 'Gélule'),
    ('Metformine 850mg', 'Comprimé'),
    ('Amlodipine 5mg', 'Comprimé'),
    ('Lisinopril 10mg', 'Comprimé'),
    ('Salbutamol spray', 'Inhalateur'),
    ('Ciprofloxacine 500mg', 'Comprimé'),
    ('Diclofénac 75mg', 'Comprimé'),
    ('Céftriaxone 1g', 'Poudre injectable'),
    ('Tramadol 50mg', 'Gélule'),
    ('Diazépam 5mg', 'Comprimé'),
    ('Ranitidine 150mg', 'Comprimé'),
    ('Norfloxacine 400mg', 'Comprimé'),
    ('Dexaméthasone 4mg', 'Comprimé'),
    ('Prednisolone 20mg', 'Comprimé'),
    ('Suppléments fer + acide folique', 'Comprimé'),
]

FORMULES = [
    ('Essentiel', 'Formule de base pour les petits établissements', 50000, 6, 10, 200),
    ('Professionnel', 'Formule intermédiaire avec plus de fonctionnalités', 150000, 12, 30, 1000),
    ('Entreprise', 'Formule complète pour les grands établissements', 350000, 12, 100, 5000),
]

PERMISSIONS = [
    ('consulter_dmp', 'Consulter les dossiers médicaux'),
    ('creer_consultation', 'Créer des consultations'),
    ('prescrire', 'Créer des ordonnances'),
    ('gerer_urgence', 'Gérer les urgences'),
    ('gerer_personnel', 'Gérer le personnel'),
    ('gerer_etablissement', 'Gérer l\'établissement'),
    ('gerer_abonnement', 'Gérer l\'abonnement'),
    ('consulter_rapports', 'Consulter les rapports'),
]


class Command(BaseCommand):
    help = 'Peuple la base avec des données de test'

    def handle(self, *args, **options):
        self.stdout.write('Création des données de test...')

        # Permissions
        for nom, desc in PERMISSIONS:
            Permission.objects.get_or_create(nom=nom, defaults={'description': desc})
        self.stdout.write(self.style.SUCCESS(f'  {len(PERMISSIONS)} permissions créées'))

        # Rôles
        roles_config = {
            'Médecin': ['consulter_dmp', 'creer_consultation', 'prescrire', 'gerer_urgence'],
            'Infirmier': ['consulter_dmp', 'gerer_urgence'],
            'Administrateur': ['gerer_personnel', 'gerer_etablissement', 'gerer_abonnement'],
        }
        for role_nom, perms in roles_config.items():
            role, _ = Role.objects.get_or_create(nomRole=role_nom)
            for perm_nom in perms:
                perm = Permission.objects.get(nom=perm_nom)
                role.permissions.add(perm)
        self.stdout.write(self.style.SUCCESS(f'  {len(roles_config)} rôles créés'))

        # Médicaments
        for nom, forme in MEDICAMENTS:
            Medicament.objects.get_or_create(nomCommercial=nom, defaults={'forme': forme})
        self.stdout.write(self.style.SUCCESS(f'  {len(MEDICAMENTS)} médicaments créés'))

        # Formules
        for nom, desc, prix, duree, nb_users, nb_dmp in FORMULES:
            Formule.objects.get_or_create(
                nom=nom,
                defaults={
                    'description': desc,
                    'prix': prix,
                    'dureeMois': duree,
                    'nbUtilisateursMax': nb_users,
                    'nbDMPMax': nb_dmp,
                }
            )
        self.stdout.write(self.style.SUCCESS(f'  {len(FORMULES)} formules créées'))

        # Établissements de test
        etabs = [
            ('Hôpital Central de Yaoundé', 'Yaoundé'),
            ('Hôpital Général de Douala', 'Douala'),
            ('Centre Hospitalier de Bafoussam', 'Bafoussam'),
        ]
        for nom, ville in etabs:
            Etablissement.objects.get_or_create(
                nom=nom,
                defaults={
                    'adresse': f'Avenue principale, {ville}',
                    'telephone': f'+237 {secrets.randbelow(90000000) + 10000000}',
                    'email': f'contact@{nom.lower().replace(" ", "").replace("é", "e")[:20]}.cm',
                    'statut': 'ACTIF',
                }
            )
        self.stdout.write(self.style.SUCCESS(f'  {len(etabs)} établissements créés'))

        self.stdout.write(self.style.SUCCESS('\nDonnées de test créées avec succès !'))
