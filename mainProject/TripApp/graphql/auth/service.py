from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest
from asgiref.sync import sync_to_async


async def register_user(request: HttpRequest, username: str, password: str) -> dict:
    username = username.strip()
    password = password.strip()

    if not username or not password:
        return {"success": False, "message": "Username and password are required."}

    if len(username) < 3:
        return {"success": False, "message": "Username must be at least 3 characters."}

    if len(password) < 6:
        return {"success": False, "message": "Password must be at least 6 characters."}

    exists = await sync_to_async(User.objects.filter(username=username).exists)()
    if exists:
        return {"success": False, "message": "Username already taken."}

    user = await sync_to_async(User.objects.create_user)(username=username, password=password)
    await sync_to_async(login)(request, user)

    return {"success": True, "message": "Account created successfully.", "user": user}


async def login_user(request: HttpRequest, username: str, password: str) -> dict:
    user = await sync_to_async(authenticate)(request, username=username, password=password)

    if user is None:
        return {"success": False, "message": "Invalid username or password."}

    await sync_to_async(login)(request, user)

    return {"success": True, "message": "Logged in successfully.", "user": user}


async def logout_user(request: HttpRequest) -> dict:
    is_auth = await sync_to_async(lambda: request.user.is_authenticated)()

    if not is_auth:
        return {"success": False, "message": "Not logged in."}

    await sync_to_async(logout)(request)

    return {"success": True, "message": "Logged out successfully."}


async def get_session(request: HttpRequest) -> dict:
    user = await sync_to_async(lambda: request.user)()
    is_auth = await sync_to_async(lambda: user.is_authenticated)()

    if is_auth:
        return {"is_authenticated": True, "user": user}

    return {"is_authenticated": False, "user": None}