"""
Thin HTTP client for the Jihuanshe (集换社) API, for use with YOUR OWN
account's bearer token — obtained the normal way, by logging into the app
and capturing the Authorization header from your own session (e.g. via a
local proxy on your own device).

This does NOT attempt to decrypt or forge encrypted request/response
bodies. Per jihuanshe-api-notes.md, some endpoints wrap payloads in a
proprietary encryption layer (kEncryptAPIRequest / kDecryptAPIResponse).
Where that's the case, requests here will get a response back but the
body will be ciphertext — the client just reports that rather than
attempting to crack it.

Config via environment variables:
    JHS_ENV    - "prod" | "uat" | "testing"  (default: "uat")
    JHS_TOKEN  - your own bearer token (required for authenticated calls)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

BASE_HOSTS = {
    "prod": "https://api.jihuanshe.com",
    "uat": "https://api-uat.jihuanshe.com",
    "testing": "https://api-testing.jihuanshe.com",
}


@dataclass
class ApiResponse:
    status_code: int
    headers: dict
    raw_text: str
    json_body: Optional[Any] = None
    looks_encrypted: bool = False

    @classmethod
    def from_response(cls, resp: requests.Response) -> "ApiResponse":
        json_body = None
        looks_encrypted = False
        try:
            json_body = resp.json()
        except ValueError:
            # Not valid JSON. If the body is non-empty and not JSON,
            # that's consistent with the encrypted-payload behavior
            # described in the API notes.
            looks_encrypted = bool(resp.text.strip())
        return cls(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            raw_text=resp.text,
            json_body=json_body,
            looks_encrypted=looks_encrypted,
        )


class JihuansheClient:
    def __init__(self, env: Optional[str] = None, token: Optional[str] = None, timeout: float = 10.0):
        env = env or os.environ.get("JHS_ENV", "uat")
        if env not in BASE_HOSTS:
            raise ValueError(f"Unknown JHS_ENV {env!r}, expected one of {list(BASE_HOSTS)}")
        self.base_url = BASE_HOSTS[env]
        self.token = token or os.environ.get("JHS_TOKEN")
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get(self, path: str, params: Optional[dict] = None) -> ApiResponse:
        resp = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return ApiResponse.from_response(resp)

    def post(self, path: str, json_body: Optional[dict] = None) -> ApiResponse:
        resp = self.session.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=json_body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return ApiResponse.from_response(resp)

    def login(self, identifier: str, password: str) -> ApiResponse:
        """
        Attempt the normal login flow with YOUR OWN credentials against
        api/market/auth. This sends the request as plain JSON — if the
        API's encryption layer covers this endpoint, expect a non-200
        or an opaque/undecodable body (check resp.looks_encrypted)
        rather than a usable token. That result is itself useful
        information, not a failure of this client.

        On a plaintext 200 response containing a recognizable token
        field, self.token is set automatically so subsequent calls on
        this client are authenticated.
        """
        resp = self.post("api/market/auth/login", json_body={"account": identifier, "password": password})
        if resp.status_code == 200 and isinstance(resp.json_body, dict):
            token = _extract_token(resp.json_body)
            if token:
                self.token = token
        return resp


def _extract_token(body: dict) -> Optional[str]:
    for key in ("token", "access_token"):
        if isinstance(body.get(key), str):
            return body[key]
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("token", "access_token"):
            if isinstance(data.get(key), str):
                return data[key]
    return None
