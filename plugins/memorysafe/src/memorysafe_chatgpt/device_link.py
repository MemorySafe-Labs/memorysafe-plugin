"""This computer's link to the person's hosted account: one sign-in, kept owner-only.

A computer in hosted mode holds one device link. The person clicks "Sign in" on the dashboard;
the browser goes to the hosted sign-in with PKCE and comes back to the dashboard's own
/callback on 127.0.0.1; the code is exchanged for tokens; the refresh token lands in the
state dir beside storage-mode.json, readable by its owner only. Every assistant on the
computer shares the link through the shared plugin: one sign-in, knowingly, not one per
assistant.

What this module promises:
  * No network call happens unless the person asked for one: sign-in, a refresh while hosted
    mode is serving them, sign-out. Local mode never touches this module.
  * The link is the person's. Sign-out revokes on the server and deletes the file; account
    erasure revokes it server-side; `memorysafe uninstall` removes the state dir with it.
    Choosing "On this computer" again signs out too (plan, 9 Nov): a token must not sit on a
    computer whose owner decided memories no longer live in the account.
  * Nothing here caches memory text. The file holds tokens, the issuer's endpoints and dates;
    the server's access token names no email, so the dashboard says since when, not who.

Two facts about the hosted server shape the code:
  * Refresh tokens rotate: each refresh spends the old one and returns a new one. The new
    record is written before the new token is used, and a refresh that fails after the server
    rotated is the one case this cannot cover: the next attempt finds the old token spent.
  * The server treats a spent refresh token used again as theft and revokes the whole
    family, which with the plugin's single client identity (client_identity.py) is every
    computer of this person. So a refresh that the server refuses deletes the local link and
    says "sign in again" instead of retrying; retrying would sign everyone out.

Three honest failure sentences, used by the dashboard, the doctor and (increment 3) the
tools: NOT_LINKED, SIGN_IN_AGAIN, OFFLINE.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from . import client_identity, device
from .device import read_private_json, utc_now, write_private_json

LINK_FILE = "device-link.json"
# A sign-in the person started but did not finish is forgotten after this long; the server's
# own window is similar (ten minutes).
PENDING_SECONDS = 600
# Refresh this long before the access token's expiry, so a call that starts at the edge does
# not arrive with a token the server has just stopped honouring.
REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10

NOT_LINKED = "Hosted is chosen on this computer but it is not signed in; open the MemorySafe dashboard and sign in."
SIGN_IN_AGAIN = "This computer's sign-in to your hosted account has ended; open the MemorySafe dashboard and sign in again."
OFFLINE = "Your hosted account could not be reached from this computer; your memories were not changed."


class LinkError(RuntimeError):
    """A failure the person can act on; the message is one of the three sentences or as plain."""

    def __init__(self, message: str, *, linked: bool) -> None:
        super().__init__(message)
        self.linked = linked


# -- the record --------------------------------------------------------------------------------

def link_path(state_dir: Path) -> Path:
    return Path(state_dir) / LINK_FILE


def read_link(state_dir: Path) -> dict[str, Any]:
    """The record, or {} when there is none or it is unreadable (never a half-link)."""

    record = read_private_json(link_path(state_dir))
    if not isinstance(record.get("refresh_token"), str) or not record["refresh_token"]:
        return {}
    return record


def delete_link(state_dir: Path) -> bool:
    path = link_path(state_dir)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def forget_access_token(state_dir: Path, spent: str | None = None) -> None:
    """Make the next access_token() refresh: the server stopped honouring `spent`, the
    access token this caller used. The link itself stays; only the hour-long token goes.

    Under the refresh lock and read again there, like a refresh: written from a copy read
    before another process refreshed, the file got back a refresh token already spent, and
    the next refresh replayed it, which signs the person out on every computer. And if the
    token in the file is no longer `spent`, someone has refreshed since: nothing to drop."""

    with _refreshing(state_dir):
        record = read_link(state_dir)
        if not record:
            return
        if spent is not None and record.get("access_token") != spent:
            return
        record["access_expires_at"] = 0
        record.pop("access_token", None)
        write_private_json(link_path(state_dir), record)


def status(state_dir: Path, now: Callable[[], float] | None = None) -> dict[str, Any]:
    """What the dashboard and the doctor may say, with no token in it."""

    now = now or time.time
    record = read_link(state_dir)
    if not record:
        return {"linked": False}
    return {
        "linked": True,
        "issuer": record.get("issuer"),
        "linked_at": record.get("linked_at"),
        "last_refreshed_at": record.get("last_refreshed_at"),
        "access_token_valid": float(record.get("access_expires_at", 0)) > now() + REFRESH_MARGIN_SECONDS,
        # The server's refresh tokens live 30 days from issue. A link not
        # refreshed in that long is dead on the server whatever the file says.
        "stale": _is_stale(record, now()),
    }


# The server's refresh lifetime; a refresh token older than this is refused by the server.
REFRESH_LIFETIME_SECONDS = 30 * 24 * 3600


def _is_stale(record: dict[str, Any], now: float) -> bool:
    newest = record.get("last_refreshed_at") or record.get("linked_at")
    if not isinstance(newest, str):
        return False
    from datetime import datetime

    try:
        issued = datetime.fromisoformat(newest.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return now - issued > REFRESH_LIFETIME_SECONDS


# -- HTTP, small and replaceable ------------------------------------------------------------------

HttpCall = Callable[[str, dict[str, str] | None, dict[str, str]], tuple[int, dict[str, Any]]]


def _http(url: str, form: dict[str, str] | None, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """POST `form` (urlencoded) or GET when form is None. Returns (status, json body or {}).

    Only https is ever called, and only on the issuer the link was made with. A connection
    failure is OSError, which callers turn into OFFLINE."""

    if not url.startswith("https://"):
        raise LinkError("The hosted sign-in must use https.", linked=False)
    data = urllib.parse.urlencode(form).encode("ascii") if form is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if form is not None else "GET")
    request.add_header("Accept", "application/json")
    if form is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with open_without_redirects(request, HTTP_TIMEOUT_SECONDS) as response:
            return response.status, _json_body(response.read())
    except urllib.error.HTTPError as error:
        return error.code, _json_body(error.read())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def open_without_redirects(request: urllib.request.Request, timeout: float):
    """Send a request that carries a token or a code, following no redirect.

    urllib follows a 301, 302 or 303 and sends the same headers to wherever it points,
    plain http included, so "only https, only the issuer" held for the first hop alone. The
    account's endpoints do not redirect; a redirect here is an answer we do not act on."""

    return _OPENER.open(request, timeout=timeout)


