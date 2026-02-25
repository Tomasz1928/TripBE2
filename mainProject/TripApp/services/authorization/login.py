from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError


def login_user(request, username, password):
    user = authenticate(request, username=username, password=password)
    if not user:
        raise ValidationError("Invalid login")
    login(request, user)
    return True


def logout_user(request):
    logout(request)


def session(request):
    return request.user.is_authenticated
