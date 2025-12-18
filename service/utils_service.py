def find_missing_values(json_values, website_values):
    json_set = set(json_values)
    website_set = set(website_values)

    print(f"\n🧪 Debug: {len(json_set)} JSON values vs {len(website_set)} website values")
    return sorted(website_set - json_set)