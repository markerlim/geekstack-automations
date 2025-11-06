from google.cloud import storage
from google.oauth2 import service_account
import json
from datetime import datetime

BUCKET_NAME = "images.geekstack.dev"
PREFIX = "UD/"
MANIFEST_FILE = "manifest.json"


def load_existing_manifest(bucket):
    try:
        blob = bucket.blob(MANIFEST_FILE)
        if blob.exists():
            content = blob.download_as_text()
            return json.loads(content)
    except Exception as e:
        print("No existing manifest found.", e)
    return {"version": "0.0", "lastUpdated": None, "assets": []}


def list_bucket_files(bucket):
    blobs = bucket.list_blobs(prefix=PREFIX)
    return [blob for blob in blobs if blob.name != MANIFEST_FILE]


def generate_incremental_manifest():
    credentials = service_account.Credentials.from_service_account_file("credentials/service-accountkey.json")
    client = storage.Client(credentials=credentials)
    bucket = client.bucket(BUCKET_NAME)

    manifest = load_existing_manifest(bucket)
    old_paths = set(asset["path"] for asset in manifest.get("assets", []))

    blobs = list_bucket_files(bucket)

    new_assets = []
    for blob in blobs:
        if blob.name not in old_paths:
            new_assets.append({
                "url": f"https://storage.googleapis.com/{BUCKET_NAME}/{blob.name}",
                "path": blob.name,
                "size": blob.size
            })

    if not new_assets:
        print("No new assets found.")
        return

    manifest["assets"].extend(new_assets)
    manifest["version"] = increment_version(manifest.get("version", "0.0"))
    manifest["lastUpdated"] = datetime.utcnow().isoformat()

    bucket.blob(MANIFEST_FILE).upload_from_string(
        json.dumps(manifest, indent=2),
        content_type="application/json"
    )

    print(f"Manifest updated with {len(new_assets)} new assets.")


def increment_version(version):
    major, minor = map(int, version.split("."))
    return f"{major}.{minor+1}"


if __name__ == "__main__":
    generate_incremental_manifest()
