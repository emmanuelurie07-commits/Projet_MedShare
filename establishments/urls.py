from django.urls import path

from . import views

urlpatterns = [
    path('candidature/soumettre/', views.soumettre_candidature, name='soumettre_candidature'),
    path('candidature/confirmation/<int:pk>/', views.candidature_confirmation,
         name='candidature_confirmation'),
    path('candidature/consulter/', views.consulter_candidature, name='consulter_candidature'),
    path('candidatures/', views.gestion_candidatures, name='gestion_candidatures'),
    path('candidatures/<int:pk>/', views.detail_candidature, name='detail_candidature'),
    path('candidatures/<int:pk>/supprimer/', views.supprimer_candidature,
         name='supprimer_candidature'),
    path('mon-etablissement/', views.mon_etablissement, name='mon_etablissement'),
    path('personnel/', views.liste_personnel, name='liste_personnel'),
    path('abonnement/', views.abonnement_detail, name='abonnement_detail'),
    path('journal/', views.journal_audit, name='journal_audit'),
]
