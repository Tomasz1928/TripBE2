from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password


def register_user(username, password):
    if User.objects.filter(username=username).exists():
        return None
    return User.objects.create(username=username, password=make_password(password))

