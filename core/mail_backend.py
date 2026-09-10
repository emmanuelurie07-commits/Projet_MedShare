"""Backend e-mail MedShare.

Le SMTP sortant (ports 25/587/465) est bloqué sur les plans standard de
certains hébergeurs (Render, Railway…) : la connexion échoue immédiatement
avec « [Errno 101] Network is unreachable » alors que le site (HTTPS/443)
fonctionne. Pour garantir une livraison partout, on peut basculer sur une
API transactionnelle par HTTPS (443, jamais bloquée) :

    EMAIL_PROVIDER=brevo    + BREVO_API_KEY   → API Brevo  (gratuit, 300/jour)
    EMAIL_PROVIDER=resend   + RESEND_API_KEY  → API Resend (gratuit, 3000/mois)

Sans EMAIL_PROVIDER, le backend conserve le comportement historique :
SMTP si les variables EMAIL_HOST* sont renseignées, sinon console (démo).
"""

import email.utils
import json
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


def _adresse_envelope(dest):
    """Du « Truc <a@b.com> » vers une simple adresse (sinon l'API la refuse)."""
    _, adresse = email.utils.parseaddr(dest or '')
    return (adresse or (dest or '')).strip()


def _expediteur():
    """Adresse d'envoi (sans le nom affiché pour les API qui l'exigent)."""
    return _adresse_envelope(settings.DEFAULT_FROM_EMAIL)


def mode_email():
    """Canal effectif de l'e-mail : 'api', 'smtp' ou 'console'."""
    provider = os.getenv('EMAIL_PROVIDER', '').lower()
    if provider == 'brevo' and os.getenv('BREVO_API_KEY'):
        return 'api'
    if provider == 'resend' and os.getenv('RESEND_API_KEY'):
        return 'api'
    if all(os.getenv(k) for k in ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD')):
        return 'smtp'
    return 'console'


class EmailBackend(BaseEmailBackend):
    """Choix du canal selon l'environnement : API HTTPS, SMTP ou console."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.provider = os.getenv('EMAIL_PROVIDER', '').lower()
        # `.strip()` : les clés API copiées depuis un tableau de bord peuvent
        # trainer un saut de ligne final — un header invalide fait échouer
        # l'envoi (`Invalid header value ... \n`).
        self.cle = {
            'brevo': os.getenv('BREVO_API_KEY', '').strip() or None,
            'resend': os.getenv('RESEND_API_KEY', '').strip() or None,
        }.get(self.provider) if self.provider in ('brevo', 'resend') else None
        if self.provider in ('brevo', 'resend') and not self.cle:
            import logging
            logging.getLogger('medshare.email').warning(
                'EMAIL_PROVIDER=%s mais %s manquant '
                '(BREVO_API_KEY/RESEND_API_KEY) — repli démo.',
                self.provider, self.provider.upper())
            self.provider = ''
        if not self.provider:
            if all(os.getenv(k) for k in ('EMAIL_HOST', 'EMAIL_HOST_USER',
                                          'EMAIL_HOST_PASSWORD')):
                from django.core.mail.backends.smtp import EmailBackend as SMTP
                self._relais = SMTP(fail_silently=fail_silently, **kwargs)
            else:
                from django.core.mail.backends.console import \
                    EmailBackend as Console
                self._relais = Console(fail_silently=fail_silently, **kwargs)
        self.mode = mode_email()

    # ── Point d'entrée Django ─────────────────────────────────────────────
    def send_messages(self, messages):
        if self.provider:
            ok = 0
            for m in messages:
                try:
                    self._envoyer_api(m)
                    ok += 1
                except Exception:
                    if not self.fail_silently:
                        raise
            return ok
        return self._relais.send_messages(messages)

    # ── Envoi par API HTTPS ───────────────────────────────────────────────
    def _envoyer_api(self, message):
        if self.provider == 'brevo':
            url = 'https://api.brevo.com/v3/smtp/email'
            corps = {
                'sender': {'email': _expediteur()},
                'to': [{'email': _adresse_envelope(d)}
                       for d in message.recipients()],
                'subject': message.subject,
                'textContent': message.body,
            }
            requete = urllib.request.Request(
                url, data=json.dumps(corps).encode('utf-8'),
                headers={'api-key': self.cle, 'Content-Type': 'application/json'})
        elif self.provider == 'resend':
            url = 'https://api.resend.com/emails'
            corps = {
                'from': settings.DEFAULT_FROM_EMAIL,
                'to': [d for d in message.recipients()],
                'subject': message.subject,
                'text': message.body,
            }
            requete = urllib.request.Request(
                url, data=json.dumps(corps).encode('utf-8'),
                headers={'Authorization': f'Bearer {self.cle}',
                         'Content-Type': 'application/json'})
        else:
            raise RuntimeError('Fournisseur e-mail inconnu.')
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            if reponse.status >= 400:
                raise RuntimeError(f'API e-mail HTTP {reponse.status}')