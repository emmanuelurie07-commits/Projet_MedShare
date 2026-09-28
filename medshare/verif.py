"""Diagnostic temporaire de déploiement (Vercel) — partie EMAIL — à retirer ensuite."""
import os
import smtplib

from django.http import JsonResponse


def verif(request):
    if request.GET.get('jeton', '') != os.getenv('SUPERADMIN_INITIAL_PASSWORD', ''):
        return JsonResponse({'erreur': 'acces refuse'}, status=403)

    try:
        from core.mail_backend import mode_email
        rapport = {'mode': mode_email(), 'provider': os.getenv('EMAIL_PROVIDER', ''),
                   'host': os.getenv('EMAIL_HOST', ''), 'port': os.getenv('EMAIL_PORT', ''),
                   'use_tls': os.getenv('EMAIL_USE_TLS', ''),
                   'user(defini)': bool(os.getenv('EMAIL_HOST_USER', '')),
                   'mdp(len)': len(os.getenv('EMAIL_HOST_PASSWORD', '')),
                   'brevo_api_key(defini)': bool(os.getenv('BREVO_API_KEY', '')),
                   'from': os.getenv('DEFAULT_FROM_EMAIL', '')}
    except Exception as e:
        rapport = {'erreur_preambule': f'{type(e).__name__}: {e}'}

    if request.GET.get('essai') == 'mail':
        try:
            msg = ('De: MedShare <emmanuelurie07@gmail.com>\r\n'
                   'To: emmanuelurie07@gmail.com\r\n'
                   'Subject: Test MedShare - sonde Vercel\r\n\r\n'
                   'Sonde SMTP depuis la fonction Vercel.')
            s = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login('emmanuelurie07@gmail.com', os.getenv('EMAIL_HOST_PASSWORD', ''))
            s.sendmail('emmanuelurie07@gmail.com', ['emmanuelurie07@gmail.com'], msg)
            s.quit()
            rapport['envoi_smtp'] = 'OK'
        except Exception as e:
            rapport['envoi_smtp'] = f'{type(e).__name__}: {e}'

    if request.GET.get('essai') == 'django':
        try:
            from django.core.mail import send_mail
            from core.mail_backend import EmailBackend
            from django.core.mail import get_connection
            rapport['backend_actif'] = str(get_connection().__class__)
            send_mail('Test MedShare - send_mail Vercel', 'Corps de test.',
                      os.getenv('DEFAULT_FROM_EMAIL', 'MedShare <emmanuelurie07@gmail.com>'),
                      ['emmanuelurie07@gmail.com'], fail_silently=False)
            rapport['send_mail'] = 'OK'
        except Exception as e:
            rapport['send_mail'] = f'{type(e).__name__}: {e}'

    return JsonResponse(rapport)