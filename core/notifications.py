"""Notifications par e-mail de MedShare.

Fonction réutilisable d'envoi d'e-mail utilisée par tous les flux de la
plateforme (candidature, création de compte patient, DUT / fusion, sécurité…).

Elle fonctionne avec le backend configuré dans settings.EMAIL_BACKEND :
- API HTTPS (Brevo / Resend) si EMAIL_PROVIDER et la clé API sont renseignés
  (port 443, utilisé sur Render car le SMTP sortant y est bloqué) ;
- backend SMTP (réel) si les variables SMTP sont renseignées dans le .env
  (fonctionne en local) ;
- backend console (affichage dans le terminal) sans aucun canal configuré.

Elle ne lève jamais d'exception bloquante : en cas d'échec d'envoi, un message
de secours est affiché à l'utilisateur via le framework de messages Django
pour ne jamais bloquer la démonstration.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.contrib import messages

from core.mail_backend import mode_email

import logging


def envoyer_email(request, destinataire, sujet, corps, secret_a_afficher=None,
                  erreur_message=None):
    """Envoie un e-mail via le backend configuré.

    Paramètres :
        request             — requête Django (peut être None pour un envoi sans IHM).
        destinataire        — adresse e-mail du destinataire.
        sujet               — objet de l'e-mail.
        corps               — corps texte de l'e-mail.
        erreur_message      — message d'erreur personnalisé (sinon message générique).

    Retourne True si l'envoi a réussi, False sinon.

    IMPORTANT : ne jamais afficher de secret (mot de passe provisoire, code 2FA…)
    à l'écran. L'ancien paramètre ``secret_a_afficher`` est conservé en
    signature uniquement pour compatibilité et n'est plus jamais utilisé.

    Robustesse (addendum 4, T2) : chaque échec d'envoi est journalisé avec le
    logger ``medshare.email`` pour permettre l'alerte e-mail en production,
    sans jamais faire échouer le flux de l'utilisateur.
    """
    logger = logging.getLogger('medshare.email')
    try:
        send_mail(
            sujet,
            corps,
            settings.DEFAULT_FROM_EMAIL or 'MedShare <no-reply@medshare.com>',
            [destinataire],
            fail_silently=False,
        )
        if request is not None and mode_email() == 'console':
            messages.info(
                request,
                'E-mail généré (mode démonstration) : contenu affiché dans le '
                'terminal du serveur.'
            )
        return True
    except Exception as exc:
        logger.warning(
            'Échec d\'envoi d\'e-mail vers %s — sujet : %s — canal : %s — '
            'erreur : %s',
            destinataire, sujet, mode_email(), exc,
        )
        if request is not None:
            messages.warning(
                request,
                erreur_message or
                f'E-mail non envoyé en démonstration (destinataire : {destinataire}).'
            )
        return False
