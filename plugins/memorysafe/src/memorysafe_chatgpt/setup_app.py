from __future__ import annotations

import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from . import agents as agents_module
from .bootstrap_catalog import VERSION
from .dashboard import dashboard_html, panel_html
from .doctor import create_support_bundle, find_support_bundle, run_doctor
from .device import (
    ensure_device_identity,
    masked_device_id,
    read_private_json,
    utc_now,
    write_private_json,
)
from .storage import MemoryStore


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_CONNECT_URL = "https://chatgpt.com/#settings/Connectors"
RUNTIME_KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9_\-]{27,}$")
TUNNEL_ID_PATTERN = re.compile(r"^tunnel_[A-Za-z0-9]+$")


@dataclass(frozen=True)
class SetupPaths:
    install_root: Path
    state_dir: Path
    database_path: Path
    secret_file: Path
    tunnel_id_file: Path
    health_url_file: Path
    legal_dir: Path
    connect_url: str

    @classmethod
    def from_environment(cls) -> "SetupPaths":
        root = Path(
            os.environ.get("MEMORYSAFE_INSTALL_ROOT", Path(__file__).resolve().parents[2])
        ).expanduser().resolve()
        state = Path(os.environ.get("MEMORYSAFE_STATE_DIR", root / "runtime-state")).expanduser().resolve()
        return cls(
            install_root=root,
            state_dir=state,
            database_path=Path(
                os.environ.get("MEMORYSAFE_DB_PATH", root / "data" / "memorysafe.sqlite3")
            ).expanduser().resolve(),
            secret_file=Path(
                os.environ.get("MEMORYSAFE_RUNTIME_KEY_FILE", root / ".secrets" / "tunnel-runtime-key")
            ).expanduser().resolve(),
            tunnel_id_file=Path(
                os.environ.get("MEMORYSAFE_TUNNEL_ID_FILE", state / "tunnel-id")
            ).expanduser().resolve(),
            health_url_file=Path(
                os.environ.get("MEMORYSAFE_HEALTH_URL_FILE", state / "health" / "tunnel.url")
            ).expanduser().resolve(),
            legal_dir=Path(os.environ.get("MEMORYSAFE_LEGAL_DIR", root / "legal")).expanduser().resolve(),
            connect_url=os.environ.get("MEMORYSAFE_CONNECT_URL", DEFAULT_CONNECT_URL),
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _loopback_health_url(path: Path) -> str:
    raw = _read_text(path)
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return ""
    return raw.rstrip("/")


def connector_ready(paths: SetupPaths) -> bool:
    base_url = _loopback_health_url(paths.health_url_file)
    if not base_url:
        return False
    try:
        with urllib.request.urlopen(f"{base_url}/readyz", timeout=0.45) as response:
            return response.status == HTTPStatus.OK
    except (OSError, urllib.error.URLError, ValueError):
        return False


def consent_payload(paths: SetupPaths) -> dict[str, Any]:
    return read_private_json(paths.state_dir / "consent.json")


def status_payload(paths: SetupPaths) -> dict[str, Any]:
    identity = ensure_device_identity(paths.state_dir)
    consent = consent_payload(paths)
    tunnel_id = _read_text(paths.tunnel_id_file)
    key_present = paths.secret_file.is_file() and paths.secret_file.stat().st_size >= 30
    store = MemoryStore(paths.database_path)
    return {
        "product": "MemorySafe Beta",
        "version": VERSION,
        # Whatever process serves this request. The plugin launcher stops a dashboard it
        # recorded only when this equals the PID it recorded, because a live PID alone can
        # be a reused one after a reboot.
        "pid": os.getpid(),
        "device_id": masked_device_id(identity),
        "surface_mode": "desktop-hosted",
        "desktop_installed": True,
        "runtime_key_saved": key_present,
        "tunnel_configured": bool(TUNNEL_ID_PATTERN.fullmatch(tunnel_id)),
        "tunnel_id": tunnel_id if TUNNEL_ID_PATTERN.fullmatch(tunnel_id) else "",
        "connector_online": connector_ready(paths),
        "terms_accepted": bool(consent.get("terms_accepted")),
        "automatic_mode": store.automatic_mode_enabled(),
        "connect_url": paths.connect_url,
    }


def dashboard_payload(paths: SetupPaths) -> dict[str, Any]:
    store = MemoryStore(paths.database_path)
    payload = store.health()
    payload["status"] = "healthy"
    payload["recent_memories"] = store.find("", 6)
    return payload


# Where a report goes. Nothing is sent from here: the dashboard opens an email draft
# the person reviews, attaches the bundle to and sends themselves.
SUPPORT_EMAIL = "contact@memorysafe.ca"


def _report_email(paths: SetupPaths, file_name: str, description: str) -> dict[str, str]:
    """The draft that turns "a ZIP in Downloads" into an actual report.

    Report a problem used to stop at the file, with no destination and no place to say
    what happened, so a tester who hit a problem had nothing to do with it. A browser
    cannot attach a file to a mailto draft, so the body says which one to attach.
    """

    device = masked_device_id(ensure_device_identity(paths.state_dir))
    subject = f"MemorySafe problem report · {device} · {VERSION}"
    body = "\n".join(
        (
            "What went wrong:",
            # A mailto URL has practical length limits; the full text is in the bundle.
            description[:1500] if description else "(not described)",
            "",
            f"Please attach {file_name} from your Downloads folder before sending.",
            "It holds status, counts and sanitized error signatures only: no memories, "
            "no conversations, no keys.",
            "",
            f"MemorySafe {VERSION} · {device} · {sys.platform}",
        )
    )
    # quote, not quote_plus: mail clients show a "+" literally where a space was meant.
    query = urlencode({"subject": subject, "body": body}, quote_via=quote)
    return {"to": SUPPORT_EMAIL, "subject": subject, "mailto": f"mailto:{SUPPORT_EMAIL}?{query}"}


def support_bundle_payload(paths: SetupPaths, description: str = "") -> dict[str, Any]:
    from .doctor import DESCRIPTION_LIMIT

    description = str(description or "").strip()[:DESCRIPTION_LIMIT]
    bundle = create_support_bundle(paths.install_root, description=description)
    try:
        display_path = f"~/{bundle.relative_to(Path.home())}"
    except ValueError:
        display_path = str(bundle)
    return {
        "created": True,
        "path": display_path,
        # The dashboard hands this name back to /api/support-bundle/download.
        "file_name": bundle.name,
        "email": _report_email(paths, bundle.name, description),
        "privacy": {
            "memory_contents_included": False,
            "conversation_history_included": False,
            "runtime_keys_included": False,
            "uploaded_automatically": False,
        },
    }


def forget_memory(paths: SetupPaths, memory_id: str) -> dict[str, Any]:
    """Remove one memory from active recall, from the dashboard rather than a chat."""
    return MemoryStore(paths.database_path).forget(memory_id)


def set_automatic_mode(paths: SetupPaths, enabled: bool) -> None:
    MemoryStore(paths.database_path).set_automatic_mode(bool(enabled))
    consent = consent_payload(paths)
    if consent:
        consent["automatic_mode"] = bool(enabled)
        consent["automatic_mode_updated_at"] = utc_now()
        write_private_json(paths.state_dir / "consent.json", consent)


def save_connection(paths: SetupPaths, runtime_key: str, tunnel_id: str) -> None:
    clean_tunnel = tunnel_id.strip()
    if not TUNNEL_ID_PATTERN.fullmatch(clean_tunnel):
        raise ValueError("Enter the complete tunnel ID beginning with tunnel_.")
    _write_private_text(paths.tunnel_id_file, clean_tunnel)

    clean_key = runtime_key.strip()
    if clean_key:
        if not RUNTIME_KEY_PATTERN.fullmatch(clean_key):
            raise ValueError("Paste the complete OpenAI runtime key beginning with sk-.")
        _write_private_text(paths.secret_file, clean_key)
    elif not paths.secret_file.is_file():
        raise ValueError("A runtime key is required for the first connection.")

    if sys.platform != "darwin":
        # The tunnel connector is launchd-managed, and launchd -- along with
        # os.getuid(), which the kickstart command below needs -- exists only on
        # macOS. Guided setup runs this same save_connection() on every platform,
        # and os.getuid() doesn't exist on Windows at all: it raised an uncaught
        # AttributeError there, which the (OSError, TimeoutExpired) guard below
        # was never meant to (and cannot) catch, since it never gets that far.
        return

    try:
        subprocess.run(
            [
                "/bin/launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/ca.memorysafe.beta.tunnel",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def save_consent(paths: SetupPaths, terms_accepted: bool, automatic_mode: bool) -> None:
    if not terms_accepted:
        raise ValueError("Accept the Beta Terms and acknowledge the Privacy Policy to continue.")
    write_private_json(
        paths.state_dir / "consent.json",
        {
            "schema_version": 1,
            "terms_accepted": True,
            "terms_version": "0.1",
            "privacy_version": "0.1",
            "accepted_at": utc_now(),
            "automatic_mode": bool(automatic_mode),
        },
    )
    set_automatic_mode(paths, automatic_mode)


def markdown_to_html(markdown: str) -> str:
    parts: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        escaped = html.escape(line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
        if line.startswith("### "):
            flush_paragraph()
            parts.append(f"<h3>{escaped[4:]}</h3>")
        elif line.startswith("## "):
            flush_paragraph()
            parts.append(f"<h2>{escaped[3:]}</h2>")
        elif line.startswith("# "):
            flush_paragraph()
            parts.append(f"<h1>{escaped[2:]}</h1>")
        elif line.startswith("- "):
            flush_paragraph()
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{escaped[2:]}</li>")
        else:
            paragraph.append(escaped.rstrip("  "))
    flush_paragraph()
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


SETUP_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Set up MemorySafe</title>
  <style>
    :root{--bg:#05080d;--card:#0c121c;--card2:#101925;--line:rgba(190,218,245,.14);--text:#f4f8fb;--muted:#91a0b2;--cyan:#19e4e9;--blue:#4b83ff;--green:#52dc88;--amber:#f4b75e;--red:#ff6a92}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 80% 0,rgba(25,228,233,.11),transparent 360px),var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    main{width:min(850px,calc(100% - 32px));margin:0 auto;padding:42px 0 60px}.top{display:flex;align-items:center;gap:14px;margin-bottom:28px}.logo{width:48px;height:48px;display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:9px;border:1px solid rgba(25,228,233,.45);border-radius:13px;background:#07111a}.logo i{border-radius:3px;background:var(--cyan)}.logo i:nth-child(2),.logo i:nth-child(3){background:var(--blue)}h1{margin:0;font-size:29px;letter-spacing:-.7px}.subtitle{color:var(--muted);font-size:13px}.device{margin-left:auto;text-align:right}.device strong{display:block;color:var(--cyan);font:700 12px ui-monospace,SFMono-Regular,Menlo,monospace}.device span{color:var(--muted);font-size:11px}
    .route{display:grid;grid-template-columns:1fr 44px 1fr;gap:12px;align-items:center;padding:17px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(140deg,rgba(75,131,255,.07),rgba(25,228,233,.03))}.endpoint{padding:15px;border-radius:11px;background:var(--card2);border:1px solid var(--line)}.endpoint span{display:block;color:var(--muted);font-size:11px}.endpoint strong{display:block;margin-top:4px;font-size:16px}.arrow{text-align:center;color:var(--cyan);font-size:22px}.online{color:var(--green)!important}.offline{color:var(--amber)!important}
    .steps{display:grid;gap:12px;margin-top:14px}.step{display:grid;grid-template-columns:42px 1fr;gap:14px;padding:19px;border:1px solid var(--line);border-radius:15px;background:var(--card)}.number{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;background:rgba(75,131,255,.12);color:#9ab7ff;font-weight:800}.step.done .number{background:rgba(82,220,136,.12);color:var(--green)}.step h2{margin:2px 0 4px;font-size:17px}.step p{margin:0;color:var(--muted);font-size:12px}.actions{margin-top:14px;display:flex;gap:10px;flex-wrap:wrap}.button,button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 16px;border:0;border-radius:10px;background:linear-gradient(135deg,var(--blue),#765df5);color:#fff;font:750 13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-decoration:none;cursor:pointer}.button.secondary,button.secondary{background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--text)}button:disabled,.button.disabled{opacity:.43;cursor:not-allowed;pointer-events:none}label{display:block;margin-top:12px;color:#dce6ef;font-size:12px;font-weight:700}input[type=password],input[type=text]{width:100%;margin-top:6px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#080d14;color:var(--text);font-size:14px;outline:none}input:focus{border-color:rgba(25,228,233,.5)}.check{display:flex;gap:9px;align-items:flex-start;margin-top:12px;color:var(--muted);font-weight:500}.check input{margin-top:3px;accent-color:var(--cyan)}.check a{color:#8bb8ff}.note{margin-top:10px;color:#6f7f92;font-size:11px}.message{display:none;margin-top:12px;padding:10px 12px;border-radius:9px;background:rgba(82,220,136,.08);color:#a5e7be;font-size:12px}.message.error{background:rgba(255,106,146,.08);color:#ffacc3}.footer{margin-top:16px;text-align:center;color:#667589;font-size:11px}@media(max-width:650px){main{padding-top:24px}.top{align-items:flex-start}.device{display:none}.route{grid-template-columns:1fr}.arrow{transform:rotate(90deg)}.step{grid-template-columns:1fr}.number{width:30px;height:30px}}
    .agent-list{display:grid;gap:8px;margin-top:14px}.agent{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 13px;border:1px solid var(--line);border-radius:11px;background:#080d14}.agent strong{display:block;font-size:14px}.agent small{display:block;margin-top:3px;color:var(--muted);font-size:11.5px;overflow-wrap:anywhere}.agent .state{flex:none;font:800 10.5px ui-monospace,Consolas,monospace;letter-spacing:.08em;padding:5px 9px;border-radius:7px}.agent .state.on{color:var(--green);border:1px solid rgba(82,220,136,.4)}.agent .state.off{color:#f4b75e;border:1px solid rgba(244,183,94,.4)}.agent button{flex:none;min-height:34px}.optional{margin:22px 0 0;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
  </style>
</head>
<body><main>
  <header class="top"><div class="logo" aria-hidden="true"><i></i><i></i><i></i><i></i></div><div><h1>Set up MemorySafe</h1><div class="subtitle">Install once. One memory for every assistant on this computer.</div></div><div class="device"><strong id="device-id">Loading…</strong><span>Secure device identity</span></div></header>
  <section class="route"><div class="endpoint"><span>Memory lives on</span><strong>This computer</strong></div><div class="arrow">↔</div><div class="endpoint"><span>Use MemorySafe from</span><strong>Your assistants</strong><span id="agents-summary" class="offline">Looking for them…</span></div></section>
  <section class="steps">
    <article class="step done"><div class="number">✓</div><div><h2>MemorySafe is installed</h2><p>The dashboard and the local connector are ready on this computer.</p><div class="actions"><a class="button" href="/dashboard">Open MemorySafe dashboard</a></div></div></article>
    <article class="step" id="agreement-step"><div class="number">2</div><div><h2>Review the private-beta agreement</h2><p>Legal acceptance and optional Automatic Mode use separate choices.</p><label class="check"><input id="terms" type="checkbox"> <span>I agree to the <a href="/legal/terms" target="_blank">Beta Terms of Use</a> and acknowledge the <a href="/legal/privacy" target="_blank">Privacy Policy</a>.</span></label><label class="check"><input id="automatic" type="checkbox"> <span><strong id="automatic-state">Automatic capture is off.</strong> <span id="automatic-help">Tick this to let MemorySafe save concise, durable, non-sensitive facts as you work.</span> Secrets, ID numbers, contact details, addresses and health information are never captured this way. You can change this whenever you like from the dashboard.</span></label><div class="actions"><button id="save-consent">Accept and continue</button></div><div id="consent-message" class="message"></div></div></article>
    <article class="step" id="assistants-step"><div class="number">3</div><div><h2>Connect your assistants</h2><p>Every assistant you connect shares the same memory. Each one is installed through its own installer; Claude Desktop asks you to confirm its extension yourself.</p><div class="agent-list" id="agent-list"></div><div id="agents-message" class="message"></div></div></article>
  </section>
  <section id="chatgpt-steps" hidden>
  <p class="optional">Optional · ChatGPT on the web, on this Mac</p>
  <section class="steps">
    <article class="step" id="connection-step"><div class="number">4</div><div><h2>Secure the private connection</h2><p>Your runtime key stays on this Mac and is never placed in chat.</p><label for="tunnel-id">Tunnel ID</label><input id="tunnel-id" type="text" placeholder="tunnel_…" autocomplete="off"><label for="runtime-key">OpenAI runtime key</label><input id="runtime-key" type="password" placeholder="Paste the key beginning with sk-" autocomplete="off"><div class="note" id="key-note">If a key was migrated from the earlier beta, you can leave this empty.</div><div class="actions"><button id="save-connection">Save private connection</button></div><div id="connection-message" class="message"></div></div></article>
    <article class="step" id="chatgpt-step"><div class="number">5</div><div><h2>Connect ChatGPT</h2><p>Open ChatGPT, enable MemorySafe, and the connector will identify this registered Mac automatically. <span id="online-label" class="offline">Checking connection…</span></p><div class="actions"><a class="button disabled" id="connect-button" href="/open-chatgpt" target="_blank">Connect MemorySafe to ChatGPT</a><button class="secondary" id="refresh" type="button">Refresh status</button></div><div class="note">The Mac must be awake for this local beta. Cloud mode can be added later as a separate opt-in.</div></div></article>
  </section>
  </section>
  <div class="footer">MemorySafe Labs Inc. · Private Beta __VERSION__ · contact@memorysafe.ca</div>
</main><script>
const setupToken=__SETUP_TOKEN__;
const byId=(id)=>document.getElementById(id);
let consentDirty=false;
function show(id,text,isError=false){const el=byId(id);el.textContent=text;el.classList.toggle('error',isError);el.style.display='block'}
async function api(path,options={}){const response=await fetch(path,{cache:'no-store',...options,headers:{'Content-Type':'application/json','X-MemorySafe-Setup-Token':setupToken,...(options.headers||{})}});const payload=await response.json();if(!response.ok)throw new Error(payload.error||'MemorySafe could not complete that step.');return payload}
// The label was fixed text, "Automatic capture is off.", beside a box that could be ticked --
// so a tester saw it ticked and "off" at once. It now follows the box.
function syncAutomatic(){const on=byId('automatic').checked;byId('automatic-state').textContent=on?'Automatic capture is on.':'Automatic capture is off.';byId('automatic-help').textContent=on?'MemorySafe saves concise, durable, non-sensitive facts as you work. Untick this to stop.':'Tick this to let MemorySafe save concise, durable, non-sensitive facts as you work.'}
function render(s){byId('device-id').textContent=s.device_id;if(!consentDirty){byId('terms').checked=Boolean(s.terms_accepted);byId('automatic').checked=Boolean(s.automatic_mode)}syncAutomatic();if(!byId('tunnel-id').value&&s.tunnel_id)byId('tunnel-id').value=s.tunnel_id;byId('agreement-step').classList.toggle('done',Boolean(s.terms_accepted));byId('connection-step').classList.toggle('done',Boolean(s.runtime_key_saved&&s.tunnel_configured));byId('chatgpt-step').classList.toggle('done',Boolean(s.connector_online));byId('key-note').textContent=s.runtime_key_saved?'A private runtime key is already saved. Leave the field empty to keep it.':'Paste the runtime key once; it will remain only on this Mac.';const online=byId('online-label');online.textContent=s.connector_online?'ONLINE · READY':'DESKTOP CONNECTOR OFFLINE';online.className=s.connector_online?'online':'offline';byId('connect-button').classList.toggle('disabled',!(s.terms_accepted&&s.runtime_key_saved&&s.tunnel_configured));}
async function refresh(){try{render(await api('/api/status'))}catch(e){byId('online-label').textContent='STATUS UNAVAILABLE'}}
byId('terms').addEventListener('change',()=>{consentDirty=true});byId('automatic').addEventListener('change',()=>{consentDirty=true;syncAutomatic()});
byId('save-consent').addEventListener('click',async()=>{try{await api('/api/consent',{method:'POST',body:JSON.stringify({terms_accepted:byId('terms').checked,automatic_mode:byId('automatic').checked})});consentDirty=false;show('consent-message','Agreement saved on this computer.');await refresh()}catch(e){show('consent-message',e.message,true)}});
byId('save-connection').addEventListener('click',async()=>{try{await api('/api/connection',{method:'POST',body:JSON.stringify({tunnel_id:byId('tunnel-id').value,runtime_key:byId('runtime-key').value})});byId('runtime-key').value='';show('connection-message','Private connection saved. MemorySafe is starting…');setTimeout(refresh,1200)}catch(e){show('connection-message',e.message,true)}});
byId('refresh').addEventListener('click',refresh);refresh();setInterval(refresh,3500);
// The ChatGPT tunnel is set up by the macOS installer only; anywhere else those two steps
// could never complete, and showed "DESKTOP CONNECTOR OFFLINE" for good.
byId('chatgpt-steps').hidden=!__CHATGPT_AVAILABLE__;
// Where a tester on Windows went looking for how to add Codex. Text only, never markup:
// a next step carries a URL.
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=String(text);return el}
function renderAgents(agents){const list=byId('agent-list');list.replaceChildren();const present=agents.filter(a=>a.present);const connected=present.filter(a=>a.connected).length;const summary=byId('agents-summary');summary.textContent=present.length?`${connected} OF ${present.length} CONNECTED`:'NONE FOUND YET';summary.className=present.length&&connected===present.length?'online':'offline';byId('assistants-step').classList.toggle('done',present.length>0&&connected===present.length);if(!present.length){list.append(node('small','','No assistants found on this computer yet.'))}for(const agent of present){const row=node('div','agent');const copy=node('div');copy.append(node('strong','',agent.label));copy.append(node('small','',agent.connected?`Connected through its ${agent.how}.`:agent.can_connect?'Installed here. Not connected yet.':String(agent.next_step??'')));row.append(copy);if(agent.connected){row.append(node('span','state on','CONNECTED'))}else if(agent.can_connect){const button=node('button','','Connect');button.type='button';button.addEventListener('click',()=>connectAgent(agent,button));row.append(button)}else{row.append(node('span','state off','ONE STEP LEFT'))}list.append(row)}}
async function loadAgents(){try{renderAgents((await api('/api/agents')).agents||[])}catch(e){byId('agents-summary').textContent='UNAVAILABLE'}}
async function connectAgent(agent,button){button.disabled=true;button.textContent='Connecting…';show('agents-message',`Installing MemorySafe in ${agent.label}. This can take a minute.`);try{const payload=await api('/api/agents/connect',{method:'POST',body:JSON.stringify({agent:agent.id})});show('agents-message',String(payload.result?.message??''),!payload.ok);renderAgents(payload.agents||[])}catch(e){show('agents-message',e.message,true);button.disabled=false;button.textContent='Connect'}}
loadAgents();
</script></body></html>"""


LEGAL_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>body{{margin:0;background:#f5f7fa;color:#17202a;font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{width:min(780px,calc(100% - 40px));margin:32px auto;background:#fff;padding:42px;border:1px solid #dfe6ee;border-radius:16px}}h1{{font-size:30px}}h2{{margin-top:34px;color:#2e74b5}}h3{{color:#1f4d78}}code{{background:#eef2f6;padding:2px 5px;border-radius:4px}}li{{margin:7px 0}}a{{color:#2e74b5}}@media(max-width:600px){{main{{padding:24px;margin:16px auto}}}}</style></head><body><main>{body}</main></body></html>"""


class SetupHandler(BaseHTTPRequestHandler):
    paths = SetupPaths.from_environment()
    setup_token = secrets.token_urlsafe(24)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _send(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def _loopback_request(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
        return host in {"127.0.0.1", "localhost", "::1"}

    def _authorized_post(self) -> bool:
        token = self.headers.get("X-MemorySafe-Setup-Token", "")
        return self._loopback_request() and secrets.compare_digest(token, self.setup_token)

    def _read_json(self) -> dict[str, Any]:
        length = min(int(self.headers.get("Content-Length", "0")), 16_384)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("The setup request was incomplete.") from None
        if not isinstance(payload, dict):
            raise ValueError("The setup request was incomplete.")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            token = json.dumps(self.setup_token)
            body = (
                SETUP_PAGE.replace("__SETUP_TOKEN__", token)
                .replace("__CHATGPT_AVAILABLE__", json.dumps(chatgpt_tunnel_installed()))
                .replace("__VERSION__", html.escape(VERSION))
                .encode("utf-8")
            )
            self._send(body, "text/html; charset=utf-8")
            return
        if path == "/dashboard":
            if not self._loopback_request():
                self._json({"error": "The dashboard is available only on this computer."}, 403)
                return
            body = dashboard_html(local_api_token=self.setup_token).encode("utf-8")
            self._send(body, "text/html; charset=utf-8")
            return
        if path == "/panel":
            if not self._loopback_request():
                self._json({"error": "The dashboard is available only on this computer."}, 403)
                return
            body = panel_html(local_api_token=self.setup_token).encode("utf-8")
            self._send(body, "text/html; charset=utf-8")
            return
        if path == "/api/dashboard":
            if not self._loopback_request():
                self._json({"error": "The dashboard is available only on this computer."}, 403)
                return
            self._json(dashboard_payload(self.paths))
            return
        if path == "/api/status":
            self._json(status_payload(self.paths))
            return
        if path == "/api/agents":
            # Which assistants are installed says something about this person; like the
            # dashboard, it is answered only on this computer.
            if not self._loopback_request():
                self._json({"error": "The dashboard is available only on this computer."}, 403)
                return
            self._json(
                {
                    "agents": agents_module.inventory(),
                    "auto_connect": agents_module.read_auto_connect(self.paths.state_dir),
                }
            )
            return
        if path == "/api/doctor":
            if not self._loopback_request():
                self._json({"error": "Diagnostics are available only on this computer."}, 403)
                return
            self._json(run_doctor(self.paths.install_root))
            return
        if path == "/open-chatgpt":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", self.paths.connect_url)
            self._security_headers()
            self.end_headers()
            return
        legal_files = {
            "/legal/terms": ("MemorySafe Beta Terms of Use", "MemorySafe_Beta_Terms_of_Use.md"),
            "/legal/privacy": ("MemorySafe Beta Privacy Policy", "MemorySafe_Beta_Privacy_Policy.md"),
        }
        if path in legal_files:
            title, filename = legal_files[path]
            source = _read_text(self.paths.legal_dir / filename)
            if not source:
                self._send(b"Legal document not installed.", "text/plain; charset=utf-8", 404)
                return
            page = LEGAL_PAGE.format(title=html.escape(title), body=markdown_to_html(source))
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._json({"error": "Not found."}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._authorized_post():
            self._json({"error": "The local setup session expired. Refresh the page."}, 403)
            return
        try:
            payload = self._read_json()
            if path == "/api/consent":
                save_consent(
                    self.paths,
                    bool(payload.get("terms_accepted")),
                    bool(payload.get("automatic_mode")),
                )
            elif path == "/api/connection":
                save_connection(
                    self.paths,
                    str(payload.get("runtime_key", "")),
                    str(payload.get("tunnel_id", "")),
                )
            elif path == "/api/automatic-mode":
                set_automatic_mode(self.paths, bool(payload.get("enabled")))
            elif path == "/api/forget":
                memory_id = str(payload.get("memory_id", "")).strip()
                if not memory_id:
                    self._json({"error": "A memory id is required."}, 400)
                    return
                result = forget_memory(self.paths, memory_id)
                self._json({"ok": True, "result": result, "dashboard": dashboard_payload(self.paths)})
                return
            elif path == "/api/support-bundle":
                self._json({"ok": True, **support_bundle_payload(self.paths, str(payload.get("description", "")))})
                return
            elif path == "/api/support-bundle/download":
                # "Report a problem" wrote the ZIP under a hidden AppData folder and said
                # so at the foot of the page; a tester clicked it and saw nothing. The page
                # now fetches it from here and the browser saves it to Downloads.
                bundle = find_support_bundle(self.paths.install_root, str(payload.get("name", "")))
                if bundle is None:
                    self._json({"error": "That support bundle was not found."}, 404)
                    return
                data = bundle.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{bundle.name}"')
                self._security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            elif path == "/api/agents/connect":
                # Runs an assistant's own plugin installer. The token check above is what
                # stops another website from triggering it: only this dashboard's page can
                # read the token. The agent id is checked against a fixed list, and nothing
                # from the request reaches the command line.
                agent_id = str(payload.get("agent", ""))
                if agent_id not in {"claude_code", "codex", "claude_desktop"}:
                    self._json({"error": "Unknown assistant."}, 400)
                    return
                result = agents_module.connect(agent_id)
                self._json(
                    {
                        "ok": result["ok"],
                        "result": result,
                        "agents": agents_module.inventory(),
                        "auto_connect": agents_module.read_auto_connect(self.paths.state_dir),
                    }
                )
                return
            elif path == "/api/agents/decision":
                # The one-time "connect your other assistants too?" answer. Yes connects
                # them now and is remembered, so assistants installed later are connected
                # when this service next starts; no is remembered so it is never asked again.
                enabled = payload.get("auto_connect")
                if not isinstance(enabled, bool):
                    self._json({"error": "Answer yes or no."}, 400)
                    return
                agents_module.write_auto_connect(self.paths.state_dir, enabled)
                results = agents_module.connect_all(state_dir=self.paths.state_dir) if enabled else []
                self._json(
                    {
                        "ok": all(result["ok"] for result in results),
                        "results": results,
                        "agents": agents_module.inventory(),
                        "auto_connect": enabled,
                    }
                )
                return
            else:
                self._json({"error": "Not found."}, 404)
                return
        except (ValueError, OSError) as error:
            self._json({"error": str(error)}, 400)
            return
        self._json({"ok": True, "status": status_payload(self.paths)})


def _warm_token_metrics() -> None:
    """Pay the token-measurement cost at startup, not inside someone's first request.

    Measuring the fixed overhead imports the MCP server, pydantic and tiktoken and runs
    an event loop to list the tools. Done lazily, the first dashboard load carried all
    of it — 1.8 seconds warm, far worse on a cold process. The result is cached, so
    doing it once here makes every request fast.
    """

    def warm() -> None:
        try:
            from .token_metrics import fixed_overhead_tokens

            fixed_overhead_tokens()
        except Exception:
            pass  # a slow dashboard is better than a service that will not start

    threading.Thread(target=warm, name="memorysafe-warm", daemon=True).start()


# The launchd job scripts/install_macos.py creates for the ChatGPT tunnel (its TUNNEL_LABEL).
_TUNNEL_AGENT = Path("Library") / "LaunchAgents" / "ca.memorysafe.beta.tunnel.plist"


def chatgpt_tunnel_installed(home: Path | None = None) -> bool:
    """Whether the ChatGPT tunnel the Setup page's optional steps configure exists here.

    Only the macOS installer creates it. A Mac with just the plugin has none, and would get
    the same permanent "DESKTOP CONNECTOR OFFLINE" that Setup showed on Windows.
    """

    return sys.platform == "darwin" and ((home or Path.home()) / _TUNNEL_AGENT).is_file()


def _auto_connect_on_start(paths: SetupPaths) -> threading.Thread:
    """Connect assistants installed since the user said yes, without holding up the dashboard.

    This service is the one singleton every host's launcher starts (port 8765 admits one),
    so it is the one place where connecting cannot race another copy of itself -- once it
    holds the port, which is why main() starts this only after the bind. Two hosts starting
    together each see the port free and each spawn a copy; the loser's bind fails, and it
    must not have started an installer by then. Before the user has answered yes,
    auto_connect_on_start does nothing at all.
    """

    def run() -> None:
        try:
            agents_module.auto_connect_on_start(paths.state_dir)
        except Exception:
            pass  # an installer that fails must not take the dashboard down with it

    thread = threading.Thread(target=run, name="memorysafe-auto-connect", daemon=True)
    thread.start()
    return thread


def _snapshot_on_start(paths: SetupPaths) -> None:
    """One consistent copy each time the service starts.

    Corruption ended every operation with "database disk image is malformed" and there
    was nothing to fall back to. A snapshot per launch is cheap and turns total loss
    into losing whatever happened since the last restart.
    """

    try:
        MemoryStore(paths.database_path).snapshot()
    except Exception:
        pass  # a backup that prevents startup would be worse than no backup


def main() -> None:
    port = int(os.environ.get("MEMORYSAFE_SETUP_PORT", str(DEFAULT_PORT)))
    SetupHandler.paths = SetupPaths.from_environment()
    ensure_device_identity(SetupHandler.paths.state_dir)
    _snapshot_on_start(SetupHandler.paths)
    _warm_token_metrics()
    with ThreadingHTTPServer((HOST, port), SetupHandler) as server:
        _auto_connect_on_start(SetupHandler.paths)
        resolved_port = server.server_address[1]
        print(f"READY http://{HOST}:{resolved_port}/", flush=True)
        server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
