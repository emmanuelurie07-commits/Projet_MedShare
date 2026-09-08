"""
Management command : seed_demo
Crée des comptes de démonstration pour chaque acteur de la plateforme
(super admin, admin hospitalier, médecin, infirmier, patients) afin de
pouvoir se connecter et visualiser chaque dashboard.

Usage : python manage.py seed_demo
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from establishments.models import Etablissement, Formule, Abonnement
from users.models import Role, Permission, Personnel, Patient, Utilisateur

MOT_DE_PASSE_DEMO = 'Demo@2026'


class Command(BaseCommand):
    help = 'Crée les comptes de démonstration (chaque acteur / dashboard).'

    def handle(self, *args, **options):
        self._creer_rôle('Médecin')
        role_medecin = Role.objects.filter(nomRole='Médecin').first()
        self._creer_rôle('Infirmier')
        role_infirmier = Role.objects.filter(nomRole='Infirmier').first()
        self._creer_rôle('Administrateur')
        role_admin = Role.objects.filter(nomRole='Administrateur').first()

        etab1 = Etablissement.objects.first()
        if not etab1:
            self.stderr.write("Aucun établissement. Lancez d'abord : python manage.py seed_data")
            return

        # ── Comptes personnel ──────────────────────────────
        comptes = []

        def personnel(email, nom, prenom, role, etab, matricule):
            if Personnel.objects.filter(email=email).exists():
                return Personnel.objects.get(email=email)
            p = Personnel(
                email=email, nom=nom, prenom=prenom,
                matricule=matricule, role=role, etablissement=etab,
                statutProfessionnel='ACTIF',
            )
            p.set_password(MOT_DE_PASSE_DEMO)
            p.save()
            return p

        admin_hop = personnel('admin.yaounde@medshare.cm', 'Mballa', 'Aline',
                              role_admin, etab1, 'ADM-001')
        medecin = personnel('dr.ngono@medshare.cm', 'Ngono', 'Emmanuel',
                            role_medecin, etab1, 'MED-101')
        infirmier = personnel('inf.fouda@medshare.cm', 'Fouda', 'Clarisse',
                              role_infirmier, etab1, 'INF-201')

        comptes += [
            ('Administrateur hospitalier', 'admin.yaounde@medshare.cm', 'Dashboard personnel'),
            ('Médecin', 'dr.ngono@medshare.cm', 'Dashboard personnel'),
            ('Infirmier', 'inf.fouda@medshare.cm', 'Dashboard personnel'),
        ]

        # ── Super administrateur (plateforme / éditeur SaaS) ──
        if not Utilisateur.objects.filter(email='demo.superadmin@medshare.cm').exists():
            sa = Utilisateur(
                email='demo.superadmin@medshare.cm', nom='MedShare', prenom='SuperAdmin',
                is_staff=True, is_superuser=True,
            )
            sa.set_password(MOT_DE_PASSE_DEMO)
            sa.save()
        comptes.append(('Super administrateur (éditeur SaaS)', 'demo.superadmin@medshare.cm', '/'))

        # ── Patients ────────────────────────────────────────
        def patient(email, nom, prenom, numero, contact):
            if Patient.objects.filter(email=email).exists():
                return Patient.objects.get(email=email)
            pat = Patient(
                email=email, nom=nom, prenom=prenom, numeroPatient=numero,
                dateNaissance='1990-05-14', sexe='F',
                nomContactUrgencePrincipal='Contact Urgence',
                telephoneContactUrgencePrincipal=contact,
                lienContactUrgencePrincipal='Proche',
                # Code de confirmation patient (démo) : impossible à connaître
                # par le soignant — à demander au patient lui-même.
                codeConfirmation='123456',
                doitChangerMotDePasse=True,
            )
            pat.set_password(MOT_DE_PASSE_DEMO)
            pat.save()
            return pat

        p1 = patient('patient1@medshare.cm', 'Atangana', 'Marie', 'PAT-1001', '+237 699111111')
        p2 = patient('patient2@medshare.cm', 'Essomba', 'Paul', 'PAT-1002', '+237 699222222')
        comptes += [
            ('Patient 1', 'patient1@medshare.cm', 'Dashboard patient '
             f'(/compte/acces/{p1.jeton_acces}/)'),
            ('Patient 2', 'patient2@medshare.cm', 'Dashboard patient '
             f'(/compte/acces/{p2.jeton_acces}/)'),
        ]

        # ── Abonnements SaaS ────────────────────────────────
        formule = Formule.objects.first()
        if formule:
            for etab in Etablissement.objects.all():
                Abonnement.objects.get_or_create(
                    etablissement=etab,
                    defaults={
                        'formule': formule,
                        'dateDebut': timezone.localdate(),
                        'dateFin': timezone.localdate() + timedelta(days=365),
                        'statut': 'ACTIF',
                    }
                )

        # ── Récapitulatif ───────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n--- Comptes de demonstration (mot de passe commun) ---'))
        self.stdout.write(f'Mot de passe générique : {MOT_DE_PASSE_DEMO}\n')
        for lib, email, acces in comptes:
            self.stdout.write(f'  • {lib}')
            self.stdout.write(f'      email   : {email}')
            self.stdout.write(f'      accès   : {acces}')
        self.stdout.write(self.style.SUCCESS("\nConnexion depuis la page d'accueil "
                                             '(http://127.0.0.1:8000/).'))

    def _creer_rôle(self, nom):
        role, _ = Role.objects.get_or_create(nomRole=nom)
        return role