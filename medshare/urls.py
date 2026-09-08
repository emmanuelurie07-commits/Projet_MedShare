from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

from core.views import dashboard, dashboard_personnel, super_abonnements, super_etablissements, super_rapports
from users.views import MedShareLoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Racine : le portail de connexion est le point d'entrée public.
    # Les candidats non membres soumettent une demande depuis cette page.
    path('', MedShareLoginView.as_view(), name='login'),
    path('dashboard/', dashboard, name='dashboard'),
    path('b/<str:jeton>/', dashboard_personnel, name='dashboard_personnel'),
    path('super/etablissements/', super_etablissements, name='super_etablissements'),
    path('super/abonnements/', super_abonnements, name='super_abonnements'),
    path('super/rapports/', super_rapports, name='super_rapports'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('compte/', include('users.urls')),
    path('etablissements/', include('establishments.urls')),
    path('dmp/', include('dmp.urls')),
    path('urgences/', include('urgences.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
