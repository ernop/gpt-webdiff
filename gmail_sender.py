"""HTTPS email delivery through the Gmail API (gmail.send scope only).

DigitalOcean blocks outbound SMTP ports (25, 465, 587) on tpbeta by default.
This module sends alert emails exclusively over HTTPS port 443 via the Gmail
REST API, using a narrow gmail.send OAuth refresh token that cannot read,
modify, or delete mail.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import tempfile
import time
import urllib.parse
from email.mime.text import MIMEText

import requests

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

# Less than a fifth of Gmail's 500/day personal sending limit.
MAX_EMAILS_PER_24H = 100
BUDGET_WINDOW_SECONDS = 24 * 60 * 60
SEND_LOG_FILE = "email_send_log.json"
TIMEOUT = (10, 30)
USER_AGENT = "http-client/1.0"

_token_cache: dict[str, object] = {
    "refresh_token": None,
    "access_token": None,
    "expires_at": 0.0,
}


class GmailDeliveryError(RuntimeError):
    pass


def reset_token_cache() -> None:
    _token_cache["refresh_token"] = None
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0.0


def _error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300].strip()
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or ""
            status = err.get("status") or ""
            return f"{status}: {msg}".strip(": ")
        desc = payload.get("error_description") or ""
        if err and desc:
            return f"{err}: {desc}"
        if err:
            return str(err)
    return str(payload)[:300]


def _load_send_log(path: str = SEND_LOG_FILE) -> dict:
    if not os.path.exists(path):
        return {"sent_timestamps": [], "auth_failed_at": None, "auth_error": None}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise GmailDeliveryError(f"{path} is corrupted (expected JSON object)")
    return {
        "sent_timestamps": [float(ts) for ts in data.get("sent_timestamps", [])],
        "auth_failed_at": data.get("auth_failed_at"),
        "auth_error": data.get("auth_error"),
    }


def _save_send_log(state: dict, path: str = SEND_LOG_FILE) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _check_auth_circuit_breaker(config_path: str, state: dict) -> None:
    failed_at = state.get("auth_failed_at")
    if failed_at is None:
        return
    if os.path.exists(config_path) and os.path.getmtime(config_path) > float(failed_at):
        state["auth_failed_at"] = None
        state["auth_error"] = None
        return
    detail = state.get("auth_error") or "OAuth token rejected"
    raise GmailDeliveryError(
        f"Gmail OAuth token was rejected ({detail}); re-authorize with "
        "`python3 gptcron.py auth-gmail` and update config.json before retrying"
    )


def _require_gmail_credentials(config: dict) -> tuple[str, str, str]:
    required = ("gmail_client_id", "gmail_client_secret", "gmail_refresh_token")
    missing = [key for key in required if not str(config.get(key) or "").strip()]
    if missing:
        raise GmailDeliveryError(
            "Missing Gmail API credentials in config.json: "
            f"{', '.join(missing)}. Run `python3 gptcron.py auth-gmail` to authorize gmail.send."
        )
    return (
        str(config["gmail_client_id"]).strip(),
        str(config["gmail_client_secret"]).strip(),
        str(config["gmail_refresh_token"]).strip(),
    )


def _get_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    state: dict,
    send_log_path: str,
    now: float,
) -> str:
    if (
        _token_cache["refresh_token"] == refresh_token
        and _token_cache["access_token"]
        and now < float(_token_cache["expires_at"]) - 60.0
    ):
        return str(_token_cache["access_token"])

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GmailDeliveryError(f"Gmail OAuth token request failed: {exc}") from exc

    if response.status_code != 200:
        detail = _error_detail(response)
        if response.status_code in (400, 401) and "invalid_grant" in detail.lower():
            state["auth_failed_at"] = now
            state["auth_error"] = detail
            _save_send_log(state, send_log_path)
            reset_token_cache()
        raise GmailDeliveryError(
            f"Gmail OAuth token refresh failed (HTTP {response.status_code}): {detail}"
        )

    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise GmailDeliveryError("Gmail OAuth token response omitted access_token")
    expires_in = float(payload.get("expires_in", 3600))
    _token_cache["refresh_token"] = refresh_token
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return str(token)


def send_html_email(
    config: dict,
    subject: str,
    html_body: str,
    to_email: str,
    *,
    config_path: str = "config.json",
    send_log_path: str = SEND_LOG_FILE,
    now: float | None = None,
) -> dict:
    current_time = time.time() if now is None else float(now)
    client_id, client_secret, refresh_token = _require_gmail_credentials(config)

    from_email = str(config.get("from_email") or "").strip()
    if not from_email:
        raise GmailDeliveryError("Missing from_email in config.json")
    if not str(to_email or "").strip():
        raise GmailDeliveryError("Missing recipient address")

    state = _load_send_log(send_log_path)
    _check_auth_circuit_breaker(config_path, state)

    cutoff = current_time - BUDGET_WINDOW_SECONDS
    recent = [ts for ts in state["sent_timestamps"] if ts > cutoff]
    if len(recent) >= MAX_EMAILS_PER_24H:
        raise GmailDeliveryError(
            f"Daily email budget reached ({len(recent)}/{MAX_EMAILS_PER_24H} in last 24h); "
            "refusing to send until budget window clears"
        )

    access_token = _get_access_token(
        client_id, client_secret, refresh_token, state, send_log_path, current_time
    )

    clean_subject = " ".join(str(subject).splitlines()).strip()
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = clean_subject
    msg["From"] = from_email
    msg["To"] = to_email
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    try:
        response = requests.post(
            SEND_URL,
            json={"raw": raw},
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GmailDeliveryError(f"Gmail API send request failed: {exc}") from exc

    if response.status_code != 200:
        detail = _error_detail(response)
        if response.status_code == 401:
            reset_token_cache()
        raise GmailDeliveryError(
            f"Gmail API send failed (HTTP {response.status_code}): {detail}"
        )

    recent.append(current_time)
    state["sent_timestamps"] = recent
    state["auth_failed_at"] = None
    state["auth_error"] = None
    _save_send_log(state, send_log_path)
    return response.json()


def authorize_gmail_send(
    config_path: str = "config.json",
    login_hint: str | None = None,
) -> dict:
    """Interactive loopback PKCE OAuth flow requesting gmail.send only."""
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    client_id = str(config.get("gmail_client_id") or "").strip()
    client_secret = str(config.get("gmail_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise GmailDeliveryError(
            "Set gmail_client_id and gmail_client_secret in config.json before running auth-gmail."
        )

    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    expected_state = secrets.token_urlsafe(24)
    captured: dict[str, str | None] = {"code": None, "state": None, "error": None}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            captured["code"] = (params.get("code") or [None])[0]
            captured["state"] = (params.get("state") or [None])[0]
            captured["error"] = (params.get("error") or [None])[0]
            body = (
                "Authorization received. You can close this tab."
                if captured["code"]
                else f"Authorization failed: {captured['error'] or 'missing code'}"
            )
            self.send_response(200 if captured["code"] else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format, *args):  # noqa: A002
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), CallbackHandler)
    try:
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}"
        query_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SEND_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": expected_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        hint = login_hint or str(config.get("from_email") or "").strip()
        if hint:
            query_params["login_hint"] = hint

        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(query_params)}"
        print("Open this URL in a browser signed into the sending Gmail account:\n")
        print(auth_url)
        print(f"\nWaiting for redirect on {redirect_uri} ...")
        server.handle_request()
    finally:
        server.server_close()

    if captured["error"]:
        raise GmailDeliveryError(f"Google OAuth returned error: {captured['error']}")
    if not captured["code"]:
        raise GmailDeliveryError("Google OAuth redirect did not contain an authorization code")
    if captured["state"] != expected_state:
        raise GmailDeliveryError("Google OAuth state mismatch")

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": captured["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise GmailDeliveryError(
            f"OAuth code exchange failed (HTTP {response.status_code}): {_error_detail(response)}"
        )

    payload = response.json()
    granted_scopes = set(str(payload.get("scope") or "").split())
    if GMAIL_SEND_SCOPE not in granted_scopes:
        raise GmailDeliveryError(
            f"Expected scope {GMAIL_SEND_SCOPE}; got: {sorted(granted_scopes)}"
        )
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise GmailDeliveryError(
            "Google did not return a refresh_token; revoke prior grant at "
            "https://myaccount.google.com/permissions and re-run auth-gmail."
        )

    config["gmail_refresh_token"] = refresh_token
    tmp_path = f"{config_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4)
        handle.write("\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, config_path)
    reset_token_cache()
    print(f"Saved gmail_refresh_token (scope gmail.send) to {config_path}")
    return config
