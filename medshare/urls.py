import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, re_path
from django.views.static import serve

from core.views import dashboard, dashboard_personnel, super_abonnements, super_etablissements, super_rapports
from users.views import MedShareLoginView
from medshare.verif import verif
from dmp import views as dmp_views
from establishments import views as etablissements_views
from urgences import views as urgences_views
from users import views as users_views

# NOTE (Vercel) : les URLconf des applications sont déclarées ici « aplaties »
# (aucun include()) car le framework Django zero-config de Vercel enregistre
# uniquement les path() déclarés directement dans l'URLconf racine. Les
# includes() n'étaient pas repris dans les routes générées (404 plateforme).

urlpatterns = [
    path('admin/', admin.site.urls),
    # Racine : le portail de connexion est le point d'entrée public.
    # Les candidats non membres soumettent une demande depuis cette page.
    path('', MedShareLoginView.as_view(), name='login'),
    path('verif/', verif, name='verif_diagnostic'),  # TEMPORAIRE
    path('dashboard/', dashboard, name='dashboard'),
    path('b/<str:jeton>/', dashboard_personnel, name='dashboard_personnel'),
    path('super/etablissements/', super_etablissements, name='super_etablissements'),
    path('super/abonnements/', super_abonnements, name='super_abonnements'),
    path('super/rapports/', super_rapports, name='super_rapports'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    # compte/  (users)
    path('compte/profil/', users_views.mon_profil, name='mon_profil'),
    path('compte/changer-mot-de-passe/', users_views.changer_mot_de_passe, name='changer_mot_de_passe'),
    path('compte/mot-de-passe-modifie/', users_views.changer_mot_de_passe_succes,
         name='changer_mot_de_passe_succes'),
    path('compte/acces/<str:jeton>/', users_views.dashboard_patient, name='dashboard_patient'),
    path('compte/superadmin/2fa/', users_views.superadmin_2fa, name='superadmin_2fa'),
    path('compte/superadmin/2fa/verifier/', users_views.superadmin_2fa_verifier,
         name='superadmin_2fa_verifier'),
    path('compte/mot-de-passe-oublie/', users_views.mot_de_passe_oublie, name='mot_de_passe_oublie'),
    path('compte/reinitialiser/<str:jeton>/', users_views.reinitialiser_mot_de_passe,
         name='reinitialiser_mot_de_passe'),
    # etablissements/  (candidatures, personnel, abonnement, journal)
    path('etablissements/candidature/soumettre/', etablissements_views.soumettre_candidature,
         name='soumettre_candidature'),
    path('etablissements/candidature/confirmation/<int:pk>/', etablissements_views.candidature_confirmation,
         name='candidature_confirmation'),
    path('etablissements/candidature/consulter/', etablissements_views.consulter_candidature,
         name='consulter_candidature'),
    path('etablissements/candidatures/', etablissements_views.gestion_candidatures,
         name='gestion_candidatures'),
    path('etablissements/candidatures/<int:pk>/', etablissements_views.detail_candidature,
         name='detail_candidature'),
    path('etablissements/candidatures/<int:pk>/supprimer/', etablissements_views.supprimer_candidature,
         name='supprimer_candidature'),
    path('etablissements/mon-etablissement/', etablissements_views.mon_etablissement,
         name='mon_etablissement'),
    path('etablissements/personnel/', etablissements_views.liste_personnel, name='liste_personnel'),
    path('etablissements/abonnement/', etablissements_views.abonnement_detail, name='abonnement_detail'),
    path('etablissements/journal/', etablissements_views.journal_audit, name='journal_audit'),
    # dmp/
    path('dmp/patients/', dmp_views.rechercher_patient, name='rechercher_patient'),
    path('dmp/patients/creer/', dmp_views.creer_patient, name='creer_patient'),
    path('dmp/patients/<int:pk>/', dmp_views.detail_patient, name='detail_patient'),
    path('dmp/patients/<int:patient_pk>/dmp/', dmp_views.consulter_dmp, name='consulter_dmp'),
    path('dmp/patients/<int:patient_pk>/consultation/creer/', dmp_views.creer_consultation,
         name='creer_consultation'),
    path('dmp/consultations/', dmp_views.liste_consultations, name='liste_consultations'),
    path('dmp/consultations/<int:pk>/', dmp_views.detail_consultation, name='detail_consultation'),
    path('dmp/consultations/<int:consultation_pk>/ordonnance/creer/', dmp_views.creer_ordonnance,
         name='creer_ordonnance'),
    path('dmp/prescriptions/', dmp_views.liste_prescriptions, name='liste_prescriptions'),
    path('dmp/dashboard/', dmp_views.dmp_dashboard, name='dmp_dashboard'),
    path('dmp/patients/<int:patient_pk>/ordonnances/', dmp_views.mes_ordonnances,
         name='mes_ordonnances'),
    path('dmp/patients/<int:patient_pk>/historique/', dmp_views.mon_historique,
         name='mon_historique'),
    path('dmp/mes-ordonnances/', dmp_views.mes_ordonnances, name='mes_ordonnances_self'),
    path('dmp/mon-historique/', dmp_views.mon_historique, name='mon_historique_self'),
    path('dmp/mes-acces/', dmp_views.mon_acces_historique, name='mon_acces_historique_self'),
    path('dmp/patients/<int:patient_pk>/acces/', dmp_views.mon_acces_historique,
         name='mon_acces_historique'),
    path('dmp/acces/<int:acces_pk>/renvoyer/', dmp_views.renvoyer_notification_acces,
         name='renvoyer_notification_acces'),
    path('dmp/acces/<int:acces_pk>/repondre/', dmp_views.acces_dmp_repondre,
         name='acces_dmp_repondre'),
    # urgences/
    path('urgences/', urgences_views.liste_urgences, name='liste_urgences'),
    path('urgences/triage/', urgences_views.liste_triage, name='liste_triage'),
    path('urgences/identification/', urgences_views.liste_identification, name='liste_identification'),
    path('urgences/creer/', urgences_views.creer_dut, name='creer_dut'),
    path('urgences/<int:pk>/', urgences_views.detail_dut, name='detail_dut'),
    path('urgences/<int:pk>/correspondances/', urgences_views.correspondances_dut,
         name='correspondances_dut'),
    path('urgences/<int:dut_pk>/fiche-vitale/', urgences_views.fiche_vitale, name='fiche_vitale'),
    path('urgences/<int:dut_pk>/break-glass/', urgences_views.break_glass, name='break_glass'),
    path('urgences/<int:dut_pk>/triage/creer/', urgences_views.creer_triage, name='creer_triage'),
    path('urgences/<int:dut_pk>/constante/ajouter/', urgences_views.ajouter_constante,
         name='ajouter_constante'),
    path('urgences/<int:dut_pk>/rechercher-identite/', urgences_views.rechercher_identite,
         name='rechercher_identite'),
    path('urgences/recherche/<int:pk>/confirmer/', urgences_views.confirmer_identite,
         name='confirmer_identite'),
    path('urgences/<int:pk>/cloturer/', urgences_views.cloturer_dut, name='cloturer_dut'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Production sans Supabase Storage : sert les fichiers médias locaux
    # (avatars patients, photos DUT) depuis MEDIA_ROOT. Avec MEDIA_STORAGE=s3,
    # les URLs des médias proviennent du stockage (signées) — aucune vue locale.
    if os.getenv('MEDIA_STORAGE', '').lower() != 's3':
        urlpatterns += [
            re_path(
                r'^media/(?P<path>.*)$', serve,
                {'document_root': settings.MEDIA_ROOT},
            )
        ]