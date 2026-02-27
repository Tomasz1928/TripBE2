import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mainProject.settings")
django.setup()

from TripApp.graphql.schema import schema
print(schema.as_str())