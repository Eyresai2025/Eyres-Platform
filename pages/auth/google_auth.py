"""Google OAuth 2.0 authentication for the PyQt5 desktop platform.

Uses the system browser and a loopback (127.0.0.1) callback, which is the
recommended pattern for Windows desktop OAuth clients. No Google password is
collected or stored by the application.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Optional

import requests

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleAuthError(RuntimeError):
    pass


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class GoogleIdentity:
    provider_user_id: str
    email: str
    name: str
    given_name: str = ""
    family_name: str = ""
    picture: str = ""
    verified_email: bool = False


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server_version = "EYRESOAuth/1.0"

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.oauth_result = {k: v[0] for k, v in params.items()}
        body = """<!doctype html><html><head><meta charset='utf-8'><title>EYRES Sign In</title>
        <style>body{font-family:Segoe UI,Arial;text-align:center;padding:60px;background:#fff;color:#172033}h2{margin-bottom:12px}p{color:#5f6b7a}</style>
        </head><body>
        <h2>EYRES AI Platform</h2>
        <p>Authentication completed successfully.</p>
        <p>This window will close automatically.</p>
        <script>
        (function(){
          try { window.close(); } catch(e) {}
          setTimeout(function(){
            try { window.open('', '_self'); window.close(); } catch(e) {}
          }, 150);
        })();
        </script>
        </body></html>"""
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return


class _CallbackServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler):
        super().__init__(server_address, handler)
        self.oauth_result = None


def _free_loopback_server():
    # Bind port 0 so Windows assigns an available local port.
    return _CallbackServer(("127.0.0.1", 0), _CallbackHandler)


def authenticate_google(timeout_seconds: int = 180) -> GoogleIdentity:
    client_id = os.getenv("EYRES_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("EYRES_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id:
        raise GoogleAuthError(
            "Google Sign-In is not configured. Set EYRES_GOOGLE_CLIENT_ID in the .env file."
        )

    server = _free_loopback_server()
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"
    state = secrets.token_urlsafe(32)
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    auth_url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Ask the default browser for a new window when possible. This keeps
        # the OAuth callback separate from the user's normal browsing window.
        # The callback page still contains window.close(); the desktop app does
        # not depend on the browser being willing to close script-created tabs.
        if not webbrowser.open(auth_url, new=1, autoraise=True):
            raise GoogleAuthError("Could not open the default browser for Google Sign-In.")

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and server.oauth_result is None:
            time.sleep(0.1)

        result = server.oauth_result
        if not result:
            raise GoogleAuthError("Google Sign-In timed out. Please try again.")
        if result.get("error"):
            description = result.get("error_description") or result.get("error")
            raise GoogleAuthError(f"Google Sign-In was not completed: {description}")
        if not secrets.compare_digest(result.get("state", ""), state):
            raise GoogleAuthError("Invalid OAuth state received. Please try again.")

        code = result.get("code")
        if not code:
            raise GoogleAuthError("Google did not return an authorization code.")

        token_data = {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
        if client_secret:
            token_data["client_secret"] = client_secret

        response = requests.post(TOKEN_ENDPOINT, data=token_data, timeout=20)
        if response.status_code != 200:
            try:
                detail = response.json().get("error_description") or response.json().get("error")
            except Exception:
                detail = response.text[:300]
            raise GoogleAuthError(f"Google token exchange failed: {detail}")

        access_token = response.json().get("access_token")
        if not access_token:
            raise GoogleAuthError("Google did not return an access token.")

        user_response = requests.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if user_response.status_code != 200:
            raise GoogleAuthError("Google account information could not be retrieved.")

        info = user_response.json()
        subject = str(info.get("sub", "")).strip()
        email = str(info.get("email", "")).strip().lower()
        if not subject or not email:
            raise GoogleAuthError("Google did not provide the required account identity.")

        return GoogleIdentity(
            provider_user_id=subject,
            email=email,
            name=str(info.get("name", "")).strip(),
            given_name=str(info.get("given_name", "")).strip(),
            family_name=str(info.get("family_name", "")).strip(),
            picture=str(info.get("picture", "")).strip(),
            verified_email=bool(info.get("email_verified", False)),
        )
    finally:
        server.shutdown()
        server.server_close()
