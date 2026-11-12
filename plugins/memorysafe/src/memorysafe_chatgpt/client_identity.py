"""Who this plugin is when it signs in to a person's hosted account.

The hosted edition's sign-in server takes two kinds of client. A Client ID Metadata Document (CIMD): the client's id is an https URL, and
the document at that URL names the client and lists where it may be sent back to. Dynamic
Client Registration (DCR, RFC 7591): every install registers itself on first sign-in, and the
server keeps a record per device.

CIMD was chosen on 9 November 2026. Every copy of the plugin is the same public client with
one static identity; nothing registers, nothing accumulates on the server per computer,
nothing extra is erased with the account. DCR stays the server's fallback for other apps,
not a path this plugin takes.

What the choice costs, said plainly: the server's refresh tokens form one family per
(client, person). Every computer a person signs in from shares that family, so a sign-out
that revokes on the server ends the link on every computer of theirs, and a refresh token
replayed from any one of them ends them all (the server's replay rule). device_link.py
documents both where they bite. Per-device families would need a server-side change, or
DCR; that trade is this module's to flip, not the flow's.

The document itself is public metadata, published on the website at CLIENT_ID. It is
generated here (client_document()) so the plugin and the published file cannot drift: the
private test suite validates it with the server's own CIMD reader.
"""

from __future__ import annotations

# The hosted edition: issuer of the tokens, home of /authorize, /token and /revoke, and the
# origin the MCP resource lives under. One constant; storage_mode.HOSTED_CONNECT_URL is a
# page on it.
HOSTED_ORIGIN = "https://memory.memorysafe.ca"
RESOURCE_URL = f"{HOSTED_ORIGIN}/mcp"
METADATA_PATH = "/.well-known/oauth-authorization-server"

# The client's id is the URL of its document. The website serves it; its contents are
# client_document() below, byte for byte.
CLIENT_ID = "https://memorysafe.ca/oauth/memorysafe-plugin.json"
CLIENT_NAME = "MemorySafe plugin"
CLIENT_URI = "https://memorysafe.ca"

# The dashboard binds 127.0.0.1 (setup_app.HOST). Both loopback names are registered with no
# port, as RFC 8252 section 7.3 allows: the server matches any port against them, so the
# runtime redirect names the port the dashboard really got.
CALLBACK_PATH = "/callback"
REDIRECT_URIS = (f"http://127.0.0.1{CALLBACK_PATH}", f"http://localhost{CALLBACK_PATH}")

# `memories` is the only memory scope the server has; `offline_access` is what makes it hand
# out a refresh token, which is the whole point of a link that outlives one hour.
SCOPES = ("memories", "offline_access")


def client_document() -> dict:
    """The CIMD document, as the website publishes it and the server reads it.

    token_endpoint_auth_method is `none`: the plugin is a public client (its code is on every
    computer, so a secret would be no secret) and PKCE is what binds a code to the computer
    that asked for it."""

    return {
        "client_id": CLIENT_ID,
        "client_name": CLIENT_NAME,
        "client_uri": CLIENT_URI,
        "redirect_uris": list(REDIRECT_URIS),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": " ".join(SCOPES),
    }


def redirect_uri(port: int) -> str:
    """The redirect for a dashboard listening on `port`: the registered 127.0.0.1 one, with the port."""

    return f"http://127.0.0.1:{int(port)}{CALLBACK_PATH}"
