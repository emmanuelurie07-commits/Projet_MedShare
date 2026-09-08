from django.urls import path

from . import views

urlpatterns = [
    path('patients/', views.rechercher_patient, name='rechercher_patient'),
    path('patients/creer/', views.creer_patient, name='creer_patient'),
    path('patients/<int:pk>/', views.detail_patient, name='detail_patient'),
    path('patients/<int:patient_pk>/dmp/', views.consulter_dmp, name='consulter_dmp'),
    path('patients/<int:patient_pk>/consultation/creer/', views.creer_consultation,
         name='creer_consultation'),
    path('consultations/', views.liste_consultations, name='liste_consultations'),
    path('consultations/<int:pk>/', views.detail_consultation, name='detail_consultation'),
    path('consultations/<int:consultation_pk>/ordonnance/creer/', views.creer_ordonnance,
         name='creer_ordonnance'),
    path('prescriptions/', views.liste_prescriptions, name='liste_prescriptions'),
    path('dashboard/', views.dmp_dashboard, name='dmp_dashboard'),
    path('patients/<int:patient_pk>/ordonnances/', views.mes_ordonnances, name='mes_ordonnances'),
    path('patients/<int:patient_pk>/historique/', views.mon_historique, name='mon_historique'),
    path('mes-ordonnances/', views.mes_ordonnances, name='mes_ordonnances_self'),
    path('mon-historique/', views.mon_historique, name='mon_historique_self'),
    path('mes-acces/', views.mon_acces_historique, name='mon_acces_historique_self'),
    path('patients/<int:patient_pk>/acces/', views.mon_acces_historique, name='mon_acces_historique'),
    path('acces/<int:acces_pk>/renvoyer/', views.renvoyer_notification_acces, name='renvoyer_notification_acces'),
    path('acces/<int:acces_pk>/repondre/', views.acces_dmp_repondre, name='acces_dmp_repondre'),
]
