from __future__ import annotations

import json


DASHBOARD_URI = "ui://memorysafe/dashboard-v3.html"
DASHBOARD_MIME_TYPE = "text/html;profile=mcp-app"


def dashboard_html(local_api_token: str | None = None) -> str:
    """Return the self-contained MemorySafe dashboard component."""

    document = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <style>
    :root {
      --bg: #05080d;
      --surface: #0b111b;
      --surface-2: #101824;
      --border: rgba(190, 218, 245, 0.13);
      --text: #f4f8fb;
      --muted: #8291a5;
      --dim: #536276;
      --cyan: #19e4e9;
      --blue: #4b83ff;
      --green: #52dc88;
      --pink: #ff4c85;
      --amber: #f4b75e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 0;
      background:
        radial-gradient(circle at 86% 0%, rgba(25, 228, 233, .10), transparent 260px),
        var(--bg);
      color: var(--text);
      font: 13px/1.45 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button { font: inherit; }
    .shell { padding: 18px; }
    .topline { display: flex; align-items: center; gap: 11px; }
    .mark {
      width: 38px; height: 38px; padding: 7px; display: grid; flex: 0 0 38px;
      grid-template-columns: 1fr 1fr; gap: 4px; border-radius: 10px;
      background: #07111a; border: 1px solid rgba(25, 228, 233, .42);
      box-shadow: 0 0 22px rgba(25, 228, 233, .12);
    }
    .mark i { display: block; border-radius: 3px; }
    .mark i:nth-child(1), .mark i:nth-child(4) { background: var(--cyan); }
    .mark i:nth-child(2), .mark i:nth-child(3) { background: var(--blue); }
    .brand { min-width: 0; }
    .brand strong { display: block; font-size: 17px; letter-spacing: -.35px; }
    .brand span { display: block; margin-top: 1px; color: var(--muted); font-size: 10px; }
    .live {
      margin-left: auto; display: flex; align-items: center; gap: 6px;
      color: #a6d9b8; font-size: 9px; font-weight: 700; letter-spacing: .08em;
    }
    .live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }
    .refresh, .setup-link, .support-bundle {
      border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.025);
      color: var(--muted); padding: 7px 9px; cursor: pointer;
    }
    .setup-link, .support-bundle { display: none; text-decoration: none; }
    .refresh:hover, .setup-link:hover, .support-bundle:hover { border-color: rgba(25, 228, 233, .38); color: var(--text); }
    .refresh:disabled { opacity: .45; cursor: wait; }
    .support-result { display: none; margin-top: 10px; padding: 10px 12px; border: 1px solid rgba(82,220,136,.18); border-radius: 9px; background: rgba(82,220,136,.05); color: #9fcdb0; font-size: 9px; overflow-wrap: anywhere; }
    .hero {
      margin-top: 17px; padding: 17px; display: grid; grid-template-columns: 1fr auto;
      gap: 20px; align-items: center; border: 1px solid var(--border); border-radius: 14px;
      background: linear-gradient(145deg, rgba(25,228,233,.07), rgba(75,131,255,.025) 48%, var(--surface));
    }
    .eyebrow { color: var(--cyan); font: 700 9px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .13em; }
    h1 { margin: 7px 0 5px; font-size: 22px; line-height: 1.1; letter-spacing: -.7px; }
    .hero p { margin: 0; color: var(--muted); font-size: 11px; max-width: 480px; }
    .auto-mode {
      margin-top: 13px; padding: 10px 11px; display: flex; align-items: center; gap: 12px;
      max-width: 520px; border: 1px solid rgba(75,131,255,.2); border-radius: 10px;
      background: rgba(75,131,255,.055);
    }
    .auto-copy { min-width: 0; flex: 1; }
    .auto-copy strong { display: block; font-size: 10px; }
    .auto-copy span { display: block; margin-top: 2px; color: var(--muted); font-size: 8px; }
    .auto-copy small { display: block; margin-top: 5px; color: var(--dim); font-size: 8px; line-height: 1.35; }
    /* Liveness sits next to the score on purpose. The score cannot fall when capture
       stops, so a stale store otherwise reads as a healthy one. */
    .capture-freshness[hidden] { display: none; }
    .capture-freshness {
      margin-top: 6px; padding: 3px 7px; border-radius: 999px; width: fit-content;
      font: 800 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .04em;
      border: 1px solid transparent;
    }
    .capture-freshness.active { color: var(--green); border-color: rgba(82,220,136,.4); background: rgba(82,220,136,.1); }
    .capture-freshness.quiet  { color: var(--amber); border-color: rgba(244,183,94,.4); background: rgba(244,183,94,.1); }
    .capture-freshness.stale,
    .capture-freshness.never  { color: var(--pink); border-color: rgba(255,76,133,.45); background: rgba(255,76,133,.12); }
    .capture-freshness.unknown { color: var(--dim); border-color: var(--border); }
    .auto-counts { color: var(--dim); font: 700 8px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
    .auto-toggle {
      min-width: 50px; padding: 7px 9px; border: 1px solid rgba(130,145,165,.3); border-radius: 999px;
      background: rgba(255,255,255,.025); color: var(--muted); cursor: pointer;
      font: 800 9px ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .auto-toggle.on { border-color: rgba(82,220,136,.45); background: rgba(82,220,136,.1); color: var(--green); }
    .auto-toggle:disabled { opacity: .45; cursor: wait; }
    .score {
      --score: 0; width: 92px; height: 92px; display: grid; place-items: center;
      border-radius: 50%; position: relative; box-shadow: 0 0 24px rgba(25,228,233,.11);
      /* A visible track matters more than the arc: every new store sits near zero, and
         a 10% arc on a .07 track just reads as an empty hole in the layout. */
      background: conic-gradient(var(--cyan) calc(var(--score) * 1%), rgba(190,218,245,.18) 0);
    }
    .score::before { content: ""; position: absolute; inset: 7px; border-radius: inherit; background: #09101a; }
    .score-value { position: relative; text-align: center; }
    .score-value strong { display: block; font: 800 26px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .score-value span { display: block; margin-top: 4px; color: var(--muted); font-size: 7px; letter-spacing: .06em; line-height: 1.3; max-width: 62px; }
    .metrics { margin-top: 10px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .metric { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface); }
    .metric span { display: block; color: var(--muted); font-size: 9px; }
    .metric strong { display: block; margin: 5px 0 2px; font: 800 19px/1.05 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .metric small { color: var(--dim); font-size: 8px; }
    .metric-cyan strong { color: var(--cyan); }
    .metric-blue strong { color: #82a7ff; }
    .metric-green strong { color: var(--green); }
    .content-grid { margin-top: 10px; display: grid; grid-template-columns: .9fr 1.1fr; gap: 10px; }
    .panel { padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); min-width: 0; }
    .panel-title { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 11px; }
    .panel-title strong { font-size: 12px; }
    .panel-title span { color: var(--dim); font-size: 8px; }
    .compare { display: grid; grid-template-columns: 1fr 18px 1fr; align-items: stretch; gap: 7px; }
    .compare-card { padding: 12px; border-radius: 10px; background: var(--surface-2); border: 1px solid rgba(190,218,245,.08); }
    .compare-card.with { border-color: rgba(25,228,233,.22); background: rgba(25,228,233,.055); }
    .compare-card span { color: var(--muted); font-size: 8px; }
    .compare-card strong { display: block; margin-top: 6px; font: 800 21px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .compare-card small { display: block; margin-top: 5px; color: var(--dim); font-size: 8px; }
    .compare-card.with strong { color: var(--cyan); }
    .arrow { display: grid; place-items: center; color: var(--cyan); font-size: 15px; }
    .savings { margin-top: 9px; display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .saving { padding: 9px; border-radius: 9px; background: rgba(82,220,136,.045); border: 1px solid rgba(82,220,136,.1); }
    .saving strong { display: block; color: var(--green); font: 800 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .saving span { color: #70897a; font-size: 8px; }
    .memory-list { display: grid; gap: 7px; }
    .memory { display: grid; grid-template-columns: 8px 1fr auto; gap: 9px; align-items: start; padding: 9px 10px; border-radius: 9px; background: var(--surface-2); }
    .memory-dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--blue); }
    .memory.protected .memory-dot { background: var(--cyan); box-shadow: 0 0 7px rgba(25,228,233,.55); }
    .memory-copy { min-width: 0; }
    .memory-copy p { margin: 0; color: #dce5ed; font-size: 10px; overflow-wrap: anywhere; }
    .memory-copy span { display: block; margin-top: 4px; color: var(--dim); font-size: 8px; }
    .priority { color: var(--muted); font: 700 9px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .store-path { margin: 9px 0 0; color: var(--dim); font-size: 8px; }
    .store-path code { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .memory-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
    .memory-forget { border: 1px solid rgba(190,218,245,.18); background: transparent; color: var(--dim);
      font: 600 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase;
      padding: 3px 7px; border-radius: 5px; cursor: pointer; }
    .memory-forget:hover { color: var(--pink); border-color: rgba(255,76,133,.5); }
    .memory-forget.confirm { color: var(--bg); background: var(--pink); border-color: var(--pink); }
    .memory-forget:disabled { opacity: .5; cursor: default; }
    .memory-forget:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
    .empty { padding: 19px 10px; text-align: center; color: var(--muted); font-size: 10px; border: 1px dashed var(--border); border-radius: 9px; }
    .token-panel { margin-top: 10px; background: linear-gradient(145deg, rgba(75,131,255,.07), rgba(25,228,233,.025) 62%, var(--surface)); }
    .token-badge { color: #8eabef !important; font: 700 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .token-live-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .token-live-stat { padding: 11px 12px; border: 1px solid rgba(25,228,233,.15); border-radius: 10px; background: rgba(25,228,233,.04); min-width: 0; }
    .token-live-stat span { display: block; color: var(--muted); font-size: 8px; }
    .token-live-stat strong { display: block; margin: 6px 0 3px; color: var(--cyan); font: 800 18px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-live-stat small { color: var(--dim); font-size: 7px; }
    .gov-item { padding: 11px 1px; border-bottom: 1px solid rgba(142,171,239,.10); }
    .gov-item:last-child { border-bottom: 0; }
    .gov-head { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; flex-wrap: wrap; }
    .gov-tag { font: 700 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; padding: 3px 7px; border-radius: 4px; }
    .gov-supersede { background: rgba(255,176,84,.15); color: #ffb054; }
    .gov-restore { background: rgba(94,234,212,.15); color: #5eead4; }
    .gov-review { background: rgba(142,171,239,.15); color: #8eabef; }
    .gov-when { color: #6b7f9e; font: 500 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .gov-reason { color: #c8d6f0; font-size: 12px; line-height: 1.45; margin-bottom: 8px; }
    .gov-pair { display: grid; gap: 5px; }
    .gov-line { display: grid; grid-template-columns: 62px 1fr; gap: 9px; align-items: baseline; font-size: 11.5px; line-height: 1.4; }
    .gov-label { font: 700 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .07em; color: #6b7f9e; padding-top: 2px; }
    .gov-out { color: #7d8ba3; text-decoration: line-through; text-decoration-color: rgba(125,139,163,.45); }
    .gov-in { color: #dbe6fb; }
    .token-section-label { display: flex; align-items: center; gap: 9px; margin: 12px 1px 8px; color: #8eabef; font: 700 8px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .token-section-label::after { content: ""; height: 1px; flex: 1; background: rgba(142,171,239,.13); }
    .token-grid { display: grid; grid-template-columns: .72fr .72fr 1.28fr 1.28fr; gap: 8px; }
    .token-stat, .token-saving { padding: 12px; border: 1px solid rgba(190,218,245,.09); border-radius: 10px; background: rgba(5,8,13,.42); min-width: 0; }
    .token-stat span, .token-saving span { display: block; color: var(--muted); font-size: 8px; }
    .token-stat strong { display: block; margin: 6px 0 3px; color: #a9bdff; font: 800 19px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-stat small { color: var(--dim); font-size: 7px; }
    .token-saving-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
    .token-saving-head strong { color: var(--green); font: 800 15px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-bar { height: 5px; margin-top: 10px; overflow: hidden; border-radius: 999px; background: rgba(255,255,255,.07); }
    .token-bar i { display: block; width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--blue), var(--cyan)); box-shadow: 0 0 9px rgba(25,228,233,.3); transition: width .35s ease; }
    .token-note { margin: 9px 1px 0; color: var(--dim); font-size: 8px; }
    .token-note strong { color: var(--amber); }
    .formula { margin-top: 10px; padding: 10px 12px; display: flex; gap: 9px; align-items: flex-start; border: 1px solid rgba(244,183,94,.11); border-radius: 10px; background: rgba(244,183,94,.035); color: #9b8a72; font-size: 8px; }
    .formula strong { flex: 0 0 auto; color: var(--amber); }
    .error { margin-top: 12px; padding: 10px 12px; border-radius: 9px; background: rgba(255,76,133,.07); color: #f1a3bb; display: none; }
    @media (max-width: 620px) {
      .shell { padding: 12px; }
      .topline { flex-wrap: wrap; }
      .brand { flex: 1; }
      .live { display: none; }
      .hero { grid-template-columns: 1fr; gap: 14px; padding: 14px; }
      .auto-mode { flex-wrap: wrap; gap: 8px; }
      .auto-copy { flex: 1 0 100%; }
      .auto-counts { margin-right: auto; }
      .score { width: 84px; height: 84px; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .content-grid { grid-template-columns: 1fr; }
      .token-live-grid { grid-template-columns: 1fr 1fr; }
      .token-grid { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 380px) {
      .brand span { display: none; }
      h1 { font-size: 20px; }
      .metrics { grid-template-columns: 1fr; }
      .compare { grid-template-columns: 1fr; }
      .arrow { transform: rotate(90deg); min-height: 18px; }
      .savings { grid-template-columns: 1fr; }
      .token-live-grid { grid-template-columns: 1fr; }
      .token-grid { grid-template-columns: 1fr; }
    }
        details.tech { margin-top: 18px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px; }
      details.tech summary { cursor: pointer; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; opacity: .6; }
      details.tech p { font-size: 12px; opacity: .65; line-height: 1.6; margin: 10px 0 0; }
    </style>
</head>
<body>
  <main class="shell">
    <header class="topline">
      <div class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="brand"><strong>MemorySafe</strong><span>Private local memory governance</span></div>
      <div class="live">LOCAL · PRIVATE</div>
      <a class="setup-link" id="setup-link" href="/">Setup</a>
      <button class="support-bundle" id="support-bundle" type="button">Report a problem</button>
      <button class="refresh" id="refresh" type="button">Refresh</button>
    </header>

    <section class="hero">
      <div>
        <div class="eyebrow">MEMORYSAFE · LIVE</div>
        <h1>Modeled context per turn</h1>
        <p>Without MemorySafe, every stored fact is restated. With MemorySafe, only the facts actually recalled plus a fixed tool cost.</p>
        <div class="auto-mode">
          <div class="auto-copy">
            <strong>Automatic capture</strong>
            <span>Saves concise, durable, non-sensitive facts as you work.</span>
            <small id="auto-status">Waiting for capture diagnostics…</small>
            <small class="capture-freshness" id="capture-freshness" hidden></small>
          </div>
          <span class="auto-counts" id="auto-counts">0 SAVED · 0 SKIPPED</span>
          <button class="auto-toggle" id="auto-toggle" type="button">OFF</button>
        </div>
      </div>
      <div class="score" id="score-ring">
        <div class="score-value">
          <strong id="tokens-saved-hero">—</strong>
          <span id="tokens-saved-label">ESTIMATED TOKENS SAVED / TURN</span>
        </div>
      </div>
    </section>
    <section class="panel token-panel" aria-label="Tokens with and without MemorySafe">
      <div class="panel-title"><strong>With vs without MemorySafe</strong><span class="token-badge">THIS STORE · THIS TURN</span></div>
      <div class="compare">
        <div class="compare-card">
          <span>Without MemorySafe</span>
          <strong id="tokens-without">—</strong>
          <small id="tokens-without-note">restate every stored fact</small>
        </div>
        <div class="arrow" aria-hidden="true">→</div>
        <div class="compare-card with">
          <span>With MemorySafe</span>
          <strong id="tokens-with">—</strong>
          <small id="tokens-with-note">overhead + recalled facts</small>
        </div>
      </div>
      <div class="savings">
        <div class="saving">
          <strong id="tokens-saved">—</strong>
          <span>tokens saved each turn</span>
        </div>
        <div class="saving">
          <strong id="tokens-saved-pct">—</strong>
          <span>less context than restating everything</span>
        </div>
      </div>
      <p class="token-note" id="token-model">Input tokens on this Mac. Not ChatGPT billed usage.</p>
    </section>
    <section class="metrics" aria-label="What MemorySafe gave back">
      <div class="metric metric-green"><span>Memory searches</span><strong id="recall-count">—</strong><small>find calls recorded by MemorySafe</small></div>
      <div class="metric metric-cyan"><span>Memories used</span><strong id="recall-used">—</strong><small id="recall-used-note">of those stored</small></div>
      <div class="metric metric-blue"><span>Never used</span><strong id="recall-unused">—</strong><small>stored, never recalled</small></div>
      <div class="metric"><span>Active memories</span><strong id="active">—</strong><small id="protected-note">available for recall</small></div>
    </section>
    <section class="content-grid">
      <div class="panel">
        <div class="panel-title"><strong>Recent memories</strong><span id="memory-count">0 MEMORIES</span></div>
        <div class="memory-list" id="memories"><div class="empty">No memories stored yet.</div></div>
      </div>
      <div class="panel">
        <div class="panel-title"><strong>Most used</strong><span>BY RECALL</span></div>
        <div class="memory-list" id="most-used"><div class="empty">Nothing has been recalled yet.</div></div>
      </div>
    </section>
    <section class="panel" aria-label="Governance trail" id="governance-panel" hidden>
      <div class="panel-title"><strong>Governance trail</strong><span id="governance-note">EVERY DECISION, WITH ITS REASON</span></div>
      <div class="memory-list" id="governance"></div>
    </section>
    <details class="tech">
      <summary>Technical detail</summary>
      <p id="tech-dupes">—</p>
      <p id="tech-health">—</p>
      <p id="tech-breakeven">—</p>
      <p id="tech-hypothetical">—</p>
      <p class="store-path">Reading <code id="database-path">—</code></p>
    </details>
    <div class="support-result" id="support-result"></div>
    <div class="error" id="error">The dashboard could not refresh. Your stored memories were not changed.</div>
  </main>

  <script>
    const localApiToken = __LOCAL_API_TOKEN__;
    const standalone = window.parent === window && Boolean(localApiToken);
    const pendingRequests = new Map();
    let nextRequestId = 1;
    let automaticModeEnabled = false;
    const byId = (id) => document.getElementById(id);
    const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
    const percentage = (value) => `${Math.round(number(value) * 100)}%`;
    const bytes = (value) => {
      const amount = number(value);
      if (amount < 1024) return `${amount} B`;
      if (amount < 1024 * 1024) return `${(amount / 1024).toFixed(1)} KB`;
      return `${(amount / (1024 * 1024)).toFixed(1)} MB`;
    };
    const unwrap = (payload) => payload?.structuredContent ?? payload?.result?.structuredContent ?? payload ?? {};

    function request(method, params) {
      if (standalone && method === "tools/call") {
        const toolName = params?.name;
        if (toolName === "memorysafe_health" || toolName === "memorysafe_dashboard") {
          return fetch("/api/dashboard", { cache: "no-store" }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload?.error ?? "Dashboard unavailable");
            return payload;
          });
        }
        if (toolName === "memorysafe_set_auto_mode") {
          return fetch("/api/automatic-mode", {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "X-MemorySafe-Setup-Token": localApiToken,
            },
            body: JSON.stringify({ enabled: Boolean(params?.arguments?.enabled) }),
          }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload?.error ?? "Automatic mode could not be changed");
            return payload;
          });
        }
        if (toolName === "memorysafe_forget") {
          return fetch("/api/forget", {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "X-MemorySafe-Setup-Token": localApiToken,
            },
            body: JSON.stringify({ memory_id: String(params?.arguments?.memory_id ?? "") }),
          }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload?.error ?? "That memory could not be forgotten");
            return payload;
          });
        }
        if (toolName === "memorysafe_support_bundle") {
          return fetch("/api/support-bundle", {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "X-MemorySafe-Setup-Token": localApiToken,
            },
            body: "{}",
          }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload?.error ?? "Support bundle could not be created");
            return payload;
          });
        }
        return Promise.reject(new Error("Unsupported local dashboard action"));
      }
      const id = nextRequestId++;
      window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
      return new Promise((resolve, reject) => pendingRequests.set(id, { resolve, reject }));
    }

    function setText(id, value) { byId(id).textContent = String(value); }

    function renderCaptureFreshness(data) {
      // An older connector will not send these fields. Stay hidden rather than
      // inventing a reassuring "active" that was never measured.
      const node = byId("capture-freshness");
      if (!node) return;
      const state = String(data.capture_freshness ?? "");
      if (!["active", "quiet", "stale", "never", "unknown"].includes(state)) {
        node.hidden = true;
        return;
      }
      const label =
        state === "never" ? "NEVER CAPTURED"
        : state === "unknown" ? "CAPTURE AGE UNKNOWN"
        : state === "active" ? "CAPTURING"
        : `LAST CAPTURE ${number(data.days_since_last_capture)}D AGO`;
      node.className = "capture-freshness " + state;
      node.textContent = label;
      node.title = String(data.capture_status ?? "");
      node.hidden = false;
    }

    function renderMemories(items) {
      const list = byId("memories");
      list.replaceChildren();
      const memories = Array.isArray(items) ? items : [];
      setText("memory-count", `${memories.length} ${memories.length === 1 ? "MEMORY" : "MEMORIES"}`);
      if (!memories.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No memories stored yet. Ask your assistant to remember something useful.";
        list.appendChild(empty);
        return;
      }
      for (const item of memories.slice(0, 6)) {
        const row = document.createElement("div");
        row.className = `memory${item?.protected ? " protected" : ""}`;
        const dot = document.createElement("span");
        dot.className = "memory-dot";
        const copy = document.createElement("div");
        copy.className = "memory-copy";
        const content = document.createElement("p");
        content.textContent = String(item?.content ?? "Memory");
        const meta = document.createElement("span");
        meta.textContent = `${String(item?.category ?? "other")} · ${item?.protected ? "Protected" : "Stored"}`;
        const priority = document.createElement("span");
        priority.className = "priority";
        priority.textContent = percentage(item?.importance);
        const actions = document.createElement("div");
        actions.className = "memory-actions";
        const forget = document.createElement("button");
        forget.type = "button";
        forget.className = "memory-forget";
        forget.textContent = "Forget";
        forget.setAttribute("aria-label", `Forget this memory: ${String(item?.content ?? "")}`);
        let armed = false;
        let armedTimer = null;
        forget.addEventListener("click", async () => {
          // Forgetting cannot be undone, so the first click only arms the button.
          if (!armed) {
            armed = true;
            forget.classList.add("confirm");
            forget.textContent = "Confirm";
            armedTimer = setTimeout(() => {
              armed = false;
              forget.classList.remove("confirm");
              forget.textContent = "Forget";
            }, 4000);
            return;
          }
          clearTimeout(armedTimer);
          forget.disabled = true;
          forget.textContent = "…";
          try {
            await request("tools/call", {
              name: "memorysafe_forget",
              arguments: { memory_id: String(item?.memory_id ?? "") },
            });
            byId("refresh").click();
          } catch (error) {
            forget.disabled = false;
            forget.classList.remove("confirm");
            forget.textContent = "Retry";
            byId("error").textContent = "That memory could not be forgotten. Nothing was changed.";
            byId("error").style.display = "block";
          }
        });
        actions.append(priority, forget);
        copy.append(content, meta);
        row.append(dot, copy, actions);
        list.appendChild(row);
      }
    }

    // The one view no other memory product can draw: what was replaced, by what,
    // and on what evidence -- with the reason in the user's own language.
    function renderGovernance(events) {
      const panel = document.getElementById("governance-panel");
      const list = document.getElementById("governance");
      if (!panel || !list) return;
      const rows = Array.isArray(events) ? events : [];
      if (!rows.length) { panel.hidden = true; return; }
      panel.hidden = false;

      const tag = (decision, status) => {
        if (status === "open") return ["gov-review", "NEEDS A DECISION"];
        if (decision === "SUPERSEDE") return ["gov-supersede", "REPLACED"];
        if (decision === "RESTORE") return ["gov-restore", "RESTORED"];
        if (decision === "KEEP_BOTH") return ["gov-review", "BOTH KEPT"];
        return ["gov-review", String(decision || "REVIEWED")];
      };
      const when = (iso) => {
        const d = new Date(iso);
        return Number.isNaN(d.getTime())
          ? ""
          : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      };

      list.textContent = "";
      let shown = 0;
      for (const event of rows) {
        if (shown >= 5) break;
        const [cls, label] = tag(event.decision, event.status);
        const item = document.createElement("div");
        item.className = "gov-item";

        const head = document.createElement("div");
        head.className = "gov-head";
        const badge = document.createElement("span");
        badge.className = `gov-tag ${cls}`;
        badge.textContent = label;
        const stamp = document.createElement("span");
        stamp.className = "gov-when";
        stamp.textContent = when(event.created_at);
        head.append(badge, stamp);

        const reason = document.createElement("div");
        reason.className = "gov-reason";
        // A restored row still carries the reason it was replaced for, which reads
        // as a contradiction under a RESTORED badge. Say who reversed it first.
        reason.textContent = event.decision === "RESTORE"
          ? `Reversed by you. It had been replaced because: ${String(event.reason || "").replace(/^./, (c) => c.toLowerCase())}`
          : String(event.reason || "");

        const pair = document.createElement("div");
        pair.className = "gov-pair";
        const line = (labelText, text, cssClass) => {
          if (!text) return;
          const row = document.createElement("div");
          row.className = "gov-line";
          const key = document.createElement("span");
          key.className = "gov-label";
          key.textContent = labelText;
          const value = document.createElement("span");
          value.className = cssClass;
          value.textContent = text.length > 190 ? `${text.slice(0, 190)}\u2026` : text;
          row.append(key, value);
          pair.append(row);
        };
        line(event.decision === "SUPERSEDE" ? "REPLACED" : "EARLIER", event.replaced, "gov-out");
        line("NOW", event.kept, "gov-in");

        item.append(head, reason, pair);
        list.append(item);
        shown += 1;
      }
    }

    function render(payload) {
      const data = unwrap(payload);
      const comparison = data.comparison ?? {};
      const recall = data.recall ?? {};
      const liveTokens = data.live_token_metrics ?? {};
      const tokenBenchmark = data.token_benchmark ?? {};

      // Recall leads, because recall is the benefit. Everything a user wants to know
      // is "did this save me anything", and that is the only number that answers it.
      const stored = number(data.active_memories);
      const used = number(recall.memories_ever_recalled);
      setText("recall-count", number(recall.times_memory_was_consulted));
      setText("recall-used", used);
      setText("recall-used-note", `of ${stored} stored`);
      setText("recall-unused", number(recall.memories_never_recalled));
      setText("active", stored);
      setText("protected-note", `${number(data.protected_memories)} protected`);

      const compare = tokenBenchmark.live_compare ?? {};
      const withoutTokens = number(compare.without_memorysafe_tokens);
      const withTokens = number(compare.with_memorysafe_tokens);
      const savedTokens = number(compare.tokens_saved_per_turn);
      const extraTokens = number(compare.tokens_extra_per_turn);
      const payingOff = Boolean(compare.paying_off);
      const pctSaved = number(compare.percent_saved);
      const recalled = number(compare.facts_recalled_per_turn) || 5;
      setText("tokens-without", withoutTokens.toLocaleString());
      setText("tokens-with", withTokens.toLocaleString());
      setText(
        "tokens-without-note",
        `restate all ${number(compare.facts_stored) || stored} facts`,
      );
      setText(
        "tokens-with-note",
        `tools + ${recalled} recalled facts`,
      );
      if (payingOff) {
        setText("tokens-saved", savedTokens.toLocaleString());
        setText("tokens-saved-pct", `${Math.round(pctSaved)}% less`);
        setText("tokens-saved-hero", savedTokens.toLocaleString());
        setText("tokens-saved-label", "ESTIMATED TOKENS SAVED / TURN");
        byId("score-ring").style.setProperty("--score", Math.max(0, Math.min(100, pctSaved)));
      } else {
        setText("tokens-saved", "0");
        setText("tokens-saved-pct", extraTokens ? `${extraTokens.toLocaleString()} extra for now` : "not yet paying off");
        setText("tokens-saved-hero", extraTokens ? `+${extraTokens.toLocaleString()}` : "0");
        setText("tokens-saved-label", extraTokens ? "EXTRA TOKENS / TURN" : "NOT YET PAYING OFF");
        byId("score-ring").style.setProperty("--score", 0);
      }
      setText("token-model", "Input tokens on this Mac. Not ChatGPT billed usage.");

      const breakEven = number(tokenBenchmark.break_even_facts);
      setText(
        "tech-breakeven",
        `Break-even at ${breakEven} stored facts. Overhead ${number(tokenBenchmark.fixed_overhead_tokens).toLocaleString()} tokens. Average ${number(compare.average_fact_tokens || liveTokens.average_memory_tokens)} tokens per fact.`,
      );
      setText(
        "tech-hypothetical",
        `If this store had 80 facts: ${Math.round(number(tokenBenchmark.savings_at_80_facts))}% less context. At 160 facts: ${Math.round(number(tokenBenchmark.savings_at_160_facts))}% less.`,
      );
      setText(
        "tech-dupes",
        `${number(comparison.duplicate_copies_avoided)} confirmed duplicate merges across `
        + `${number(comparison.raw_remember_requests)} remember requests `
        + `(${bytes(comparison.content_bytes_avoided)} of content).`,
      );
      setText(
        "tech-health",
        `Health ${number(data.memory_health)} — ${String(data.formula ?? "")} `
        + "This rates how tidy the store is; it says nothing about whether memories are used.",
      );
      setText("database-path", String(data.database_path ?? "unknown store"));

      if (typeof data.automatic_mode === "boolean") {
        automaticModeEnabled = data.automatic_mode;
      }
      const autoToggle = byId("auto-toggle");
      autoToggle.textContent = automaticModeEnabled ? "ON" : "OFF";
      autoToggle.classList.toggle("on", automaticModeEnabled);
      autoToggle.setAttribute("aria-pressed", String(automaticModeEnabled));
      if (data.automatic_captures !== undefined || data.automatic_skips !== undefined) {
        setText(
          "auto-counts",
          `${number(data.automatic_captures)} SAVED · ${number(data.automatic_skips)} SKIPPED`,
        );
      }
      setText("auto-status", String(data.automatic_status ?? "Capture diagnostics unavailable."));
      renderCaptureFreshness(data);
      renderMemories(data.recent_memories);
      renderGovernance(data.governance_events);
      renderMostUsed(recall.most_used);
      byId("error").style.display = "none";
    }

    function renderMostUsed(items) {
      const list = byId("most-used");
      list.textContent = "";
      if (!Array.isArray(items) || items.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Nothing has been recalled yet.";
        list.appendChild(empty);
        return;
      }
      for (const item of items) {
        // .memory is a three-column grid (dot / copy / trailing). Appending one child
        // drops the text into the 8px column and it wraps a word per line.
        const row = document.createElement("div");
        row.className = "memory protected";
        const dot = document.createElement("div");
        dot.className = "memory-dot";
        const copy = document.createElement("div");
        copy.className = "memory-copy";
        const content = document.createElement("p");
        content.textContent = String(item.content ?? "");
        copy.append(content);
        const count = number(item.recall_count);
        const tally = document.createElement("span");
        tally.className = "priority";
        tally.textContent = `×${count}`;
        row.append(dot, copy, tally);
        list.appendChild(row);
      }
    }

    window.addEventListener("message", (event) => {
      if (event.source !== window.parent) return;
      const message = event.data;
      if (!message || message.jsonrpc !== "2.0") return;
      if (message.id !== undefined && pendingRequests.has(message.id)) {
        const pending = pendingRequests.get(message.id);
        pendingRequests.delete(message.id);
        if (message.error) pending.reject(message.error);
        else pending.resolve(message.result);
        return;
      }
      if (message.method === "ui/notifications/tool-result") {
        render(message.params?.structuredContent ?? message.params);
      }
    }, { passive: true });

    byId("refresh").addEventListener("click", async () => {
      const button = byId("refresh");
      button.disabled = true;
      button.textContent = "Refreshing…";
      try {
        const result = await request("tools/call", { name: "memorysafe_health", arguments: {} });
        render(result);
      } catch (_) {
        byId("error").style.display = "block";
      } finally {
        button.disabled = false;
        button.textContent = "Refresh";
      }
    });

    byId("auto-toggle").addEventListener("click", async () => {
      const button = byId("auto-toggle");
      const nextEnabled = !automaticModeEnabled;
      button.disabled = true;
      button.textContent = "…";
      try {
        await request("tools/call", {
          name: "memorysafe_set_auto_mode",
          arguments: { enabled: nextEnabled },
        });
        const refreshed = await request("tools/call", { name: "memorysafe_health", arguments: {} });
        render(refreshed);
      } catch (_) {
        byId("error").textContent = "Automatic mode could not be changed. Your existing memories were not affected.";
        byId("error").style.display = "block";
        button.textContent = automaticModeEnabled ? "ON" : "OFF";
      } finally {
        button.disabled = false;
      }
    });

    byId("support-bundle").addEventListener("click", async () => {
      const button = byId("support-bundle");
      const result = byId("support-result");
      button.disabled = true;
      button.textContent = "Creating…";
      try {
        const payload = await request("tools/call", { name: "memorysafe_support_bundle", arguments: {} });
        result.textContent = `Privacy-safe support bundle created at ${String(payload?.path ?? "the local support folder")}. Nothing was uploaded.`;
        result.style.display = "block";
      } catch (_) {
        byId("error").textContent = "The support bundle could not be created. No information was uploaded.";
        byId("error").style.display = "block";
      } finally {
        button.disabled = false;
        button.textContent = "Report a problem";
      }
    });

    if (standalone) {
      byId("setup-link").style.display = "inline-flex";
      byId("support-bundle").style.display = "inline-flex";
      byId("refresh").click();
    } else if (window.openai?.toolOutput) {
      render(window.openai.toolOutput);
    }
  </script>
</body>
</html>"""
    return document.replace("__LOCAL_API_TOKEN__", json.dumps(local_api_token))


def panel_html(local_api_token: str | None = None) -> str:
    """Compact Dock window: health, capture toggle, a few memories. Not the full dashboard."""

    document = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <title>MemorySafe</title>
  <style>
    :root {
      --bg: #05080d;
      --surface: #0b111b;
      --border: rgba(190, 218, 245, 0.13);
      --text: #f4f8fb;
      --muted: #8291a5;
      --dim: #536276;
      --cyan: #19e4e9;
      --blue: #4b83ff;
      --green: #52dc88;
      --pink: #ff4c85;
      --amber: #f4b75e;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
      font: 13px/1.4 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body {
      background:
        radial-gradient(circle at 88% -10%, rgba(25, 228, 233, .12), transparent 180px),
        var(--bg);
    }
    .shell { padding: 14px 14px 12px; min-height: 100%; display: flex; flex-direction: column; gap: 12px; }
    header { display: flex; align-items: center; gap: 10px; }
    .mark {
      width: 32px; height: 32px; padding: 6px; display: grid; flex: 0 0 32px;
      grid-template-columns: 1fr 1fr; gap: 3px; border-radius: 8px;
      background: #07111a; border: 1px solid rgba(25, 228, 233, .42);
    }
    .mark i { display: block; border-radius: 2px; }
    .mark i:nth-child(1), .mark i:nth-child(4) { background: var(--cyan); }
    .mark i:nth-child(2), .mark i:nth-child(3) { background: var(--blue); }
    .brand strong { display: block; font-size: 14px; letter-spacing: -.3px; }
    .brand span { display: block; color: var(--muted); font-size: 9px; }
    .live { margin-left: auto; color: #a6d9b8; font: 700 8px/1 ui-monospace, Menlo, monospace; letter-spacing: .08em; }
    .live::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 5px;
      border-radius: 50%; background: var(--green); box-shadow: 0 0 7px var(--green); vertical-align: 0; }
    .hero {
      padding: 12px; display: flex; gap: 12px; align-items: center;
      border: 1px solid var(--border); border-radius: 12px;
      background: linear-gradient(145deg, rgba(25,228,233,.07), var(--surface));
    }
    .score {
      --score: 0; width: 72px; height: 72px; flex: 0 0 72px; display: grid; place-items: center;
      border-radius: 50%; background: conic-gradient(var(--cyan) calc(var(--score) * 1%), rgba(190,218,245,.18) 0);
    }
    .score::before { content: ""; position: absolute; width: 58px; height: 58px; border-radius: inherit; background: #09101a; }
    .score { position: relative; }
    .score-value { position: relative; text-align: center; }
    .score-value strong { display: block; font: 800 20px/1 ui-monospace, Menlo, monospace; }
    .score-value span { display: block; margin-top: 3px; color: var(--muted); font-size: 7px; letter-spacing: .05em; }
    .hero-copy { min-width: 0; flex: 1; }
    .hero-copy strong { display: block; font-size: 12px; }
    .hero-copy p { margin: 3px 0 0; color: var(--muted); font-size: 10px; }
    .fresh { display: inline-block; margin-top: 6px; padding: 2px 7px; border-radius: 999px;
      font: 800 8px ui-monospace, Menlo, monospace; letter-spacing: .04em; border: 1px solid transparent; }
    .fresh.active { color: var(--green); border-color: rgba(82,220,136,.4); background: rgba(82,220,136,.1); }
    .fresh.quiet { color: var(--amber); border-color: rgba(244,183,94,.4); background: rgba(244,183,94,.1); }
    .fresh.stale, .fresh.never { color: var(--pink); border-color: rgba(255,76,133,.45); background: rgba(255,76,133,.12); }
    .metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
    .metric { padding: 9px 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); min-width: 0; }
    .metric span { display: block; color: var(--muted); font-size: 8px; }
    .metric strong { display: block; margin-top: 3px; font: 800 16px/1 ui-monospace, Menlo, monospace; }
    .auto {
      padding: 10px 11px; display: flex; align-items: center; gap: 10px;
      border: 1px solid rgba(75,131,255,.2); border-radius: 10px; background: rgba(75,131,255,.055);
    }
    .auto div { min-width: 0; flex: 1; }
    .auto strong { display: block; font-size: 11px; }
    .auto small { display: block; margin-top: 2px; color: var(--muted); font-size: 9px; }
    .toggle {
      min-width: 48px; padding: 7px 8px; border: 1px solid rgba(130,145,165,.3); border-radius: 999px;
      background: rgba(255,255,255,.025); color: var(--muted); cursor: pointer;
      font: 800 9px ui-monospace, Menlo, monospace;
    }
    .toggle.on { border-color: rgba(82,220,136,.45); background: rgba(82,220,136,.1); color: var(--green); }
    .toggle:disabled { opacity: .45; }
    .memories { flex: 1; min-height: 0; padding: 10px 11px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .memories h2 { margin: 0 0 8px; font-size: 11px; display: flex; justify-content: space-between; }
    .memories h2 span { color: var(--dim); font: 700 8px ui-monospace, Menlo, monospace; }
    .row { display: grid; grid-template-columns: 7px 1fr; gap: 8px; align-items: start; padding: 7px 0;
      border-top: 1px solid rgba(190,218,245,.06); }
    .row:first-of-type { border-top: 0; }
    .dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--blue); }
    .row.protected .dot { background: var(--cyan); box-shadow: 0 0 6px rgba(25,228,233,.55); }
    .row p { margin: 0; font-size: 11px; color: #dce5ed; overflow-wrap: anywhere; }
    .row em { display: block; margin-top: 2px; color: var(--dim); font-style: normal; font-size: 8px; }
    .empty { color: var(--muted); font-size: 11px; padding: 12px 0; text-align: center; }
    footer { display: flex; gap: 8px; }
    footer a, footer button {
      flex: 1; text-align: center; text-decoration: none; cursor: pointer;
      padding: 8px 9px; border-radius: 9px; font-size: 11px;
      border: 1px solid var(--border); background: rgba(255,255,255,.025); color: var(--muted);
    }
    footer a.primary { border-color: rgba(25,228,233,.35); color: var(--cyan); }
    .error { display: none; color: #f1a3bb; font-size: 10px; }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="brand"><strong>MemorySafe</strong><span>On this Mac</span></div>
      <div class="live">LOCAL</div>
    </header>
    <section class="hero">
      <div class="score" id="score-ring">
        <div class="score-value"><strong id="score">—</strong><span>HEALTH</span></div>
      </div>
      <div class="hero-copy">
        <strong id="status-line">Your memory file</strong>
        <p id="status-note">Waiting…</p>
        <span class="fresh" id="fresh" hidden></span>
      </div>
    </section>
    <section class="metrics">
      <div class="metric"><span>Active</span><strong id="active">—</strong></div>
      <div class="metric"><span>Protected</span><strong id="protected">—</strong></div>
      <div class="metric"><span>Recalled</span><strong id="recalled">—</strong></div>
    </section>
    <section class="auto">
      <div>
        <strong>Automatic capture</strong>
        <small id="auto-status">—</small>
      </div>
      <button class="toggle" id="auto-toggle" type="button">OFF</button>
    </section>
    <section class="memories">
      <h2>Recent <span id="memory-count">0</span></h2>
      <div id="list"><div class="empty">No memories yet.</div></div>
    </section>
    <div class="error" id="error"></div>
    <footer>
      <a class="primary" href="/dashboard">Full dashboard</a>
      <button type="button" id="refresh">Refresh</button>
    </footer>
  </div>
  <script>
    const localApiToken = __LOCAL_API_TOKEN__;
    const byId = (id) => document.getElementById(id);
    const n = (v) => Number.isFinite(Number(v)) ? Number(v) : 0;
    let automaticOn = false;

    function headers() {
      return {
        "Content-Type": "application/json",
        "X-MemorySafe-Setup-Token": localApiToken || "",
      };
    }

    async function load() {
      const response = await fetch("/api/dashboard", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Unavailable");
      return data;
    }

    function render(data) {
      const health = Math.round(n(data.memory_health));
      byId("score").textContent = Number.isFinite(health) ? String(health) : "—";
      byId("score-ring").style.setProperty("--score", String(health));
      byId("active").textContent = n(data.active_memories);
      byId("protected").textContent = n(data.protected_memories);
      const recall = data.recall || {};
      byId("recalled").textContent = n(recall.times_memory_was_consulted);
      byId("status-line").textContent = String(data.governance_status || "Your memory file");
      byId("status-note").textContent = String(data.capture_status || data.automatic_status || "Local only.");
      const fresh = byId("fresh");
      const state = String(data.capture_freshness || "");
      if (["active", "quiet", "stale", "never"].includes(state)) {
        fresh.hidden = false;
        fresh.className = "fresh " + state;
        fresh.textContent = state === "active" ? "CAPTURING" : state.toUpperCase();
      } else {
        fresh.hidden = true;
      }
      automaticOn = Boolean(data.automatic_mode);
      const toggle = byId("auto-toggle");
      toggle.textContent = automaticOn ? "ON" : "OFF";
      toggle.classList.toggle("on", automaticOn);
      byId("auto-status").textContent = automaticOn
        ? "Saves durable facts as you work."
        : "Off until you turn it on.";
      const items = Array.isArray(data.recent_memories) ? data.recent_memories.slice(0, 5) : [];
      byId("memory-count").textContent = String(items.length);
      const list = byId("list");
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Nothing stored yet.";
        list.appendChild(empty);
        return;
      }
      for (const item of items) {
        const row = document.createElement("div");
        row.className = item?.protected ? "row protected" : "row";
        const dot = document.createElement("span");
        dot.className = "dot";
        const copy = document.createElement("div");
        const p = document.createElement("p");
        p.textContent = String(item?.content ?? "");
        const em = document.createElement("em");
        em.textContent = `${item?.category ?? "other"} · ${item?.protected ? "protected" : "stored"}`;
        copy.append(p, em);
        row.append(dot, copy);
        list.appendChild(row);
      }
    }

    async function refresh() {
      byId("error").style.display = "none";
      try {
        render(await load());
      } catch (error) {
        byId("error").textContent = "Could not refresh. Memories were not changed.";
        byId("error").style.display = "block";
      }
    }

    byId("refresh").addEventListener("click", refresh);
    byId("auto-toggle").addEventListener("click", async () => {
      const button = byId("auto-toggle");
      button.disabled = true;
      try {
        const response = await fetch("/api/automatic-mode", {
          method: "POST",
          cache: "no-store",
          headers: headers(),
          body: JSON.stringify({ enabled: !automaticOn }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Could not change capture");
        await refresh();
      } catch (error) {
        byId("error").textContent = "Automatic capture could not be changed.";
        byId("error").style.display = "block";
      } finally {
        button.disabled = false;
      }
    });
    refresh();
  </script>
</body>
</html>"""
    return document.replace("__LOCAL_API_TOKEN__", json.dumps(local_api_token))



def orchestra_html(local_api_token: str | None = None) -> str:
    """Retired. Orchestra is not a product surface."""

    _ = local_api_token
    return (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<title>Retired</title></head><body style='font-family:sans-serif;padding:2rem'>"
        "<h1>This page was retired</h1>"
        "<p>Orchestra is not part of MemorySafe. "
        "<a href='/dashboard'>Open the MemorySafe dashboard</a>.</p>"
        "</body></html>"
    )
