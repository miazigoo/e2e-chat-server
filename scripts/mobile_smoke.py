#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import email
import hashlib
import http.server
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx
import websockets
from psycopg import connect as pg_connect
from redis import Redis

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.totp import _generate_totp_code  # noqa: E402

DEFAULT_HTTP_PORT = 8010
DEFAULT_SMTP_PORT = 1025
DEFAULT_ENV_FILE = ".env.example"
USER_AGENT = "secure-chat-mobile-smoke/1.0"
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc`\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class SmokeFailure(RuntimeError):
    pass


@dataclass
class RuntimeHandle:
    backend: subprocess.Popen[str]
    smtp: subprocess.Popen[str]
    s3: subprocess.Popen[str]
    postgres_container: str
    redis_container: str
    postgres_port: int
    redis_port: int
    backend_log: Path
    smtp_log: Path
    smtp_sink: Path
    s3_log: Path


@dataclass
class AuthState:
    nickname: str
    password: str
    email: str | None
    user_id: int
    device_uuid: str
    access_token: str
    refresh_token: str


class FakeSmtpServer:
    def __init__(self, host: str, port: int, sink_path: Path) -> None:
        self.host = host
        self.port = port
        self.sink_path = sink_path

    async def run(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        async with server:
            await server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await self._send(writer, "220 fake-smtp ESMTP ready")
        in_data = False
        message_lines: list[str] = []

        try:
            while not reader.at_eof():
                raw_line = await reader.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

                if in_data:
                    if line == ".":
                        self._persist_message("\n".join(message_lines))
                        message_lines.clear()
                        in_data = False
                        await self._send(writer, "250 message accepted")
                    else:
                        message_lines.append(line)
                    continue

                upper = line.upper()
                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    await self._send(writer, "250-fake-smtp")
                    await self._send(writer, "250 SIZE 10485760")
                elif upper.startswith("MAIL FROM:"):
                    await self._send(writer, "250 sender ok")
                elif upper.startswith("RCPT TO:"):
                    await self._send(writer, "250 recipient ok")
                elif upper == "DATA":
                    in_data = True
                    await self._send(writer, "354 end with <CR><LF>.<CR><LF>")
                elif upper == "RSET":
                    message_lines.clear()
                    in_data = False
                    await self._send(writer, "250 reset ok")
                elif upper == "NOOP":
                    await self._send(writer, "250 ok")
                elif upper == "QUIT":
                    await self._send(writer, "221 bye")
                    break
                else:
                    await self._send(writer, "250 ok")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _send(self, writer: asyncio.StreamWriter, line: str) -> None:
        writer.write(f"{line}\r\n".encode("utf-8"))
        await writer.drain()

    def _persist_message(self, payload: str) -> None:
        self.sink_path.parent.mkdir(parents=True, exist_ok=True)
        with self.sink_path.open("a", encoding="utf-8") as handle:
            handle.write(f"--- message {datetime.now(UTC).isoformat()} ---\n")
            handle.write(payload)
            handle.write("\n")


class FakeS3Handler(http.server.BaseHTTPRequestHandler):
    server_version = "FakeS3/1.0"

    def do_PUT(self) -> None:  # noqa: N802
        bucket, key = self._split_path()
        if not bucket:
            self.send_error(400, "bucket required")
            return

        bucket_path = self._bucket_path(bucket)
        if key is None:
            bucket_path.mkdir(parents=True, exist_ok=True)
            self.send_response(200)
            self.end_headers()
            return

        bucket_path.mkdir(parents=True, exist_ok=True)
        object_path = bucket_path / key
        object_path.parent.mkdir(parents=True, exist_ok=True)

        copy_source = self.headers.get("x-amz-copy-source")
        if copy_source:
            src_bucket, src_key = self._split_copy_source(copy_source)
            src_path = self._bucket_path(src_bucket) / src_key
            if not src_path.exists():
                self.send_error(404, "copy source not found")
                return
            object_path.write_bytes(src_path.read_bytes())
        else:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            object_path.write_bytes(payload)

        self.send_response(200)
        self.send_header("ETag", self._etag(object_path))
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        bucket, key = self._split_path()
        if not bucket:
            self.send_error(400, "bucket required")
            return

        bucket_path = self._bucket_path(bucket)
        if key is None:
            if not bucket_path.exists():
                self.send_error(404, "bucket not found")
                return
            self.send_response(200)
            self.end_headers()
            return

        object_path = bucket_path / key
        if not object_path.exists():
            self.send_error(404, "object not found")
            return

        stat = object_path.stat()
        self.send_response(200)
        self.send_header("Content-Length", str(stat.st_size))
        self.send_header("ETag", self._etag(object_path))
        self.send_header(
            "Last-Modified",
            self.date_time_string(stat.st_mtime),
        )
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        bucket, key = self._split_path()
        if not bucket:
            self.send_error(400, "bucket required")
            return

        bucket_path = self._bucket_path(bucket)
        if key is None:
            if not bucket_path.exists():
                self.send_error(404, "bucket not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            self.wfile.write(b"<ListBucketResult/>")
            return

        object_path = bucket_path / key
        if not object_path.exists():
            self.send_error(404, "object not found")
            return

        payload = object_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("ETag", self._etag(object_path))
        self.end_headers()
        self.wfile.write(payload)

    def do_DELETE(self) -> None:  # noqa: N802
        bucket, key = self._split_path()
        if not bucket or key is None:
            self.send_error(400, "object path required")
            return

        object_path = self._bucket_path(bucket) / key
        if object_path.exists():
            object_path.unlink()
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)

    def _root(self) -> Path:
        return Path(self.server.root_dir)  # type: ignore[attr-defined]

    def _bucket_path(self, bucket: str) -> Path:
        return self._root() / bucket

    def _split_path(self) -> tuple[str | None, str | None]:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path).lstrip("/")
        if not path:
            return None, None
        parts = path.split("/", 1)
        if len(parts) == 1:
            return parts[0], None
        return parts[0], parts[1]

    def _split_copy_source(self, header_value: str) -> tuple[str, str]:
        path = unquote(header_value).lstrip("/")
        bucket, key = path.split("/", 1)
        return bucket, key

    def _etag(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


class FakeS3Server(http.server.ThreadingHTTPServer):
    def __init__(self, host: str, port: int, root_dir: Path) -> None:
        super().__init__((host, port), FakeS3Handler)
        self.root_dir = str(root_dir)


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        device_uuid: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.device_uuid = device_uuid
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int = 200,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
        auth: bool = True,
        device: bool = False,
        extra_headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        headers: dict[str, str] = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if device and self.device_uuid:
            headers["X-Device-UUID"] = self.device_uuid
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)

        response = await self.http.request(
            method,
            path,
            json=json_body,
            params=params,
            files=files,
            content=content,
            headers=headers,
        )

        if response.status_code != expected_status:
            label = f"{method} {path}"
            body = response.text
            if response.status_code == 404:
                raise SmokeFailure(f"{label} returned 404\n{body}")
            if response.status_code >= 500:
                raise SmokeFailure(f"{label} returned {response.status_code}\n{body}")
            raise SmokeFailure(
                f"{label} returned {response.status_code}, expected {expected_status}\n"
                f"{body}"
            )

        if not expect_json:
            return response

        data = response.json()
        if isinstance(data, dict) and data.get("ok") is False:
            raise SmokeFailure(f"{method} {path} returned ok=false\n{data}")
        return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local smartphone-like backend smoke")
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{DEFAULT_HTTP_PORT}")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--smtp-port", type=int, default=DEFAULT_SMTP_PORT)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--no-start-deps", action="store_true")
    parser.add_argument("--no-start-backend", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--fake-smtp", action="store_true")
    parser.add_argument("--smtp-host", default="127.0.0.1")
    parser.add_argument("--smtp-sink")
    parser.add_argument("--fake-s3", action="store_true")
    parser.add_argument("--s3-host", default="127.0.0.1")
    parser.add_argument("--s3-port", type=int, default=9000)
    parser.add_argument("--s3-root")
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def find_python_tool(name: str) -> str:
    candidates = [
        REPO_ROOT / "venv" / "bin" / name,
        REPO_ROOT / ".venv" / "bin" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise SmokeFailure(f"Required tool not found: {name}")


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(shlex.quote(part) for part in command)}")
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SmokeFailure(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def wait_for_tcp(host: str, port: int, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.closing(
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(1.0)
    raise SmokeFailure(f"Timed out waiting for TCP {host}:{port}")


async def wait_for_http(url: str, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.time() < deadline:
            try:
                response = await client.get(url, headers={"User-Agent": USER_AGENT})
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    raise SmokeFailure(f"Timed out waiting for HTTP {url}")


def build_backend_env(
    args: argparse.Namespace,
    *,
    postgres_port: int,
    redis_port: int,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(REPO_ROOT / args.env_file))
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "APP_ENV": "development",
            "DEBUG": "true",
            "DATABASE_URL": (
                "postgresql+psycopg://chatuser:chatpass"
                f"@127.0.0.1:{postgres_port}/chatdb"
            ),
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "RABBITMQ_URL": "memory://",
            "MINIO_ENDPOINT": f"{args.s3_host}:{args.s3_port}",
            "MINIO_SECURE": "false",
            "BACKEND_CORS_ORIGINS": "*",
            "TRUSTED_HOSTS": "localhost,127.0.0.1",
            "ALLOW_DEBUG_EMAIL_CODES": "true",
            "SMTP_HOST": args.smtp_host,
            "SMTP_PORT": str(args.smtp_port),
            "SMTP_STARTTLS": "false",
            "SMTP_USE_SSL": "false",
            "SMTP_FROM_EMAIL": "no-reply@example.test",
            "SMTP_FROM_NAME": "Secure Chat Local",
            "SMTP_TIMEOUT_SECONDS": "10",
        }
    )
    return env


def start_runtime(args: argparse.Namespace) -> RuntimeHandle | None:
    if args.no_start_backend:
        return None

    postgres_port = find_free_tcp_port()
    redis_port = find_free_tcp_port()
    backend_env = build_backend_env(
        args,
        postgres_port=postgres_port,
        redis_port=redis_port,
    )

    container_suffix = uuid4().hex[:8]
    postgres_container = f"secure-chat-smoke-postgres-{container_suffix}"
    redis_container = f"secure-chat-smoke-redis-{container_suffix}"

    if not args.no_start_deps:
        run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                postgres_container,
                "-e",
                "POSTGRES_DB=chatdb",
                "-e",
                "POSTGRES_USER=chatuser",
                "-e",
                "POSTGRES_PASSWORD=chatpass",
                "-p",
                f"127.0.0.1:{postgres_port}:5432",
                "postgres:16",
            ],
        )
        run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                redis_container,
                "-p",
                f"127.0.0.1:{redis_port}:6379",
                "redis:7-alpine",
                "redis-server",
                "--appendonly",
                "yes",
            ],
        )
        wait_for_postgres(postgres_port)
        wait_for_redis(redis_port)

    run_command([find_python_tool("alembic"), "upgrade", "head"], env=backend_env)

    log_dir = Path(tempfile.mkdtemp(prefix="secure-chat-smoke-"))
    backend_log = log_dir / "backend.log"
    smtp_log = log_dir / "smtp.log"
    smtp_sink = log_dir / "smtp-messages.log"
    s3_log = log_dir / "s3.log"
    s3_root = log_dir / "fake-s3"

    smtp = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fake-smtp",
            "--smtp-host",
            args.smtp_host,
            "--smtp-port",
            str(args.smtp_port),
            "--smtp-sink",
            str(smtp_sink),
        ],
        cwd=REPO_ROOT,
        stdout=smtp_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )

    wait_for_tcp(args.smtp_host, args.smtp_port, timeout=15.0)

    s3 = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fake-s3",
            "--s3-host",
            args.s3_host,
            "--s3-port",
            str(args.s3_port),
            "--s3-root",
            str(s3_root),
        ],
        cwd=REPO_ROOT,
        stdout=s3_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )

    wait_for_tcp(args.s3_host, args.s3_port, timeout=15.0)
    ensure_fake_s3_buckets(
        host=args.s3_host,
        port=args.s3_port,
        bucket_names=[
            backend_env["MINIO_BUCKET_ASSETS"],
            backend_env["MINIO_BUCKET_ATTACHMENTS"],
            backend_env["MINIO_BUCKET_TEMP"],
        ],
    )

    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.http_port),
            "--proxy-headers",
        ],
        cwd=REPO_ROOT,
        env=backend_env,
        stdout=backend_log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )

    return RuntimeHandle(
        backend=backend,
        smtp=smtp,
        s3=s3,
        postgres_container=postgres_container,
        redis_container=redis_container,
        postgres_port=postgres_port,
        redis_port=redis_port,
        backend_log=backend_log,
        smtp_log=smtp_log,
        smtp_sink=smtp_sink,
        s3_log=s3_log,
    )


def stop_runtime(handle: RuntimeHandle | None) -> None:
    if handle is None:
        return
    for process in (handle.backend, handle.smtp, handle.s3):
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    for container_name in (handle.redis_container, handle.postgres_container):
        if container_name:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def dump_log_tail(path: Path, *, lines: int = 80) -> str:
    if not path.exists():
        return f"{path}: missing"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = "\n".join(content[-lines:])
    return f"== {path} ==\n{tail}"


def ensure_fake_s3_buckets(
    *,
    host: str,
    port: int,
    bucket_names: list[str],
) -> None:
    with httpx.Client(timeout=10.0) as client:
        for bucket_name in bucket_names:
            response = client.put(f"http://{host}:{port}/{bucket_name}")
            if response.status_code != 200:
                raise SmokeFailure(
                    f"Failed to create fake S3 bucket {bucket_name}: "
                    f"{response.status_code}"
                )


def find_free_tcp_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_postgres(port: int, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    dsn = f"postgresql://chatuser:chatpass@127.0.0.1:{port}/chatdb"
    while time.time() < deadline:
        try:
            with pg_connect(dsn):
                return
        except Exception:
            time.sleep(1.0)
    raise SmokeFailure(f"Timed out waiting for Postgres on 127.0.0.1:{port}")


def wait_for_redis(port: int, *, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    client = Redis(host="127.0.0.1", port=port, db=0)
    try:
        while time.time() < deadline:
            try:
                if client.ping():
                    return
            except Exception:
                time.sleep(1.0)
        raise SmokeFailure(f"Timed out waiting for Redis on 127.0.0.1:{port}")
    finally:
        client.close()


def new_device_uuid() -> str:
    return str(uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_prekeys(
    prefix: str, count: int = 5, *, start: int = 1
) -> list[dict[str, Any]]:
    return [
        {
            "prekey_id": start + offset,
            "public_prekey": f"{prefix}-prekey-{start + offset}",
        }
        for offset in range(count)
    ]


def build_bootstrap_payload(
    device_uuid: str, *, registration_id: int
) -> dict[str, Any]:
    return {
        "device_uuid": device_uuid,
        "device_name": "Pixel Smoke",
        "platform": "android",
        "app_version": "1.0.0-smoke",
        "fcm_token": f"fcm-{device_uuid}",
        "registration_id": registration_id,
        "public_identity_key": f"identity-{device_uuid}",
        "public_signing_key": f"signing-{device_uuid}",
        "signed_prekey_id": 1,
        "signed_prekey": f"signed-{device_uuid}",
        "signed_prekey_signature": f"signature-{device_uuid}",
        "one_time_prekeys": build_prekeys(device_uuid),
    }


async def register_bootstrap_and_login(
    *,
    base_url: str,
    nickname: str,
    password: str,
    email_address: str | None = None,
    email_2fa_enabled: bool = False,
) -> AuthState:
    device_uuid = new_device_uuid()
    anonymous = ApiClient(base_url=base_url)
    try:
        register_data = (
            await anonymous.request(
                "POST",
                "/api/v1/auth/register",
                auth=False,
                json_body={
                    "nickname": nickname,
                    "password": password,
                    "email": email_address,
                    "email_2fa_enabled": email_2fa_enabled,
                },
            )
        )["data"]
        bootstrap_token = register_data["bootstrap_token"]
        user_id = register_data["user_id"]

        anonymous.token = bootstrap_token
        anonymous.device_uuid = device_uuid
        await anonymous.request(
            "POST",
            "/api/v1/auth/bootstrap",
            json_body=build_bootstrap_payload(
                device_uuid,
                registration_id=int(time.time()) % 100000 + user_id,
            ),
            device=True,
        )

        login_data = (
            await anonymous.request(
                "POST",
                "/api/v1/auth/login",
                auth=False,
                json_body={
                    "nickname": nickname,
                    "password": password,
                    "device_uuid": device_uuid,
                },
            )
        )["data"]

        if email_2fa_enabled:
            login_data = (
                await anonymous.request(
                    "POST",
                    "/api/v1/auth/login/verify-email-code",
                    auth=False,
                    json_body={
                        "login_challenge_id": login_data["login_challenge_id"],
                        "code": login_data["debug_code"],
                        "device_uuid": device_uuid,
                    },
                )
            )["data"]

        refresh_token = login_data["refresh_token"]
        refresh_data = (
            await anonymous.request(
                "POST",
                "/api/v1/auth/refresh",
                auth=False,
                json_body={"refresh_token": refresh_token},
            )
        )["data"]

        return AuthState(
            nickname=nickname,
            password=password,
            email=email_address,
            user_id=user_id,
            device_uuid=device_uuid,
            access_token=refresh_data["access_token"],
            refresh_token=refresh_data["refresh_token"],
        )
    finally:
        await anonymous.close()


async def verify_presigned_download(url: str, expected_bytes: bytes) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
        if response.status_code != 200:
            raise SmokeFailure(
                f"Presigned download returned {response.status_code} for {url}"
            )
        if response.content != expected_bytes:
            raise SmokeFailure(
                "Downloaded attachment bytes do not match uploaded bytes"
            )


async def upload_presigned(url: str, payload: bytes, *, content_type: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            url,
            content=payload,
            headers={"Content-Type": content_type, "User-Agent": USER_AGENT},
        )
        if response.status_code not in {200, 201}:
            raise SmokeFailure(
                f"Presigned upload returned {response.status_code}\n{response.text}"
            )


async def expect_ws_event(
    websocket: websockets.ClientConnection,
    expected_type: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        if isinstance(message, bytes):
            raise SmokeFailure("Unexpected binary websocket frame")
        payload = cast(dict[str, Any], json.loads(message))
        if payload.get("type") == expected_type:
            return payload
    raise SmokeFailure(f"Timed out waiting for websocket event type={expected_type}")


def parse_smtp_messages(path: Path) -> list[email.message.EmailMessage]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    chunks = [chunk.strip() for chunk in raw.split("--- message ") if chunk.strip()]
    messages: list[email.message.EmailMessage] = []
    for chunk in chunks:
        _, _, payload = chunk.partition("---\n")
        if not payload:
            continue
        parsed = email.message_from_string(payload)
        messages.append(cast(email.message.EmailMessage, parsed))
    return messages


async def run_smoke(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")

    health = ApiClient(base_url=base_url)
    try:
        live_response = await health.request("GET", "/health/live", auth=False)
        ready_response = await health.request("GET", "/health/ready", auth=False)
        assert live_response["ok"] is True
        assert ready_response["ok"] is True
    finally:
        await health.close()

    suffix = uuid4().hex[:8]
    users = {
        "alice": await register_bootstrap_and_login(
            base_url=base_url,
            nickname=f"smokealice{suffix}",
            password="SmokePass123!",
        ),
        "bob": await register_bootstrap_and_login(
            base_url=base_url,
            nickname=f"smokebob{suffix}",
            password="SmokePass123!",
        ),
        "google": await register_bootstrap_and_login(
            base_url=base_url,
            nickname=f"smokegoogle{suffix}",
            password="SmokePass123!",
        ),
        "email": await register_bootstrap_and_login(
            base_url=base_url,
            nickname=f"smokeemail{suffix}",
            password="SmokePass123!",
            email_address=f"smoke-{suffix}@example.com",
            email_2fa_enabled=True,
        ),
    }

    alice = ApiClient(
        base_url=base_url,
        token=users["alice"].access_token,
        device_uuid=users["alice"].device_uuid,
    )
    bob = ApiClient(
        base_url=base_url,
        token=users["bob"].access_token,
        device_uuid=users["bob"].device_uuid,
    )
    google_user = ApiClient(
        base_url=base_url,
        token=users["google"].access_token,
        device_uuid=users["google"].device_uuid,
    )
    email_user = ApiClient(
        base_url=base_url,
        token=users["email"].access_token,
        device_uuid=users["email"].device_uuid,
    )

    try:
        me = (await alice.request("GET", "/api/v1/users/me"))["data"]
        if me["nickname"] != users["alice"].nickname:
            raise SmokeFailure("Unexpected /users/me nickname")

        updated_profile = (
            await alice.request(
                "PATCH",
                "/api/v1/users/me",
                json_body={
                    "full_name": "Smoke Alice",
                    "bio": "local smoke profile",
                    "language_code": "ru",
                    "theme": "dark",
                    "push_notifications_enabled": True,
                    "apk_update_notifications_enabled": True,
                },
            )
        )["data"]
        if updated_profile["full_name"] != "Smoke Alice":
            raise SmokeFailure("Profile patch did not persist full_name")

        avatar_profile = (
            await alice.request(
                "POST",
                "/api/v1/users/me/avatar",
                files={"file": ("avatar.png", TINY_PNG, "image/png")},
            )
        )["data"]
        avatar_url = avatar_profile["avatar_url"]
        if not avatar_url:
            raise SmokeFailure("Avatar upload did not return avatar_url")
        await verify_presigned_download(avatar_url, TINY_PNG)

        deleted_avatar_profile = (
            await alice.request("DELETE", "/api/v1/users/me/avatar")
        )["data"]
        if deleted_avatar_profile["avatar_url"] is not None:
            raise SmokeFailure("Avatar delete did not clear avatar_url")

        search = (
            await alice.request(
                "GET",
                "/api/v1/users/search",
                params={"q": users["bob"].nickname[:8], "limit": 10},
            )
        )["data"]
        if not any(item["user_id"] == users["bob"].user_id for item in search["items"]):
            raise SmokeFailure("User search did not return the peer user")

        safety = (
            await alice.request(
                "GET",
                f"/api/v1/users/{users['bob'].user_id}/safety",
            )
        )["data"]
        if not safety["supports_encrypted_chat"]:
            raise SmokeFailure("Peer should support encrypted chat after bootstrap")

        public_profile = (
            await alice.request(
                "GET",
                f"/api/v1/users/{users['bob'].user_id}/profile",
            )
        )["data"]
        if public_profile["user_id"] != users["bob"].user_id:
            raise SmokeFailure("Public profile returned the wrong user")

        await alice.request("POST", "/api/v1/devices/heartbeat", device=True)
        fcm_data = (
            await alice.request(
                "POST",
                "/api/v1/devices/fcm-token",
                device=True,
                json_body={"fcm_token": "smoke-fcm-updated"},
            )
        )["data"]
        if not fcm_data["updated"]:
            raise SmokeFailure("FCM token update was not persisted")

        bundle = (
            await alice.request(
                "GET",
                f"/api/v1/keys/bundle/{users['bob'].user_id}",
                device=True,
            )
        )["data"]
        if bundle["user_id"] != users["bob"].user_id:
            raise SmokeFailure("Key bundle returned the wrong target user")

        refill = (
            await alice.request(
                "POST",
                "/api/v1/keys/prekeys/refill",
                device=True,
                json_body={"prekeys": build_prekeys("alice-refill", 3, start=100)},
            )
        )["data"]
        if refill["added"] != 3:
            raise SmokeFailure("Prekey refill count mismatch")

        rotate = (
            await alice.request(
                "POST",
                "/api/v1/keys/signed-prekey/rotate",
                device=True,
                json_body={
                    "signed_prekey_id": 2,
                    "signed_prekey": "alice-rotated-signed-prekey",
                    "signed_prekey_signature": "alice-rotated-signature",
                },
            )
        )["data"]
        if not rotate["rotated"]:
            raise SmokeFailure("Signed prekey rotation failed")

        conversation = (
            await alice.request(
                "POST",
                "/api/v1/conversations",
                json_body={
                    "recipient_user_id": users["bob"].user_id,
                    "title": "Smoke Chat",
                    "message_ttl_days": 30,
                },
            )
        )["data"]
        conversation_id = conversation["conversation_id"]

        conversations = (await alice.request("GET", "/api/v1/conversations"))["data"]
        if not any(
            item["conversation_id"] == conversation_id
            for item in conversations["items"]
        ):
            raise SmokeFailure(
                "Conversation list does not include created conversation"
            )

        conversation_detail = (
            await alice.request(
                "GET",
                f"/api/v1/conversations/{conversation_id}",
            )
        )["data"]
        if conversation_detail["peer_user_id"] != users["bob"].user_id:
            raise SmokeFailure("Conversation detail returned wrong peer user")

        await alice.request(
            "PATCH",
            f"/api/v1/conversations/{conversation_id}",
            json_body={
                "title": "Smoke Chat Updated",
                "message_ttl_days": 20,
                "delete_after_read_seconds": 90,
            },
        )
        await bob.request("GET", f"/api/v1/conversations/{conversation_id}")

        ws_url = (
            f"ws://127.0.0.1:{args.http_port}/api/v1/ws"
            f"?token={users['bob'].access_token}"
        )
        async with websockets.connect(
            ws_url,
            additional_headers={
                "X-Device-UUID": users["bob"].device_uuid,
                "User-Agent": USER_AGENT,
            },
        ) as websocket:
            await websocket.send('{"type":"whoami"}')
            whoami = await expect_ws_event(websocket, "whoami")
            if whoami["user_id"] != users["bob"].user_id:
                raise SmokeFailure("Websocket whoami returned the wrong user")

            await websocket.send('{"type":"ping"}')
            await expect_ws_event(websocket, "pong")

            await websocket.send(
                (
                    '{"type":"subscribe_conversation",'
                    f'"conversation_id":{conversation_id}}}'
                )
            )
            subscribed = await expect_ws_event(websocket, "subscribed")
            if subscribed["conversation_id"] != conversation_id:
                raise SmokeFailure("Conversation subscription ack mismatch")

            text_message = (
                await alice.request(
                    "POST",
                    "/api/v1/messages/send",
                    device=True,
                    json_body={
                        "conversation_id": conversation_id,
                        "recipient_user_id": users["bob"].user_id,
                        "message_uuid": str(uuid4()),
                        "message_type": "text",
                        "ciphertext": "ciphertext:hello-smoke",
                        "ciphertext_version": 1,
                        "encryption_mode": "signal",
                        "nonce": "nonce-1",
                        "aad_hash": hashlib.sha256(b"aad-1").hexdigest(),
                        "client_created_at": now_iso(),
                    },
                )
            )["data"]
            text_message_id = text_message["message_id"]

            ws_message_created = await expect_ws_event(websocket, "conversation.event")
            event_payload = ws_message_created.get("event", {})
            if event_payload.get("event_type") != "message_created":
                raise SmokeFailure(
                    "Realtime websocket payload did not contain message_created event"
                )
            if ws_message_created["conversation_id"] != conversation_id:
                raise SmokeFailure("Realtime message event returned wrong conversation")

        await alice.request(
            "PATCH",
            f"/api/v1/conversations/{conversation_id}/settings",
            json_body={
                "shared_secret_enabled": True,
                "shared_secret_fingerprint": "abcd1234efgh5678",
            },
        )

        upload_session = (
            await alice.request(
                "POST",
                "/api/v1/files/upload-sessions",
                json_body={
                    "conversation_id": conversation_id,
                    "files_expected_count": 1,
                },
            )
        )["data"]
        upload_session_id = upload_session["session_id"]

        attachment_init = (
            await alice.request(
                "POST",
                f"/api/v1/files/upload-sessions/{upload_session_id}/attachments/init",
                json_body={
                    "items": [
                        {
                            "encrypted_file_name": "cipher.bin",
                            "file_size": 20,
                            "mime_hint": "application/octet-stream",
                            "sha256_encrypted_blob": hashlib.sha256(
                                b"encrypted-blob-smoke"
                            ).hexdigest(),
                            "encrypted_metadata": {"caption": "smoke attachment"},
                        }
                    ]
                },
            )
        )["data"]
        attachment_item = attachment_init["items"][0]
        attachment_bytes = b"encrypted-blob-smoke"
        await upload_presigned(
            attachment_item["upload_url"],
            attachment_bytes,
            content_type="application/octet-stream",
        )
        await alice.request(
            "POST",
            f"/api/v1/files/upload-sessions/{upload_session_id}/complete",
            json_body={"attachment_ids": [attachment_item["attachment_id"]]},
        )

        attachment_message = (
            await alice.request(
                "POST",
                "/api/v1/messages/send",
                device=True,
                json_body={
                    "conversation_id": conversation_id,
                    "recipient_user_id": users["bob"].user_id,
                    "message_uuid": str(uuid4()),
                    "reply_to_message_id": text_message_id,
                    "message_type": "file",
                    "ciphertext": "ciphertext:file-smoke",
                    "ciphertext_version": 1,
                    "encryption_mode": "signal_plus_shared_secret",
                    "nonce": "nonce-2",
                    "aad_hash": hashlib.sha256(b"aad-2").hexdigest(),
                    "client_created_at": now_iso(),
                    "attachment_ids": [attachment_item["attachment_id"]],
                },
            )
        )["data"]
        attachment_message_id = attachment_message["message_id"]

        await bob.request(
            "POST",
            f"/api/v1/messages/{attachment_message_id}/delivered",
            device=True,
            json_body={"delivered_at": now_iso()},
        )
        await bob.request(
            "POST",
            f"/api/v1/messages/{attachment_message_id}/read",
            device=True,
            json_body={"read_at": now_iso()},
        )
        await bob.request(
            "POST",
            f"/api/v1/messages/{attachment_message_id}/reaction",
            device=True,
            json_body={"reaction": "fire"},
        )
        await bob.request(
            "DELETE",
            f"/api/v1/messages/{attachment_message_id}/reaction",
            device=True,
        )

        history_a = (
            await alice.request(
                "GET",
                f"/api/v1/messages/conversations/{conversation_id}",
            )
        )["data"]
        history_b = (
            await alice.request(
                "GET",
                f"/api/v1/conversations/{conversation_id}/messages",
            )
        )["data"]
        if len(history_a["items"]) != len(history_b["items"]):
            raise SmokeFailure("Message list endpoints returned different item counts")

        await alice.request(
            "POST",
            (
                f"/api/v1/messages/conversations/{conversation_id}"
                f"/pin/{attachment_message_id}"
            ),
            device=True,
        )
        await alice.request(
            "DELETE",
            f"/api/v1/messages/conversations/{conversation_id}/pin",
            device=True,
        )

        search_messages = (
            await alice.request(
                "GET",
                f"/api/v1/messages/conversations/{conversation_id}/search",
                params={"q": "ciphertext", "limit": 20},
            )
        )["data"]
        if not search_messages["items"]:
            raise SmokeFailure("Message search returned no results")

        shared_files = (
            await alice.request(
                "GET",
                f"/api/v1/messages/conversations/{conversation_id}/shared",
                params={"tab": "files", "limit": 20},
            )
        )["data"]
        if shared_files["counts"]["files"] < 1:
            raise SmokeFailure("Shared files tab did not count uploaded attachment")

        message_attachments = (
            await alice.request(
                "GET",
                f"/api/v1/files/messages/{attachment_message_id}/attachments",
            )
        )["data"]
        attachment_id = message_attachments["items"][0]["attachment_id"]

        attachment_meta = (
            await alice.request(
                "GET",
                f"/api/v1/files/attachments/{attachment_id}",
            )
        )["data"]
        if not attachment_meta["download_url"]:
            raise SmokeFailure("Attachment metadata did not include download_url")
        await verify_presigned_download(
            attachment_meta["download_url"],
            attachment_bytes,
        )

        google_conv = (
            await alice.request(
                "POST",
                "/api/v1/conversations",
                json_body={
                    "recipient_user_id": users["google"].user_id,
                    "title": "Forward Target",
                    "message_ttl_days": 15,
                },
            )
        )["data"]
        google_conversation_id = google_conv["conversation_id"]

        forwarded = (
            await alice.request(
                "POST",
                "/api/v1/messages/forward",
                device=True,
                json_body={
                    "conversation_id": google_conversation_id,
                    "recipient_user_id": users["google"].user_id,
                    "message_ids": [text_message_id],
                    "client_created_at": now_iso(),
                },
            )
        )["data"]
        forwarded_message_id = forwarded["items"][0]["message_id"]

        await alice.request(
            "POST",
            "/api/v1/messages/delete-local",
            json_body={
                "conversation_id": google_conversation_id,
                "message_ids": [forwarded_message_id],
            },
        )
        await alice.request(
            "POST",
            "/api/v1/messages/delete-global",
            json_body={
                "conversation_id": google_conversation_id,
                "message_ids": [forwarded_message_id],
            },
        )

        events = (
            await alice.request(
                "GET",
                f"/api/v1/sync/conversations/{conversation_id}/events",
                params={"limit": 100},
            )
        )["data"]
        if not events["items"]:
            raise SmokeFailure("Sync events returned no conversation activity")

        await bob.request(
            "POST", f"/api/v1/conversations/{conversation_id}/clear-local"
        )
        await alice.request(
            "POST",
            f"/api/v1/conversations/{google_conversation_id}/clear-global",
            json_body={"reason": "smoke cleanup"},
        )

        apk_upload = (
            await alice.request(
                "POST",
                "/api/v1/files/apk/upload",
                auth=False,
                files={
                    "version_name": (None, "1.0.99-smoke"),
                    "version_code": (None, "1099"),
                    "changelog": (None, "smoke upload"),
                    "token": (None, "change-me-apk-upload-token"),
                    "file": (
                        "secure-chat-smoke.apk",
                        b"PK\x03\x04smoke-apk",
                        "application/vnd.android.package-archive",
                    ),
                },
            )
        )["data"]
        if apk_upload["version_code"] != 1099:
            raise SmokeFailure("APK upload returned unexpected version code")

        latest_apk = (
            await alice.request(
                "GET",
                "/api/v1/files/apk/latest",
                auth=False,
            )
        )["data"]
        if latest_apk["version_code"] != 1099:
            raise SmokeFailure("Latest APK endpoint returned stale release")
        await verify_presigned_download(
            latest_apk["download_url"], b"PK\x03\x04smoke-apk"
        )

        apk_check = (
            await alice.request(
                "GET",
                "/api/v1/files/apk/check",
                auth=False,
                params={"version_code": 1000},
            )
        )["data"]
        if not apk_check["update_available"]:
            raise SmokeFailure("APK version check did not report an available update")

        google_setup = (
            await google_user.request("POST", "/api/v1/auth/2fa/google/setup")
        )["data"]
        await google_user.request(
            "GET",
            "/api/v1/auth/2fa/google/qr",
            expect_json=False,
        )
        google_code = _generate_totp_code(
            secret=google_setup["secret"],
            counter=int(time.time()) // 30,
        )
        google_status = (
            await google_user.request(
                "POST",
                "/api/v1/auth/2fa/google/confirm",
                json_body={"code": google_code},
            )
        )["data"]
        if not google_status["enabled"]:
            raise SmokeFailure("Google 2FA did not become enabled")

        await google_user.request("POST", "/api/v1/auth/logout")
        anonymous = ApiClient(base_url=base_url)
        try:
            requires_totp = (
                await anonymous.request(
                    "POST",
                    "/api/v1/auth/login",
                    auth=False,
                    json_body={
                        "nickname": users["google"].nickname,
                        "password": users["google"].password,
                        "device_uuid": users["google"].device_uuid,
                    },
                )
            )["data"]
            if not requires_totp["requires_totp"]:
                raise SmokeFailure("Google 2FA login did not request a TOTP code")

            google_access = (
                await anonymous.request(
                    "POST",
                    "/api/v1/auth/login",
                    auth=False,
                    json_body={
                        "nickname": users["google"].nickname,
                        "password": users["google"].password,
                        "device_uuid": users["google"].device_uuid,
                        "totp_code": _generate_totp_code(
                            secret=google_setup["secret"],
                            counter=int(time.time()) // 30,
                        ),
                    },
                )
            )["data"]
        finally:
            await anonymous.close()

        google_user.token = google_access["access_token"]
        google_user.device_uuid = users["google"].device_uuid
        await google_user.request("DELETE", "/api/v1/auth/2fa/google")
        await google_user.request("POST", "/api/v1/auth/logout-all")

        await email_user.request("POST", "/api/v1/auth/logout")
        await bob.request("DELETE", "/api/v1/devices/current", device=True)
        await alice.request("POST", "/api/v1/auth/logout")
    finally:
        await alice.close()
        await bob.close()
        await google_user.close()
        await email_user.close()


async def async_main(args: argparse.Namespace) -> int:
    if args.fake_smtp:
        sink = Path(
            args.smtp_sink or tempfile.mkstemp(prefix="smtp-sink-", suffix=".log")[1]
        )
        server = FakeSmtpServer(args.smtp_host, args.smtp_port, sink)
        await server.run()
        return 0
    if args.fake_s3:
        root_dir = Path(args.s3_root or tempfile.mkdtemp(prefix="fake-s3-", dir="/tmp"))
        root_dir.mkdir(parents=True, exist_ok=True)
        s3_server = FakeS3Server(args.s3_host, args.s3_port, root_dir)
        try:
            s3_server.serve_forever()
        finally:
            s3_server.server_close()
        return 0

    runtime = start_runtime(args)
    try:
        if runtime is not None:
            await wait_for_http(
                f"{args.base_url.rstrip('/')}/health/live", timeout=90.0
            )
            await wait_for_http(
                f"{args.base_url.rstrip('/')}/health/ready", timeout=90.0
            )

        await run_smoke(args)

        if runtime is not None and runtime.backend.poll() not in {None, 0}:
            raise SmokeFailure("Backend process exited unexpectedly during smoke run")
        if runtime is not None:
            smtp_messages = parse_smtp_messages(runtime.smtp_sink)
            if not smtp_messages:
                raise SmokeFailure("SMTP sink is empty after email 2FA smoke flow")

        print("Smoke scenario completed successfully.")
        if runtime is not None:
            print(f"Backend log: {runtime.backend_log}")
            print(f"SMTP log: {runtime.smtp_log}")
        return 0
    except Exception as exc:
        if runtime is not None:
            print(dump_log_tail(runtime.backend_log), file=sys.stderr)
            print(dump_log_tail(runtime.smtp_log), file=sys.stderr)
            print(dump_log_tail(runtime.s3_log), file=sys.stderr)
        print(f"Smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if runtime is not None and not args.keep_running:
            stop_runtime(runtime)


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
