# Filtres de template pour la sidebar : comparaison EXACTE des noms d'URL.
# La comparaison « nom de page en cours ∈ groupe » doit être exacte et non une
# sous-chaîne (ex. 'dashboard' n'est PAS un membre de 'dmp_dashboard ...').
from django import template

register = template.Library()


@register.filter
def in_urls(url_name, groupe):
    """Vrai si ``url_name`` appartient exactement au groupe (liste de noms
    d'URL séparés par des espaces)."""
    if not url_name:
        return False
    return url_name in groupe.split()