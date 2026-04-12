import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mainProject.settings")
django.setup()

from TripApp.graphql.schema import schema

with open("schema.graphql", "w", encoding="utf-8") as f:
    f.write(schema.as_str())

print("Schema exported to schema.graphql")