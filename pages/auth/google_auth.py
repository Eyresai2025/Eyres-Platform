"""Google OAuth 2.0 helpers for the EYRES desktop application.

The OAuth callback uses a loopback HTTP listener on 127.0.0.1.

Qt6 integration note
--------------------
The browser is NOT opened from this backend module. The UI calls
QDesktopServices.openUrl(...) on the Qt GUI thread and this module waits for
the loopback callback in a worker thread. This avoids Windows browser-launch
quirks and keeps all GUI/native URL handling inside Qt6.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass

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
    server_version = "EYRESOAuth/2.0"

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        result = {k: v[0] for k, v in params.items()}
        self.server.oauth_result = result
        self.server.oauth_event.set()

        cancelled = bool(result.get("error"))
        if cancelled:
            heading = "Google Sign-In cancelled"
            message = (
                "No changes were made. You can close this browser tab "
                "and return to EYRES."
            )
        else:
            heading = "Google Sign-In complete"
            message = (
                "Authentication has returned to EYRES. "
                "You can close this browser tab."
            )

        body = f"""<!doctype html>
        <html>
        <head>
          <meta charset='utf-8'>
          <title>EYRES Sign-In</title>
          <style>
            body {{
              margin:0; min-height:100vh; display:grid; place-items:center;
              font-family:Segoe UI,Arial,sans-serif;
              background:#F6F8FC; color:#172033;
            }}
            .card {{
              width:min(92vw,460px);
              background:#fff;
              border:1px solid #DDE5F0;
              border-radius:18px;
              padding:34px;
              text-align:center;
              box-shadow:0 18px 50px rgba(38,64,110,.12);
            }}
            h2 {{ margin:0 0 10px; font-size:22px; }}
            p {{ margin:0; color:#64748B; line-height:1.55; font-size:14px; }}
          </style>
        </head>
        <body>
          <div class='card'>
            <h2>{heading}</h2>
            <p>{message}</p>
          </div>
        </body>
        </html>"""
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
        self.oauth_event = threading.Event()


@dataclass
class GoogleAuthFlow:
    client_id: str
    client_secret: str
    server: _CallbackServer
    auth_url: str
    redirect_uri: str
    state: str
    verifier: str

    def close(self):
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass


def _free_loopback_server() -> _CallbackServer:
    try:
        return _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
    except OSError as exc:
        raise GoogleAuthError(
            "EYRES could not start the local Google Sign-In callback listener "
            "on 127.0.0.1."
        ) from exc


def prepare_google_auth() -> GoogleAuthFlow:
    """Create the loopback listener and return the Google authorization URL."""
    client_id = os.getenv("EYRES_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("EYRES_GOOGLE_CLIENT_SECRET", "").strip()

    if not client_id:
        raise GoogleAuthError(
            "Google Sign-In is not configured. "
            "Set EYRES_GOOGLE_CLIENT_ID in the .env file."
        )

    server = _free_loopback_server()
    port = int(server.server_address[1])
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

    return GoogleAuthFlow(
        client_id=client_id,
        client_secret=client_secret,
        server=server,
        auth_url=auth_url,
        redirect_uri=redirect_uri,
        state=state,
        verifier=verifier,
    )


def complete_google_auth(
    flow: GoogleAuthFlow,
    timeout_seconds: int = 180,
) -> GoogleIdentity:
    """Wait for Google's loopback callback, exchange the code and return identity."""
    try:
        received = flow.server.oauth_event.wait(timeout=max(10, int(timeout_seconds)))
        result = flow.server.oauth_result

        if not received or not result:
            raise GoogleAuthError(
                "Google Sign-In timed out because EYRES did not receive the "
                "browser callback. Complete the Google page in the browser and "
                "allow the redirect to 127.0.0.1."
            )

        if result.get("error"):
            description = result.get("error_description") or result.get("error")
            raise GoogleAuthError(
                f"Google Sign-In was not completed: {description}"
            )

        if not secrets.compare_digest(result.get("state", ""), flow.state):
            raise GoogleAuthError(
                "Invalid Google OAuth state received. Please try again."
            )

        code = result.get("code")
        if not code:
            raise GoogleAuthError(
                "Google did not return an authorization code."
            )

        token_data = {
            "code": code,
            "client_id": flow.client_id,
            "redirect_uri": flow.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": flow.verifier,
        }
        if flow.client_secret:
            token_data["client_secret"] = flow.client_secret

        try:
            response = requests.post(
                TOKEN_ENDPOINT,
                data=token_data,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleAuthError(
                "EYRES could not reach Google's token service."
            ) from exc

        if response.status_code != 200:
            try:
                payload = response.json()
                detail = payload.get("error_description") or payload.get("error")
            except Exception:
                detail = response.text[:300]
            raise GoogleAuthError(
                f"Google token exchange failed: {detail}"
            )

        access_token = response.json().get("access_token")
        if not access_token:
            raise GoogleAuthError(
                "Google did not return an access token."
            )

        try:
            user_response = requests.get(
                USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise GoogleAuthError(
                "EYRES could not retrieve Google account information."
            ) from exc

        if user_response.status_code != 200:
            raise GoogleAuthError(
                "Google account information could not be retrieved."
            )

        info = user_response.json()
        subject = str(info.get("sub", "")).strip()
        email = str(info.get("email", "")).strip().lower()

        if not subject or not email:
            raise GoogleAuthError(
                "Google did not provide the required account identity."
            )

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
        flow.close()


def authenticate_google(timeout_seconds: int = 180) -> GoogleIdentity:
    """Backward-compatible non-Qt helper.

    Existing non-Qt callers can still use this function. Qt6 UI code should use
    prepare_google_auth() + QDesktopServices.openUrl() + complete_google_auth().
    """
    import webbrowser

    flow = prepare_google_auth()
    try:
        if not webbrowser.open(flow.auth_url, new=2, autoraise=True):
            raise GoogleAuthError(
                "Could not open the default browser for Google Sign-In."
            )
        return complete_google_auth(flow, timeout_seconds=timeout_seconds)
    except Exception:
        flow.close()
        raise
