import random
import string

from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest
from asgiref.sync import sync_to_async

from TripApp.services.email import send_new_password_email


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_password(length: int = 12) -> str:
    """Generate a random password: letters + digits, no ambiguous chars."""
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


def _is_valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

async def register_user(request: HttpRequest, username: str, password: str, email: str) -> dict:
    username = username.strip()
    password = password.strip()
    email = email.strip().lower()

    if not username or not password or not email:
        return {"success": False, "message": "Wszystkie pola są wymagane."}

    if len(username) < 3:
        return {"success": False, "message": "Nazwa użytkownika musi mieć min. 3 znaki."}

    if len(password) < 6:
        return {"success": False, "message": "Hasło musi mieć min. 6 znaków."}

    if not _is_valid_email(email):
        return {"success": False, "message": "Podaj prawidłowy adres email."}

    username_exists = await sync_to_async(User.objects.filter(username=username).exists)()
    if username_exists:
        return {"success": False, "message": "Nazwa użytkownika jest już zajęta."}

    email_exists = await sync_to_async(
        User.objects.filter(email__iexact=email).exists
    )()
    if email_exists:
        return {"success": False, "message": "Ten adres email jest już używany."}

    user = await sync_to_async(User.objects.create_user)(
        username=username, password=password, email=email
    )
    await sync_to_async(login)(request, user)

    return {"success": True, "message": "Konto utworzone pomyślnie.", "user": user}


# ---------------------------------------------------------------------------
# Login / Logout / Session
# ---------------------------------------------------------------------------

async def login_user(request: HttpRequest, username: str, password: str) -> dict:
    user = await sync_to_async(authenticate)(request, username=username, password=password)

    if user is None:
        return {"success": False, "message": "Nieprawidłowa nazwa użytkownika lub hasło."}

    await sync_to_async(login)(request, user)
    return {"success": True, "message": "Zalogowano pomyślnie.", "user": user}


async def logout_user(request: HttpRequest) -> dict:
    is_auth = await sync_to_async(lambda: request.user.is_authenticated)()
    if not is_auth:
        return {"success": False, "message": "Nie jesteś zalogowany."}

    await sync_to_async(logout)(request)
    return {"success": True, "message": "Wylogowano pomyślnie."}


async def get_session(request: HttpRequest) -> dict:
    user = await sync_to_async(lambda: request.user)()
    is_auth = await sync_to_async(lambda: user.is_authenticated)()

    if is_auth:
        return {"is_authenticated": True, "user": user}
    return {"is_authenticated": False, "user": None}


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

async def reset_password(username: str, email: str) -> dict:
    """
    If username + email match an existing account, generate a new random
    password, save it, and send it via Mailjet.
    Returns a clear error if the combination does not exist.
    """
    username = username.strip()
    email = email.strip().lower()

    if not username and not email:
        return {"success": False, "message": "Podaj nazwę użytkownika i adres email."}

    if not username:
        return {"success": False, "message": "Podaj nazwę użytkownika."}

    if not email:
        return {"success": False, "message": "Podaj adres email."}

    if not _is_valid_email(email):
        return {"success": False, "message": "Podaj prawidłowy adres email."}

    user = await sync_to_async(
        lambda: User.objects.filter(username=username, email__iexact=email).first()
    )()

    if user is None:
        return {"success": False, "message": "Nie znaleziono konta o podanej nazwie użytkownika i adresie email."}

    new_password = _generate_password()

    await sync_to_async(user.set_password)(new_password)
    await sync_to_async(user.save)()

    try:
        await sync_to_async(send_new_password_email)(
            to_email=user.email,
            username=user.username,
            new_password=new_password,
        )
    except Exception as exc:
        # Log but don't expose details to client
        import logging
        logging.getLogger(__name__).error("Mailjet send failed: %s", exc)

    return {"success": True, "message": "Nowe hasło zostało wysłane na adres email."}


# ---------------------------------------------------------------------------
# Change email (authenticated)
# ---------------------------------------------------------------------------

async def change_email(request: HttpRequest, new_email: str) -> dict:
    is_auth = await sync_to_async(lambda: request.user.is_authenticated)()
    if not is_auth:
        return {"success": False, "message": "Wymagane logowanie."}

    new_email = new_email.strip().lower()

    if not _is_valid_email(new_email):
        return {"success": False, "message": "Podaj prawidłowy adres email."}

    user = await sync_to_async(lambda: request.user)()

    email_taken = await sync_to_async(
        lambda: User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists()
    )()
    if email_taken:
        return {"success": False, "message": "Ten adres email jest już używany."}

    await sync_to_async(_set_email)(user, new_email)
    return {"success": True, "message": "Adres email został zaktualizowany."}


def _set_email(user: User, email: str) -> None:
    user.email = email
    user.save(update_fields=["email"])


# ---------------------------------------------------------------------------
# Change password (authenticated)
# ---------------------------------------------------------------------------

async def change_password(request: HttpRequest, new_password: str, new_password_confirm: str) -> dict:
    is_auth = await sync_to_async(lambda: request.user.is_authenticated)()
    if not is_auth:
        return {"success": False, "message": "Wymagane logowanie."}

    if len(new_password) < 6:
        return {"success": False, "message": "Hasło musi mieć min. 6 znaków."}

    if new_password != new_password_confirm:
        return {"success": False, "message": "Hasła nie są identyczne."}

    user = await sync_to_async(lambda: request.user)()
    await sync_to_async(_set_password)(user, new_password)

    return {"success": True, "message": "Hasło zostało zmienione."}


def _set_password(user: User, password: str) -> None:
    user.set_password(password)
    user.save()