def _json_body(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _endpoints(origin: str, http: HttpCall) -> dict[str, str]:
    """The issuer's /authorize, /token and /revoke from its metadata; the standard paths when
    the metadata cannot be read, so an unreachable metadata document is not a dead end."""

    defaults = {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/authorize",
        "token_endpoint": f"{origin}/token",
        "revocation_endpoint": f"{origin}/revoke",
    }
    try:
        code, meta = http(origin + client_identity.METADATA_PATH, None, {})
    except OSError:
        return defaults
    if code != 200:
        return defaults
    found = {key: meta[key] for key in defaults if isinstance(meta.get(key), str) and meta[key].startswith("https://")}
    return {**defaults, **found}


# -- sign-in -------------------------------------------------------------------------------------

_pending: dict[str, dict[str, Any]] = {}
_pending_lock = threading.Lock()


def _forget_stale_pending(now: float) -> None:
    for state, entry in list(_pending.items()):
        if entry["started"] + PENDING_SECONDS < now:
            _pending.pop(state, None)


def begin_sign_in(port: int, *, origin: str = client_identity.HOSTED_ORIGIN, http: HttpCall | None = None,
                  now: Callable[[], float] = time.time) -> dict[str, str]:
    """Start a sign-in: returns the URL the browser must open, and remembers the PKCE verifier
    and the state until /callback brings them back. The dashboard calls this; nothing is
    written to disk until the sign-in finishes."""
    http = http or _http

    endpoints = _endpoints(origin, http)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    redirect = client_identity.redirect_uri(port)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_identity.CLIENT_ID,
            "redirect_uri": redirect,
            "scope": " ".join(client_identity.SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": _resource(origin),
        }
    )
    with _pending_lock:
        _forget_stale_pending(now())
        _pending[state] = {"verifier": verifier, "redirect": redirect, "endpoints": endpoints, "started": now()}
    return {"url": f"{endpoints['authorization_endpoint']}?{query}", "state": state}


