# IP-only HTTPS/WSS deploy

This mode is intended for a private Android client that talks to the backend by IP address instead of a domain.

## What it does

- serves only `https://<SERVER_IP>` and `wss://<SERVER_IP>/api/v1/ws`
- uses a private root CA and a server certificate with the IP in SAN
- requires the Android client to trust `deploy/certs/ca.crt` or pin the server certificate/public key

## 1. Generate certificates

Run on the server or locally before copying deploy files:

```bash
bash deploy/scripts/generate_ip_cert.sh <SERVER_IP>
```

Generated files:

- `deploy/certs/ca.crt`
- `deploy/certs/server.crt`
- `deploy/certs/server.key`

## 2. Configure `.env`

Start from `deploy/env.prod.example` and set:

```dotenv
APP_ENV=production
DEBUG=false

CADDY_CONFIG=Caddyfile.ip-selfsigned
SERVER_IP=<SERVER_IP>
CADDY_HTTP_BIND=127.0.0.1:80
CADDY_HTTPS_BIND=443
FCM_CREDENTIALS_PATH=/run/secrets/fcm_service_account.json

BACKEND_CORS_ORIGINS=https://<SERVER_IP>
TRUSTED_HOSTS=<SERVER_IP>,localhost,127.0.0.1
```

Notes:

- CORS does not matter for a native Android client, but the backend requires a non-`*` value in production.
- WebSocket origin checks are not implemented separately; TLS and auth still apply.
- With `CADDY_HTTP_BIND=127.0.0.1:80`, only `443` is reachable from outside.

## 3. Provide Firebase credentials

Put Firebase Admin SDK service account JSON here:

- `deploy/secrets/fcm_service_account.json`

This is **not** `google-services.json`.

## 4. Run

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build
```

## 5. Android trust

The Android app must trust `deploy/certs/ca.crt` or use certificate/public-key pinning.

Without this, default Android TLS verification will reject the connection even though the server is using HTTPS/WSS.
