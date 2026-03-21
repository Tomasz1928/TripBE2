from TripApp.graphql.schema import schema  # import schemy

with open("schema.graphql", "w", encoding="utf-8") as f:
    f.write(schema.as_str())

print("Schema exported to schema.graphql")