def forget_pending_sign_ins() -> None:
    """Drop every sign-in that was started and not finished. The person went back to keeping
    memories on this computer; a tab still open on the account must not sign it in after that."""

    with _pending_lock:
        _pending.clear()


def finish_sign_in(state_dir: Path, *, code: str, state: str, iss: str | None, http: HttpCall | None = None,
                   now: Callable[[], float] = time.time) -> dict[str, Any]:
    """The browser came back to /callback: check the state, exchange the code, write the link.

    `iss` is the authorization_response_iss_parameter (RFC 9207); the server sends it, and a
    callback from anywhere else is refused before any token call."""
    http = http or _http

    with _pending_lock:
        _forget_stale_pending(now())
        pending = _pending.pop(state, None) if state else None
    if pending is None:
        raise LinkError("This sign-in was not started from this dashboard, or it took too long; start again.", linked=False)
    endpoints = pending["endpoints"]
    # The server always sends `iss`; a callback without it did not come from the server.
    if iss is None or iss.rstrip("/") != endpoints["issuer"].rstrip("/"):
        raise LinkError("The sign-in came back from a different server than the one it went to; start again.", linked=False)
    if not code:
        raise LinkError("The sign-in did not finish; start again.", linked=False)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect"],
        "client_id": client_identity.CLIENT_ID,
        "code_verifier": pending["verifier"],
        "resource": _resource(endpoints["issuer"]),
    }
    tokens = _token_call(endpoints["token_endpoint"], form, http, linked=False)
    record = _record_from(tokens, endpoints, previous={}, now=now())
    record["linked_at"] = utc_now()
    write_private_json(link_path(state_dir), record)
    return status(state_dir, now)


# -- using and ending the link --------------------------------------------------------------------

def access_token(state_dir: Path, *, http: HttpCall | None = None, now: Callable[[], float] = time.time) -> str:
    """A bearer token good for at least REFRESH_MARGIN_SECONDS, refreshing first if needed.

    LinkError(NOT_LINKED) with no link; LinkError(SIGN_IN_AGAIN) when the server refuses the
    refresh (the link is deleted, see the module doc on replay); LinkError(OFFLINE) when the
    server cannot be reached (the link is kept: being offline is not a reason to sign out)."""
    http = http or _http

    record = read_link(state_dir)
    if not record:
        raise LinkError(NOT_LINKED, linked=False)
    if float(record.get("access_expires_at", 0)) > now() + REFRESH_MARGIN_SECONDS and record.get("access_token"):
        return str(record["access_token"])
    with _refreshing(state_dir):
        return _refresh(state_dir, http, now)


_REFRESH_LOCK = threading.Lock()


@contextmanager
def _refreshing(state_dir: Path) -> Iterator[None]:
    """One refresh at a time, across this process's threads and every MemorySafe process.

    A refresh token is single use and a replayed one revokes the whole family, which for
    this client is every computer the person signed in on. Tool calls run in worker
    threads and each assistant is its own process, so two calls landing just after the
    hourly expiry both sent the same refresh token: the second was a replay, every
    computer was signed out, and the loser then deleted the link here (found 10 Nov 2026).
    The lock file is empty and stays; flock is released when the handle closes.
    """

    with _REFRESH_LOCK:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "device-link.lock", "a+", encoding="utf-8") as handle:
            device._lock_exclusive(handle)
            try:
                yield
            finally:
                device._unlock(handle)


