#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Upload an Android APK release to the backend.

Required:
  APK_UPLOAD_BASE_URL   Backend base URL, for example https://127.0.0.1
  APK_UPLOAD_TOKEN      Release upload token from server env
  APK_PATH              Path to APK file

Optional:
  APK_METADATA_PATH     Gradle output-metadata.json; used to infer version fields
  APK_VERSION_NAME      Override version name
  APK_VERSION_CODE      Override version code
  APK_CHANGELOG         Release notes
  APK_UPLOAD_INSECURE   Set to 1 for self-signed HTTPS certificates

Example:
  APK_UPLOAD_BASE_URL="https://example.com" \
  APK_UPLOAD_TOKEN="replace-with-token" \
  APK_PATH="../-e2e-chat-client/app/build/outputs/apk/release/app-release.apk" \
  APK_METADATA_PATH="../-e2e-chat-client/app/build/outputs/apk/release/output-metadata.json" \
  APK_CHANGELOG="Release build" \
  APK_UPLOAD_INSECURE=1 \
  scripts/upload_apk_release.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

base_url="${APK_UPLOAD_BASE_URL:-}"
token="${APK_UPLOAD_TOKEN:-}"
apk_path="${APK_PATH:-}"
metadata_path="${APK_METADATA_PATH:-}"
version_name="${APK_VERSION_NAME:-}"
version_code="${APK_VERSION_CODE:-}"
changelog="${APK_CHANGELOG:-}"
insecure="${APK_UPLOAD_INSECURE:-0}"

if [[ -z "$base_url" || -z "$token" || -z "$apk_path" ]]; then
  usage >&2
  exit 2
fi

if [[ ! -f "$apk_path" ]]; then
  echo "APK file not found: $apk_path" >&2
  exit 2
fi

if [[ -n "$metadata_path" && -f "$metadata_path" ]]; then
  if [[ -z "$version_name" ]]; then
    version_name="$(
      python3 - "$metadata_path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    metadata = json.load(fh)
print(metadata["elements"][0]["versionName"])
PY
    )"
  fi
  if [[ -z "$version_code" ]]; then
    version_code="$(
      python3 - "$metadata_path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    metadata = json.load(fh)
print(metadata["elements"][0]["versionCode"])
PY
    )"
  fi
fi

if [[ -z "$version_name" || -z "$version_code" ]]; then
  echo "APK_VERSION_NAME and APK_VERSION_CODE are required when metadata is absent." >&2
  exit 2
fi

endpoint="${base_url%/}/api/v1/files/apk/upload"
curl_args=(--fail-with-body --show-error --silent)
if [[ "$insecure" == "1" || "$insecure" == "true" ]]; then
  curl_args+=(--insecure)
fi

curl "${curl_args[@]}" \
  --request POST "$endpoint" \
  --header "X-APK-Upload-Token: $token" \
  --form "version_name=$version_name" \
  --form "version_code=$version_code" \
  --form "changelog=$changelog" \
  --form "file=@${apk_path};type=application/vnd.android.package-archive"

echo
