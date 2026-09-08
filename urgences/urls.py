from django.urls import path

from . import views

urlpatterns = [
    path('', views.liste_urgences, name='liste_urgences'),
    path('triage/', views.liste_triage, name='liste_triage'),
    path('identification/', views.liste_identification, name='liste_identification'),
    path('creer/', views.creer_dut, name='creer_dut'),
    path('<int:pk>/', views.detail_dut, name='detail_dut'),
    # Étape 2 : résultats comparatifs (3-5 meilleures correspondances >60%)
    path('<int:pk>/correspondances/', views.correspondances_dut, name='correspondances_dut'),
    # Fiche vitale & Break Glass (Étape 3)
    path('<int:dut_pk>/fiche-vitale/', views.fiche_vitale, name='fiche_vitale'),
    path('<int:dut_pk>/break-glass/', views.break_glass, name='break_glass'),
    path('<int:dut_pk>/triage/creer/', views.creer_triage, name='creer_triage'),
    path('<int:dut_pk>/constante/ajouter/', views.ajouter_constante, name='ajouter_constante'),
    path('<int:dut_pk>/rechercher-identite/', views.rechercher_identite,
         name='rechercher_identite'),
    # Confirmation & fusion (médecin uniquement) — POST
    path('recherche/<int:pk>/confirmer/', views.confirmer_identite, name='confirmer_identite'),
    path('<int:pk>/cloturer/', views.cloturer_dut, name='cloturer_dut'),
]