def _refresh(state_dir: Path, http: HttpCall, now: Callable[[], float]) -> str:
    # Read again under the lock: whoever held it before may have refreshed already, and
    # the token it stored is the one to use. Its refresh token is the only live one.
    record = read_link(state_dir)
    if not record:
        raise LinkError(NOT_LINKED, linked=False)
    if float(record.get("access_expires_at", 0)) > now() + REFRESH_MARGIN_SECONDS and record.get("access_token"):
        return str(record["access_token"])
    endpoints = {
        "issuer": record["issuer"],
        "token_endpoint": record["token_endpoint"],
        "revocation_endpoint": record.get("revocation_endpoint", record["issuer"] + "/revoke"),
    }
    form = {
        "grant_type": "refresh_token",
        "refresh_token": record["refresh_token"],
        "client_id": client_identity.CLIENT_ID,
        "resource": _resource(record["issuer"]),
    }
    try:
        tokens = _token_call(endpoints["token_endpoint"], form, http, linked=True)
    except LinkError as error:
        if error.linked is False:
            delete_link(state_dir)  # refused: retrying would sign out every computer
        raise
    refreshed = _record_from(tokens, endpoints, previous=record, now=now())
    refreshed["last_refreshed_at"] = utc_now()
    write_private_json(link_path(state_dir), refreshed)
    return str(refreshed["access_token"])


def sign_out(state_dir: Path, *, http: HttpCall | None = None) -> dict[str, Any]:
    """Revoke on the server, then delete the file. The file goes even when the server cannot
    be reached: the person asked for this computer to stop, and that at least is in our hands.

    Because the plugin is one client identity, the server's revoke ends this person's refresh
    tokens on every computer, not only this one. The dashboard says so before the click."""
    http = http or _http

    record = read_link(state_dir)
    if not record:
        # Nothing was signed in, so there is nothing to report: the dashboard says nothing.
        return {"linked": False, "was_linked": False, "revoked": False, "reached": True}
    reached = False
    revoked = False
    endpoint = record.get("revocation_endpoint") or f"{record['issuer']}/revoke"
    try:
        code, _body = http(endpoint, {"token": record["refresh_token"], "token_type_hint": "refresh_token",
                                      "client_id": client_identity.CLIENT_ID}, {})
        reached = True
        revoked = code == 200
    except (OSError, LinkError):
        pass
    delete_link(state_dir)
    return {"linked": False, "was_linked": True, "revoked": revoked, "reached": reached}


# -- helpers -------------------------------------------------------------------------------------

def _resource(origin: str) -> str:
    return origin.rstrip("/") + "/mcp"


def _token_call(endpoint: str, form: dict[str, str], http: HttpCall, *, linked: bool) -> dict[str, Any]:
    try:
        code, body = http(endpoint, form, {})
    except OSError:
        raise LinkError(OFFLINE, linked=linked) from None
    if code == 200 and isinstance(body.get("access_token"), str):
        return body
    error = str(body.get("error", ""))
    if code in (400, 401) and error in ("invalid_grant", "invalid_client", "unauthorized_client", "invalid_scope"):
        raise LinkError(SIGN_IN_AGAIN if linked else "The hosted account did not accept this sign-in; start again.", linked=False)
    raise LinkError(OFFLINE, linked=linked)


def _record_from(tokens: dict[str, Any], endpoints: dict[str, str], *, previous: dict[str, Any], now: float) -> dict[str, Any]:
    """The record to write: the new tokens over what the previous record knew."""

    expires_in = tokens.get("expires_in")
    lifetime = float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else 3600.0
    refresh = tokens.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        # Rotation always returns one; a server that did not would leave this computer with
        # an hour of access and no way on, so keep the one that worked.
        refresh = str(previous.get("refresh_token", ""))
        if not refresh:
            raise LinkError("The hosted account did not grant a lasting sign-in; start again.", linked=False)
    record = {
        **{key: previous[key] for key in ("linked_at", "last_refreshed_at") if key in previous},
        "issuer": endpoints["issuer"],
        "token_endpoint": endpoints["token_endpoint"],
        "revocation_endpoint": endpoints.get("revocation_endpoint", endpoints["issuer"] + "/revoke"),
        "client_id": client_identity.CLIENT_ID,
        "scope": str(tokens.get("scope") or " ".join(client_identity.SCOPES)),
        "access_token": str(tokens["access_token"]),
        "access_expires_at": now + lifetime,
        "refresh_token": refresh,
    }
    return record
