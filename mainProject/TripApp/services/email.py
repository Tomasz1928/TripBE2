"""
TripApp/email_service.py

Mailjet integration for transactional emails.
Requires environment variables:
    MAILJET_API_KEY     — Mailjet public API key
    MAILJET_API_SECRET  — Mailjet secret API key
    MAILJET_FROM_EMAIL  — verified sender address (e.g. noreply@yourdomain.com)
    MAILJET_FROM_NAME   — sender display name (e.g. TripApp)
"""

import os
from mailjet_rest import Client


def _get_client() -> Client:
    api_key = os.environ.get("MAILJET_API_KEY", "bd64f2a2d047bacf4037ee0fcac6a1a1")
    api_secret = os.environ.get("MAILJET_API_SECRET", "5c655b902c2df45f2c83a8219f1ea757")
    if not api_key or not api_secret:
        raise RuntimeError(
            "Mailjet credentials missing. Set MAILJET_API_KEY and MAILJET_API_SECRET."
        )
    return Client(auth=(api_key, api_secret), version="v3.1")


def send_new_password_email(to_email: str, username: str, new_password: str) -> None:
    """
    Send an email containing the auto-generated new password.

    Raises RuntimeError if the Mailjet API returns a non-2xx status.
    """
    from_email = os.environ.get("MAILJET_FROM_EMAIL", "trip.calculator.servis@gmail.com")
    from_name = os.environ.get("MAILJET_FROM_NAME", "TripApp")

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px;">
      <h2 style="color: #136DEC; margin-bottom: 8px;">TripApp</h2>
      <p style="color: #0D131B; font-size: 16px; margin-bottom: 24px;">
        Cześć <strong>{username}</strong>,
      </p>
      <p style="color: #4C6C9A; font-size: 14px; margin-bottom: 16px;">
        Otrzymaliśmy prośbę o zresetowanie hasła do Twojego konta.
        Oto Twoje nowe, tymczasowe hasło:
      </p>
      <div style="background: #F6F7F8; border-radius: 12px; padding: 16px 24px;
                  text-align: center; margin-bottom: 24px;">
        <span style="font-size: 22px; font-weight: 700; color: #136DEC;
                     letter-spacing: 2px;">{new_password}</span>
      </div>
      <p style="color: #4C6C9A; font-size: 13px; margin-bottom: 8px;">
        Zaloguj się tym hasłem i zmień je od razu w sekcji
        <strong>Opcje → Moje dane → Hasło</strong>.
      </p>
      <p style="color: #9CA3AF; font-size: 12px;">
        Jeśli to nie Ty prosiłeś o reset hasła, zignoruj tę wiadomość.
        Twoje poprzednie hasło przestało działać.
      </p>
      <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 24px 0;" />
      <p style="color: #9CA3AF; font-size: 11px; text-align: center;">
        TripApp — wspólne podróże, bez rachunkowych sporów.
      </p>
    </div>
    """

    text_body = (
        f"Cześć {username},\n\n"
        f"Twoje nowe hasło do TripApp: {new_password}\n\n"
        f"Zaloguj się i zmień je w sekcji Opcje → Moje dane → Hasło.\n\n"
        f"Jeśli nie prosiłeś o reset, zignoruj tę wiadomość."
    )

    data = {
        "Messages": [
            {
                "From": {"Email": from_email, "Name": from_name},
                "To": [{"Email": to_email, "Name": username}],
                "Subject": "Twoje nowe hasło do TripApp",
                "TextPart": text_body,
                "HTMLPart": html_body,
            }
        ]
    }

    client = _get_client()
    result = client.send.create(data=data)

    if result.status_code not in (200, 201):
        raise RuntimeError(
            f"Mailjet error {result.status_code}: {result.json()}"
        )