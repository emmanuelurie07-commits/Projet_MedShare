from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import redirect
from functools import wraps


def role_required(*roles_noms):
    """
    Décorateur qui vérifie que l'utilisateur possède au moins un des rôles indiqués.
    Usage: @role_required('Médecin', 'Infirmier')
    Super admin bypass inclus (ancien comportement).
    """
    def decorateur(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'{settings.LOGIN_URL}?next={request.path}')
            user_roles = getattr(request, 'user_roles', set())
            if request.user.is_superuser or any(r in user_roles for r in roles_noms):
                return view_func(request, *args, **kwargs)
            from django.contrib import messages
            messages.error(request, 'Vous n\'avez pas les droits nécessaires pour accéder à cette page.')
            return redirect('dashboard')
        return wrapper
    return decorateur


def role_required_strict(*roles_noms):
    """Même que role_required mais super admin n'est PAS autorisé."""
    def decorateur(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'{settings.LOGIN_URL}?next={request.path}')
            if request.user.is_superuser:
                from django.contrib import messages
                messages.error(request, 'Accès réservé au personnel médical.')
                return redirect('dashboard')
            user_roles = getattr(request, 'user_roles', set())
            if any(r in user_roles for r in roles_noms):
                return view_func(request, *args, **kwargs)
            from django.contrib import messages
            messages.error(request, 'Vous n\'avez pas les droits nécessaires pour accéder à cette page.')
            return redirect('dashboard')
        return wrapper
    return decorateur


def admin_etablissement_required(view_func):
    """Vérifie que l'utilisateur est administrateur de son établissement."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{settings.LOGIN_URL}?next={request.path}')
        user_roles = getattr(request, 'user_roles', set())
        if request.user.is_superuser or 'Administrateur' in user_roles:
            return view_func(request, *args, **kwargs)
        from django.contrib import messages
        messages.error(request, 'Accès réservé aux administrateurs d\'établissement.')
        return redirect('dashboard')
    return wrapper


def admin_etablissement_required_strict(view_func):
    """Admin établissement uniquement, super admin bloqué."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{settings.LOGIN_URL}?next={request.path}')
        if request.user.is_superuser:
            from django.contrib import messages
            messages.error(request, 'Super admin : utilisez /super/etablissements/ et /super/abonnements/.')
            return redirect('dashboard')
        user_roles = getattr(request, 'user_roles', set())
        if 'Administrateur' in user_roles:
            return view_func(request, *args, **kwargs)
        from django.contrib import messages
        messages.error(request, 'Accès réservé aux administrateurs d\'établissement.')
        return redirect('dashboard')
    return wrapper


def super_admin_required(view_func):
    """Vérifie que l'utilisateur est super administrateur."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{settings.LOGIN_URL}?next={request.path}')
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        from django.contrib import messages
        messages.error(request, 'Accès réservé aux super administrateurs.')
        return redirect('dashboard')
    return wrapper


def block_superadmin(view_func):
    """Bloque le super admin sur les vues médicales."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            from django.contrib import messages
            messages.error(request, 'Super admin : accès limité à établissements, abonnements et journaux.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper
