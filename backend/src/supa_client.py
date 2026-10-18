"""Thin Supabase HTTP client: PostgREST, RPC, Auth, Storage and the Realtime broadcast REST endpoint.

Everything comes from env, nothing is hardcoded: SUPABASE_URL, SUPABASE_SERVICE_KEY (secret key, backend only),
SUPABASE_PUBLISHABLE_KEY / SUPABASE_ANON_KEY / NEXT_PUBLIC_SUPABASE_ANON_KEY (publishable key, used with agent access
tokens), SUPABASE_PROJECT_REF (scripts). New-style keys (sb_publishable_, sb_secret_) travel only in the `apikey` header,
as the Supabase docs require; a legacy JWT key also goes in `Authorization: Bearer`. An agent's access token always goes
in `Authorization: Bearer` with the publishable key as `apikey`, so PostgREST runs the request as that agent.
"""
from __future__ import annotations

import json
import os
import re
import threading
from urllib.parse import quote

import httpx

TIMEOUT = 10.0


def _clean(name: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return ""
    value = raw.strip()
    if not value or value.startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip().strip('"').strip("'").strip()


def supabase_url() -> str:
    url = _clean("SUPABASE_URL").rstrip("/")
    return url if url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost") else ""


def service_key() -> str:
    return _clean("SUPABASE_SERVICE_KEY")


def publishable_key() -> str:
    return _clean("SUPABASE_PUBLISHABLE_KEY") or _clean("SUPABASE_ANON_KEY") or _clean("NEXT_PUBLIC_SUPABASE_ANON_KEY")


def project_ref() -> str:
    ref = _clean("SUPABASE_PROJECT_REF")
    return ref if re.fullmatch(r"[a-z]{20}", ref) else ""


def key_headers(key: str) -> dict:
    headers = {"apikey": key}
    if not key.startswith("sb_"):
        headers["Authorization"] = "Bearer " + key  # legacy JWT keys
    return headers


def token_headers(access_token: str, apikey: str) -> dict:
    return {"apikey": apikey, "Authorization": "Bearer " + access_token}


class SupabaseError(Exception):
    def __init__(self, status: int, body: dict | str, detail: str = ""):
        self.status = status
        self.body = body
        message = body.get("message") if isinstance(body, dict) else str(body)[:200]
        super().__init__(detail or f"HTTP {status}: {message}")

    @property
    def code(self) -> str | None:
        return self.body.get("code") if isinstance(self.body, dict) else None

    @property
    def message(self) -> str:
        if isinstance(self.body, dict):
            return str(self.body.get("message") or self.body.get("msg") or self.body.get("error_description") or self.body.get("error") or "")
        return str(self.body)[:300]


def _body(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


class _Borrowed:
    """`with supa.client() as client:` keeps working: the shared client is not closed at the end of the block, and the
    per-call timeout is applied to each request."""

    def __init__(self, http: httpx.Client, timeout: float):
        self.http = http
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return self.http.request(method, url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)


class Supa:
    def __init__(self, url: str | None = None, key: str | None = None, anon: str | None = None, transport=None):
        self.url = (url if url is not None else supabase_url()).rstrip("/")
        self.key = key if key is not None else service_key()
        self.anon = anon if anon is not None else publishable_key()
        self.transport = transport
        self._local = threading.local()
        self._clients: list[httpx.Client] = []
        self._clients_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)

    def client(self, timeout: float = TIMEOUT) -> "_Borrowed":
        """A kept-alive client for this thread (one TLS handshake per thread, not per request)."""
        http = getattr(self._local, "http", None)
        if http is None or http.is_closed:
            http = httpx.Client(transport=self.transport, timeout=TIMEOUT, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))
            self._local.http = http
            with self._clients_lock:
                self._clients.append(http)
        return _Borrowed(http, timeout)

    def close(self):
        with self._clients_lock:
            clients, self._clients = self._clients, []
        for http in clients:
            try:
                http.close()
            except Exception:
                pass

    def _check(self, response: httpx.Response):
        if response.status_code >= 400:
            raise SupabaseError(response.status_code, _body(response))
        return response

    def auth(self, token: str | None) -> dict:
        """Headers for a request as the service role (token None) or as an agent (its access token)."""
        if token:
            return token_headers(token, self.anon or self.key)
        return key_headers(self.key)

    # ---- PostgREST -------------------------------------------------------------------------------------------

    def upsert(self, table: str, rows: list[dict], token: str | None = None, ignore_duplicates: bool = False) -> int:
        # PostgREST bulk inserts need every object to carry the same keys; a record without an optional field mirrors as null.
        keys = list(dict.fromkeys(key for row in rows for key in row))
        if any(len(row) != len(keys) for row in rows):
            rows = [{key: row.get(key) for key in keys} for row in rows]
        prefer = ("resolution=ignore-duplicates" if ignore_duplicates else "resolution=merge-duplicates") + ",return=minimal"
        headers = {**self.auth(token), "Content-Type": "application/json", "Prefer": prefer}
        with self.client() as client:
            response = client.post(f"{self.url}/rest/v1/{table}", params={"on_conflict": "id"}, headers=headers,
                                   content=json.dumps(rows, ensure_ascii=False, default=str))
        self._check(response)
        return response.status_code

    def rpc(self, name: str, args: dict | None = None, token: str | None = None, timeout: float = TIMEOUT):
        headers = {**self.auth(token), "Content-Type": "application/json"}
        with self.client(timeout) as client:
            response = client.post(f"{self.url}/rest/v1/rpc/{name}", headers=headers, content=json.dumps(args or {}))
        self._check(response)
        return _body(response) if response.content else None

    def patch(self, table: str, match: dict, values: dict, token: str | None = None) -> int:
        params = {column: f"eq.{value}" for column, value in match.items()}
        headers = {**self.auth(token), "Content-Type": "application/json", "Prefer": "return=minimal"}
        with self.client() as client:
            response = client.patch(f"{self.url}/rest/v1/{table}", params=params, headers=headers, content=json.dumps(values))
        self._check(response)
        return response.status_code

    def select(self, table: str, params: dict, token: str | None = None, apikey_only: str | None = None):
        headers = {"apikey": apikey_only} if apikey_only else self.auth(token)
        with self.client() as client:
            response = client.get(f"{self.url}/rest/v1/{table}", params=params, headers=headers)
        self._check(response)
        return _body(response)

    # ---- Auth -----------------------------------------------------------------------------------------------

    def password_grant(self, email: str, password: str) -> dict:
        with self.client() as client:
            response = client.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"},
                                   headers={"apikey": self.anon or self.key, "Content-Type": "application/json"},
                                   content=json.dumps({"email": email, "password": password}))
        self._check(response)
        return response.json()

    def refresh_grant(self, refresh_token: str) -> dict:
        with self.client() as client:
            response = client.post(f"{self.url}/auth/v1/token", params={"grant_type": "refresh_token"},
                                   headers={"apikey": self.anon or self.key, "Content-Type": "application/json"},
                                   content=json.dumps({"refresh_token": refresh_token}))
        self._check(response)
        return response.json()

    def admin_users(self, page: int = 1, per_page: int = 100) -> list[dict]:
        with self.client() as client:
            response = client.get(f"{self.url}/auth/v1/admin/users", params={"page": page, "per_page": per_page}, headers=key_headers(self.key))
        self._check(response)
        payload = response.json()
        return payload.get("users", []) if isinstance(payload, dict) else payload

    def admin_create_user(self, email: str, password: str, app_metadata: dict | None = None) -> dict:
        body = {"email": email, "password": password, "email_confirm": True, "app_metadata": app_metadata or {}}
        with self.client() as client:
            response = client.post(f"{self.url}/auth/v1/admin/users", headers={**key_headers(self.key), "Content-Type": "application/json"},
                                   content=json.dumps(body))
        self._check(response)
        return response.json()

    def admin_update_user(self, user_id: str, password: str | None = None, app_metadata: dict | None = None) -> dict:
        body: dict = {}
        if password:
            body["password"] = password
        if app_metadata is not None:
            body["app_metadata"] = app_metadata
        with self.client() as client:
            response = client.put(f"{self.url}/auth/v1/admin/users/{user_id}", headers={**key_headers(self.key), "Content-Type": "application/json"},
                                  content=json.dumps(body))
        self._check(response)
        return response.json()

    # ---- Storage --------------------------------------------------------------------------------------------

    def upload(self, bucket: str, path: str, data: bytes, content_type: str, upsert: bool = True) -> dict:
        headers = {**key_headers(self.key), "Content-Type": content_type, "x-upsert": "true" if upsert else "false",
                   "cache-control": "max-age=3600"}
        with self.client(30) as client:
            response = client.post(f"{self.url}/storage/v1/object/{bucket}/{quote(path)}", headers=headers, content=data)
        self._check(response)
        return _body(response)

    def sign(self, bucket: str, path: str, expires_in: int = 900, transform: dict | None = None) -> str:
        body: dict = {"expiresIn": int(expires_in)}
        if transform:
            body["transform"] = transform
        with self.client() as client:
            response = client.post(f"{self.url}/storage/v1/object/sign/{bucket}/{quote(path)}",
                                   headers={**key_headers(self.key), "Content-Type": "application/json"}, content=json.dumps(body))
        self._check(response)
        payload = response.json()
        signed = payload.get("signedURL") or payload.get("signedUrl") or ""
        if not signed:
            raise SupabaseError(response.status_code, payload, "Storage returned no signed URL.")
        return signed if signed.startswith("http") else f"{self.url}/storage/v1{signed}"

    def remove(self, bucket: str, paths: list[str]) -> list:
        with self.client() as client:
            response = client.request("DELETE", f"{self.url}/storage/v1/object/{bucket}", headers={**key_headers(self.key), "Content-Type": "application/json"},
                                      content=json.dumps({"prefixes": paths}))
        self._check(response)
        return _body(response) or []

    # ---- Realtime -------------------------------------------------------------------------------------------

    def broadcast(self, messages: list[dict]) -> int:
        """POST /realtime/v1/api/broadcast with the secret key: the only sender on the private HUD channels."""
        with self.client() as client:
            response = client.post(f"{self.url}/realtime/v1/api/broadcast", headers={**key_headers(self.key), "Content-Type": "application/json"},
                                   content=json.dumps({"messages": messages}, ensure_ascii=False, default=str))
        self._check(response)
        return response.status_code
