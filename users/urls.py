from django.urls import path

from . import views

urlpatterns = [
    path('changer-mot-de-passe/', views.changer_mot_de_passe, name='changer_mot_de_passe'),
    path('mot-de-passe-modifie/', views.changer_mot_de_passe_succes,
         name='changer_mot_de_passe_succes'),
    path('acces/<str:jeton>/', views.dashboard_patient, name='dashboard_patient'),
    path('superadmin/2fa/', views.superadmin_2fa, name='superadmin_2fa'),
    path('superadmin/2fa/verifier/', views.superadmin_2fa_verifier, name='superadmin_2fa_verifier'),
    path('mot-de-passe-oublie/', views.mot_de_passe_oublie, name='mot_de_passe_oublie'),
    path('reinitialiser/<str:jeton>/', views.reinitialiser_mot_de_passe,
         name='reinitialiser_mot_de_passe'),
]
