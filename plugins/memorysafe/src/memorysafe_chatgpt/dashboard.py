from __future__ import annotations

import html
import json


DASHBOARD_URI = "ui://memorysafe/dashboard-v3.html"
DASHBOARD_MIME_TYPE = "text/html;profile=mcp-app"


def dashboard_html(
    local_api_token: str | None = None,
    *,
    hosted: bool = False,
    account_url: str | None = None,
) -> str:
    """Return the self-contained MemorySafe dashboard component.

    hosted=True serves the same page from a remote server, where "this computer",
    the local database path and the LOCAL label would all be untrue. Only hosted
    needs account_url, the page's Manage link.
    """
    if hosted and not account_url:
        raise ValueError("a hosted dashboard needs account_url")

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
      font: 16px/1.45 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
    .brand strong { display: block; font-size: 19px; letter-spacing: -.35px; }
    .brand span { display: block; margin-top: 1px; color: var(--muted); font-size: 15px; }
    .live {
      margin-left: auto; display: flex; align-items: center; gap: 6px;
      color: #a6d9b8; font-size: 14px; font-weight: 700; letter-spacing: .08em;
    }
    .live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }
    .refresh, .setup-link, .support-bundle {
      border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.025);
      color: var(--muted); padding: 7px 9px; cursor: pointer;
    }
    .setup-link, .support-bundle { display: none; text-decoration: none; }
    .refresh:hover, .setup-link:hover, .support-bundle:hover { border-color: rgba(25, 228, 233, .38); color: var(--text); }
    .refresh:disabled { opacity: .45; cursor: wait; }
    .support-result { margin: 0 0 10px; padding: 10px 12px; border: 1px solid rgba(82,220,136,.18); border-radius: 9px; background: rgba(82,220,136,.05); color: #9fcdb0; font-size: 15px; overflow-wrap: anywhere; }
    /* Collapsed rather than display:none. Screen readers only announce a live region that
       was already in the page when its text changed, so this one is never taken out. */
    .support-result:empty { margin: 0; padding: 0; border: 0; }
    .support-result.bad { border-color: rgba(244,183,94,.3); background: rgba(244,183,94,.06); color: #f3d3a0; }
    .support-result a { color: var(--cyan); }
    .hosted-text { margin: 0 0 10px; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .hosted-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin: 0 0 10px; }
    .plan-key { flex: 1 1 280px; min-width: 0; padding: 9px 11px; border: 1px solid rgba(255,255,255,.14); border-radius: 9px; background: transparent; color: inherit; font: inherit; }
    .report-form { margin: 0 0 10px; padding: 11px 12px; border: 1px solid rgba(25,228,233,.35); border-radius: 9px; background: rgba(25,228,233,.06); }
    .report-form label { display: block; color: #dce5ed; font-size: 15px; font-weight: 700; }
    .report-form label span { display: block; margin-top: 3px; color: var(--dim); font-size: 14px; font-weight: 400; }
    .report-form textarea { display: block; width: 100%; margin: 8px 0; padding: 8px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-2); color: var(--text); font-family: inherit; font-size: 15px; line-height: 1.45; resize: vertical; }
    .report-form textarea:focus { outline: none; border-color: rgba(25,228,233,.5); }
    .report-actions { display: flex; gap: 7px; flex-wrap: wrap; }
    .hero {
      margin-top: 17px; padding: 17px; display: grid; grid-template-columns: 1fr auto;
      gap: 20px; align-items: center; border: 1px solid var(--border); border-radius: 14px;
      background: linear-gradient(145deg, rgba(25,228,233,.07), rgba(75,131,255,.025) 48%, var(--surface));
    }
    .eyebrow { color: var(--cyan); font: 700 14px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .13em; }
    h1 { margin: 7px 0 5px; font-size: 24px; line-height: 1.1; letter-spacing: -.7px; }
    .hero p { margin: 0; color: var(--muted); font-size: 16px; max-width: 480px; }
    .auto-mode {
      margin-top: 13px; padding: 10px 11px; display: flex; align-items: center; gap: 12px;
      max-width: 520px; border: 1px solid rgba(75,131,255,.2); border-radius: 10px;
      background: rgba(75,131,255,.055);
    }
    .auto-copy { min-width: 0; flex: 1; }
    .auto-copy strong { display: block; font-size: 15px; }
    .auto-copy span { display: block; margin-top: 2px; color: var(--muted); font-size: 14px; }
    .auto-copy small { display: block; margin-top: 5px; color: var(--dim); font-size: 14px; line-height: 1.35; }
    /* Liveness sits next to the score on purpose. The score cannot fall when capture
       stops, so a stale store otherwise reads as a healthy one. */
    .capture-freshness[hidden] { display: none; }
    .capture-freshness {
      margin-top: 6px; padding: 3px 7px; border-radius: 999px; width: fit-content;
      font: 800 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .04em;
      border: 1px solid transparent;
    }
    .capture-freshness.active { color: var(--green); border-color: rgba(82,220,136,.4); background: rgba(82,220,136,.1); }
    .capture-freshness.quiet  { color: var(--amber); border-color: rgba(244,183,94,.4); background: rgba(244,183,94,.1); }
    .capture-freshness.stale,
    .capture-freshness.never  { color: var(--pink); border-color: rgba(255,76,133,.45); background: rgba(255,76,133,.12); }
    .capture-freshness.unknown { color: var(--dim); border-color: var(--border); }
    .auto-counts { color: var(--dim); font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
    .auto-toggle {
      min-width: 50px; padding: 7px 9px; border: 1px solid rgba(130,145,165,.3); border-radius: 999px;
      background: rgba(255,255,255,.025); color: var(--muted); cursor: pointer;
      font: 800 14px ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .auto-toggle.on { border-color: rgba(82,220,136,.45); background: rgba(82,220,136,.1); color: var(--green); }
    .auto-toggle:disabled { opacity: .45; cursor: wait; }
    .score {
      --score: 0; width: 176px; height: 176px; display: grid; place-items: center;
      border-radius: 50%; position: relative; box-shadow: 0 0 24px rgba(25,228,233,.11);
      /* A visible track matters more than the arc: every new store sits near zero, and
         a 10% arc on a .07 track just reads as an empty hole in the layout. */
      background: conic-gradient(var(--cyan) calc(var(--score) * 1%), rgba(190,218,245,.18) 0);
    }
    .score::before { content: ""; position: absolute; inset: 7px; border-radius: inherit; background: #09101a; }
    .score-value { position: relative; text-align: center; }
    .score-value strong { display: block; font: 800 28px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .score-value span { display: block; margin-top: 4px; color: var(--muted); font-size: 14px; letter-spacing: .03em; line-height: 1.25; max-width: 118px; }
    .metrics { margin-top: 10px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .metric { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface); }
    .metric span { display: block; color: var(--muted); font-size: 14px; }
    .metric strong { display: block; margin: 5px 0 2px; font: 800 21px/1.05 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .metric small { color: var(--dim); font-size: 14px; }
    .metric-cyan strong { color: var(--cyan); }
    .metric-blue strong { color: #82a7ff; }
    .metric-green strong { color: var(--green); }
    .content-grid { margin-top: 10px; display: grid; grid-template-columns: .9fr 1.1fr; gap: 10px; }
    .panel { padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); min-width: 0; }
    .panel-title { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 11px; }
    .panel-title strong { font-size: 16px; }
    .panel-title span { color: var(--dim); font-size: 14px; }
    .compare { display: grid; grid-template-columns: 1fr 18px 1fr; align-items: stretch; gap: 7px; }
    .compare-card { padding: 12px; border-radius: 10px; background: var(--surface-2); border: 1px solid rgba(190,218,245,.08); }
    .compare-card.with { border-color: rgba(25,228,233,.22); background: rgba(25,228,233,.055); }
    .compare-card span { color: var(--muted); font-size: 14px; }
    .compare-card strong { display: block; margin-top: 6px; font: 800 23px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .compare-card small { display: block; margin-top: 5px; color: var(--dim); font-size: 14px; }
    .compare-card.with strong { color: var(--cyan); }
    .arrow { display: grid; place-items: center; color: var(--cyan); font-size: 17px; }
    .savings { margin-top: 9px; display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .saving { padding: 9px; border-radius: 9px; background: rgba(82,220,136,.045); border: 1px solid rgba(82,220,136,.1); }
    .saving strong { display: block; color: var(--green); font: 800 16px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .saving span { color: #70897a; font-size: 14px; }
    .memory-list { display: grid; gap: 7px; }
    .memory { display: grid; grid-template-columns: 8px 1fr auto; gap: 9px; align-items: start; padding: 9px 10px; border-radius: 9px; background: var(--surface-2); }
    .memory-dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--blue); }
    .memory.protected .memory-dot { background: var(--cyan); box-shadow: 0 0 7px rgba(25,228,233,.55); }
    .memory-copy { min-width: 0; }
    .memory-copy p { margin: 0; color: #dce5ed; font-size: 15px; overflow-wrap: anywhere; white-space: pre-line; }
    .memory-copy span { display: block; margin-top: 4px; color: var(--dim); font-size: 14px; }
    .priority { color: var(--muted); font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .store-path { margin: 9px 0 0; color: var(--dim); font-size: 14px; }
    .store-path code { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .memory-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
    .memory-forget { border: 1px solid rgba(190,218,245,.18); background: transparent; color: var(--dim);
      font: 600 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase;
      padding: 3px 7px; border-radius: 5px; cursor: pointer; }
    .memory-forget:hover { color: var(--pink); border-color: rgba(255,76,133,.5); }
    .memory-forget.confirm { color: var(--bg); background: var(--pink); border-color: var(--pink); }
    .memory-forget:disabled { opacity: .5; cursor: default; }
    .memory-forget:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
    .empty { padding: 19px 10px; text-align: center; color: var(--muted); font-size: 15px; border: 1px dashed var(--border); border-radius: 9px; }
    .agents-panel { margin-top: 10px; }
    .agent { display: grid; grid-template-columns: 1fr auto; gap: 9px; align-items: center; padding: 9px 10px; border-radius: 9px; background: var(--surface-2); }
    .agent-copy { min-width: 0; }
    .agent-name { display: block; color: #dce5ed; font-size: 15px; font-weight: 700; }
    .agent-note { display: block; margin-top: 4px; color: var(--dim); font-size: 14px; overflow-wrap: anywhere; }
    .agent-state { font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; padding: 3px 7px; border-radius: 5px; white-space: nowrap; }
    .agent-state.on { color: var(--green); border: 1px solid rgba(82,220,136,.35); }
    .agent-state.off { color: var(--amber); border: 1px solid rgba(244,183,94,.35); }
    .agent-connect { border: 1px solid rgba(25,228,233,.45); background: rgba(25,228,233,.08); color: var(--cyan);
      font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase;
      padding: 4px 9px; border-radius: 5px; cursor: pointer; white-space: nowrap; }
    .agent-connect:hover { background: rgba(25,228,233,.16); }
    .agent-connect:disabled { opacity: .5; cursor: wait; }
    .agent-connect:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
    .agents-missing { margin: 9px 0 0; color: var(--dim); font-size: 14px; }
    .agents-ask { margin-bottom: 9px; padding: 11px 12px; border-radius: 9px; border: 1px solid rgba(25,228,233,.35); background: rgba(25,228,233,.06); }
    .agents-ask p { margin: 0 0 9px; color: #dce5ed; font-size: 15px; }
    .agents-ask-actions { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
    .agents-ask small { display: block; margin-top: 8px; color: var(--dim); font-size: 14px; }
    .agents-no, .agents-link { border: 1px solid var(--border); background: transparent; color: var(--muted);
      font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase;
      padding: 4px 9px; border-radius: 5px; cursor: pointer; }
    .agents-no:hover, .agents-link:hover { color: var(--text); border-color: rgba(25,228,233,.38); }
    .agents-link { padding: 1px 6px; margin-left: 4px; }
    .agents-auto { margin: 9px 0 0; color: var(--dim); font-size: 14px; }
    .agents-mode { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; margin-bottom: 9px; }
    .agents-mode-label { color: var(--dim); font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .agents-mode-choice { border: 1px solid var(--border); background: transparent; color: var(--muted);
      font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase;
      padding: 4px 9px; border-radius: 5px; cursor: pointer; }
    .agents-mode-choice:hover { color: var(--text); border-color: rgba(25,228,233,.38); }
    .agents-mode-choice.on { color: var(--cyan); border-color: rgba(25,228,233,.45); background: rgba(25,228,233,.08); cursor: default; }
    .agents-mode-choice:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
    .agents-hosted { margin: 0 0 9px; padding: 11px 12px; border-radius: 9px; border: 1px solid var(--border); color: var(--dim); font-size: 14px; }
    .agents-hosted p { margin: 0; }
    .agents-hosted a { color: var(--cyan); }
    .agents-hosted #agents-local-count { margin: 8px 0 0; color: var(--muted); }
    .agents-link { margin: 10px 0 0; padding-top: 10px; border-top: 1px solid var(--border); }
    .agents-link p { margin: 0 0 8px; color: var(--text); }
    .agents-link small { display: block; margin-top: 6px; color: var(--muted); line-height: 1.4; }
    .agents-message { margin: 9px 0 0; color: #9fcdb0; font-size: 14px; overflow-wrap: anywhere; }
    .agents-message.bad { color: var(--amber); }
    .token-panel { margin-top: 10px; background: linear-gradient(145deg, rgba(75,131,255,.07), rgba(25,228,233,.025) 62%, var(--surface)); }
    .token-badge { color: #8eabef !important; font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .token-live-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .token-live-stat { padding: 11px 12px; border: 1px solid rgba(25,228,233,.15); border-radius: 10px; background: rgba(25,228,233,.04); min-width: 0; }
    .token-live-stat span { display: block; color: var(--muted); font-size: 14px; }
    .token-live-stat strong { display: block; margin: 6px 0 3px; color: var(--cyan); font: 800 20px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-live-stat small { color: var(--dim); font-size: 14px; }
    .gov-item { padding: 11px 1px; border-bottom: 1px solid rgba(142,171,239,.10); }
    .gov-item:last-child { border-bottom: 0; }
    .gov-head { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; flex-wrap: wrap; }
    .gov-tag { font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; padding: 3px 7px; border-radius: 4px; }
    .gov-supersede { background: rgba(255,176,84,.15); color: #ffb054; }
    .gov-restore { background: rgba(94,234,212,.15); color: #5eead4; }
    .gov-review { background: rgba(142,171,239,.15); color: #8eabef; }
    .gov-when { color: #6b7f9e; font: 500 15px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .gov-reason { color: #c8d6f0; font-size: 16px; line-height: 1.45; margin-bottom: 8px; }
    .gov-pair { display: grid; gap: 5px; }
    .gov-line { display: grid; grid-template-columns: 62px 1fr; gap: 9px; align-items: baseline; font-size: 16px; line-height: 1.4; }
    .gov-label { font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .07em; color: #6b7f9e; padding-top: 2px; }
    .gov-out { color: #7d8ba3; text-decoration: line-through; text-decoration-color: rgba(125,139,163,.45); }
    .gov-in { color: #dbe6fb; }
    .token-section-label { display: flex; align-items: center; gap: 9px; margin: 12px 1px 8px; color: #8eabef; font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .token-section-label::after { content: ""; height: 1px; flex: 1; background: rgba(142,171,239,.13); }
    .token-grid { display: grid; grid-template-columns: .72fr .72fr 1.28fr 1.28fr; gap: 8px; }
    .token-stat, .token-saving { padding: 12px; border: 1px solid rgba(190,218,245,.09); border-radius: 10px; background: rgba(5,8,13,.42); min-width: 0; }
    .token-stat span, .token-saving span { display: block; color: var(--muted); font-size: 14px; }
    .token-stat strong { display: block; margin: 6px 0 3px; color: #a9bdff; font: 800 21px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-stat small { color: var(--dim); font-size: 14px; }
    .token-saving-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
    .token-saving-head strong { color: var(--green); font: 800 17px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .token-bar { height: 5px; margin-top: 10px; overflow: hidden; border-radius: 999px; background: rgba(255,255,255,.07); }
    .token-bar i { display: block; width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--blue), var(--cyan)); box-shadow: 0 0 9px rgba(25,228,233,.3); transition: width .35s ease; }
    .token-note { margin: 9px 1px 0; color: var(--dim); font-size: 14px; }
    .token-note strong { color: var(--amber); }
    .formula { margin-top: 10px; padding: 10px 12px; display: flex; gap: 9px; align-items: flex-start; border: 1px solid rgba(244,183,94,.11); border-radius: 10px; background: rgba(244,183,94,.035); color: #9b8a72; font-size: 14px; }
    .formula strong { flex: 0 0 auto; color: var(--amber); }
    .error { margin-top: 12px; padding: 10px 12px; border-radius: 9px; background: rgba(255,76,133,.07); color: #f1a3bb; display: none; }
    .notice { margin-top: 12px; padding: 10px 12px; border-radius: 9px; background: rgba(25,228,233,.07); color: var(--text); display: none; font-size: 16px; }
    .notice a { color: var(--cyan); }
    @media (max-width: 620px) {
      .shell { padding: 12px; }
      .topline { flex-wrap: wrap; }
      .brand { flex: 1; }
      .live { display: none; }
      .hero { grid-template-columns: 1fr; gap: 14px; padding: 14px; }
      .auto-mode { flex-wrap: wrap; gap: 8px; }
      .auto-copy { flex: 1 0 100%; }
      .auto-counts { margin-right: auto; }
      .score { width: 160px; height: 160px; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .content-grid { grid-template-columns: 1fr; }
      .token-live-grid { grid-template-columns: 1fr 1fr; }
      .token-grid { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 380px) {
      .brand span { display: none; }
      h1 { font-size: 22px; }
      .metrics { grid-template-columns: 1fr; }
      .compare { grid-template-columns: 1fr; }
      .arrow { transform: rotate(90deg); min-height: 18px; }
      .savings { grid-template-columns: 1fr; }
      .token-live-grid { grid-template-columns: 1fr; }
      .token-grid { grid-template-columns: 1fr; }
    }
        [hidden] { display: none !important; }
      .gov-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
      .gov-action { border: 1px solid rgba(190,218,245,.28); background: transparent; color: var(--text); font: 600 14px ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 7px 13px; border-radius: 9px; cursor: pointer; }
      .gov-action:hover { border-color: var(--cyan); color: var(--cyan); }
      .gov-action.confirm { color: var(--bg); background: var(--cyan); border-color: var(--cyan); }
      .gov-action:disabled { opacity: .5; cursor: default; }
      .gov-action:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
      .gov-help { flex-basis: 100%; color: var(--muted); font-size: 14px; line-height: 1.4; min-height: 1.4em; }
      .gov-error { flex-basis: 100%; color: var(--pink); font-size: 14px; }
      .fold-panel { margin-top: 10px; }
      .fold-panel > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
      .fold-panel > summary::-webkit-details-marker { display: none; }
      .fold-panel > summary strong { font-size: 16px; }
      .fold-panel > summary strong::before { content: "\25B8"; display: inline-block; width: 14px; color: var(--dim); transition: transform .15s; }
      .fold-panel[open] > summary strong::before { transform: rotate(90deg); }
      .fold-panel > summary span { color: var(--dim); font-size: 14px; }
      .fold-panel[open] > summary { margin-bottom: 11px; }
      .fold-panel > summary span.needs { color: #ffb454; }
      .content-grid { grid-template-columns: 1fr; }
      details.tech { margin-top: 18px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px; }
      details.tech summary { cursor: pointer; font-size: 16px; letter-spacing: .08em; text-transform: uppercase; opacity: .6; }
      details.tech p { font-size: 16px; opacity: .65; line-height: 1.6; margin: 10px 0 0; }
    </style>
</head>
<body>
  <main class="shell">
    <header class="topline">
      <div class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="brand"><strong>MemorySafe</strong><span>Private local memory governance</span></div>
      <div class="live" id="live-label">LOCAL · PRIVATE</div>
      <a class="setup-link" id="setup-link" href="/">Setup</a>
      <button class="support-bundle" id="support-bundle" type="button">Report a problem</button>
      <button class="refresh" id="refresh" type="button">Refresh</button>
    </header>
    <!-- Right under the button that fills it. It used to sit at the foot of the page, below
         "Technical detail", so a tester clicked Report a problem and saw nothing happen. -->
    <div class="report-form" id="report-form" hidden>
      <label for="report-description">What went wrong?
        <span>Optional. It goes into the report file and the email. Leave out passwords and other people's details.</span></label>
      <textarea id="report-description" maxlength="4000" rows="3" placeholder="For example: I asked Claude to remember my deadline and it said MemorySafe wasn't available."></textarea>
      <div class="report-actions">
        <button class="agent-connect" id="report-send" type="button">Create report and email it</button>
        <button class="agents-no" id="report-cancel" type="button">Cancel</button>
      </div>
    </div>
    <div class="support-result" id="support-result" role="status"></div>

    <section class="hero">
      <div>
        <div class="eyebrow">MEMORYSAFE · LIVE</div>
        <h1 id="hero-title">Modeled context per turn</h1>
        <p id="hero-note">Without MemorySafe, every stored fact is restated. With MemorySafe, only the facts actually recalled plus a fixed tool cost.</p>
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
    <section class="panel agents-panel" id="agents-panel" aria-label="Your assistants" hidden>
      <div class="panel-title"><strong>One memory, every assistant</strong><span id="agents-note">ON THIS COMPUTER</span></div>
      <div class="agents-mode" id="agents-mode" hidden>
        <span class="agents-mode-label">MEMORIES LIVE</span>
        <button class="agents-mode-choice" id="mode-local" type="button">On this computer</button>
        <button class="agents-mode-choice" id="mode-hosted" type="button">In my hosted account</button>
      </div>
      <div class="agents-hosted" id="agents-hosted" hidden>
        <p>Each assistant connects to your account from its own settings; the steps are on
        <a href="https://memory.memorysafe.ca/connect" target="_blank" rel="noopener">your hosted Connect page</a>.
        This choice moves no memories: to take the ones on this computer with you, export them below and
        import the file on your account page. The way back works too: download the move file from your
        account page, set memories to live on this computer again, and import it below.</p>
        <p>The numbers and memories on this page are still the ones left on this computer. Your account's are on
        <a href="https://memory.memorysafe.ca/account" target="_blank" rel="noopener">your account page</a>.</p>
        <p id="agents-local-count" hidden></p>
        <div class="agents-link" id="agents-link">
          <p id="agents-link-text"></p>
          <div class="agents-ask-actions">
            <button class="agent-connect" id="link-signin" type="button">Sign in to your account</button>
            <button class="agents-no" id="link-signout" type="button" hidden>Sign out</button>
          </div>
          <small id="agents-link-note"></small>
        </div>
      </div>
      <div class="agents-ask" id="agents-ask" hidden>
        <p id="agents-ask-text"></p>
        <div class="agents-ask-actions">
          <button class="agent-connect" id="agents-yes" type="button">Yes, connect them</button>
          <button class="agents-no" id="agents-no" type="button">No thanks</button>
        </div>
        <small>Your answer is remembered. Yes also connects assistants you install later, the next time MemorySafe starts.</small>
      </div>
      <div class="memory-list" id="agents"></div>
      <p class="agents-missing" id="agents-missing" hidden></p>
      <p class="agents-auto" id="agents-auto" hidden>Assistants you install later connect automatically.<button class="agents-link" id="agents-auto-off" type="button">Turn off</button></p>
      <p class="agents-message" id="agents-message" hidden></p>
    </section>
    <section class="panel hosted-panel" id="hosted-panel" aria-label="Take your memory everywhere">
      <div class="panel-title"><strong>Take your memory everywhere</strong><span>MEMORYSAFE HOSTED · FREE</span></div>
      <p class="hosted-text">Hosted gives every assistant you use, on every device, this same memory. Export a copy here, then import it into your Hosted account; nothing leaves this computer until you upload the file yourself.</p>
      <div class="hosted-actions">
        <button class="agent-connect" id="hosted-export" type="button">Export my memories for Hosted</button>
        <a class="agents-link" href="https://memory.memorysafe.ca/account/start?signup=1&amp;next=/account/import&amp;lang=en" target="_blank" rel="noopener">Create a free Hosted account</a>
      </div>
      <div class="support-result" id="hosted-result" role="status"></div>
      <p class="hosted-text hosted-return">Coming back from Hosted? Download the move file from
        <a href="https://memory.memorysafe.ca/account/export" target="_blank" rel="noopener">your account page</a>,
        then choose it here. Memories already on this computer are kept: duplicates merge, and a conflict is flagged
        for you to decide. Nothing on your account changes.</p>
      <div class="hosted-actions">
        <input id="hosted-import-file" type="file" accept="application/json,.json" hidden>
        <button class="agent-connect" id="hosted-import" type="button">Import a move file</button>
      </div>
      <div class="support-result" id="hosted-import-result" role="status"></div>
    </section>
    <section class="panel hosted-panel" id="plan-panel" aria-label="Your plan" hidden>
      <div class="panel-title"><strong>Your plan</strong><span id="plan-note"></span></div>
      <p class="hosted-text" id="plan-text"></p>
      <div class="hosted-actions">
        <input class="plan-key" id="plan-key" type="text" autocomplete="off" spellcheck="false" placeholder="Plan key from your account page" aria-label="Plan key">
        <button class="agent-connect" id="plan-save" type="button">Use this key</button>
        <button class="agent-connect" id="plan-remove" type="button" hidden>Remove the key</button>
      </div>
      <div class="support-result" id="plan-result" role="status"></div>
    </section>
    <details class="panel token-panel fold-panel" aria-label="Tokens with and without MemorySafe">
      <summary><strong>With vs without MemorySafe</strong><span class="token-badge">THIS STORE · THIS TURN</span></summary>
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
      <p class="token-note" id="token-model">Estimated from tokens counted on this computer. Not anyone’s billed usage.</p>
    </details>
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
      <details class="panel fold-panel">
        <summary><strong>Most used</strong><span>BY RECALL</span></summary>
        <div class="memory-list" id="most-used"><div class="empty">Nothing has been recalled yet.</div></div>
      </details>
    </section>
    <details class="panel fold-panel" aria-label="Governance trail" id="governance-panel" hidden>
      <summary><strong>Governance trail</strong><span id="governance-note">EVERY DECISION, WITH ITS REASON</span></summary>
      <div class="memory-list" id="governance"></div>
    </details>
    <details class="tech">
      <summary>Technical detail</summary>
      <p id="tech-dupes">—</p>
      <p id="tech-health">—</p>
      <p id="tech-breakeven">—</p>
      <p id="tech-hypothetical">—</p>
      <p class="store-path">Reading <code id="database-path">—</code></p>
    </details>
    <div class="error" id="error">The dashboard could not refresh. Your stored memories were not changed.</div>
    <div class="notice" id="terms-notice" role="status"></div>
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
        if (toolName === "memorysafe_resolve_conflict") {
          return fetch("/api/conflicts/resolve", {
            method: "POST",
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
              "X-MemorySafe-Setup-Token": localApiToken,
            },
            body: JSON.stringify({
              conflict_id: Number(params?.arguments?.conflict_id),
              action: String(params?.arguments?.action ?? ""),
            }),
          }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload?.error ?? "That decision could not be saved");
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
            body: JSON.stringify({ description: String(params?.arguments?.description ?? "") }),
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
      // When the last memory was saved, by any route: a memory saved by hand counts
      // too, so nothing here may read as if automatic capture were running.
      const label =
        state === "never" ? "NOTHING SAVED YET"
        : state === "unknown" ? "LAST SAVE UNKNOWN"
        : state === "active" ? (number(data.days_since_last_capture) === 1 ? "SAVED YESTERDAY" : "SAVED TODAY")
        : `LAST SAVED ${number(data.days_since_last_capture)}D AGO`;
      node.className = "capture-freshness " + state;
      node.textContent = label;
      node.title = String(data.capture_status ?? "");
      node.hidden = false;
    }

    function renderMemories(items) {
      const list = byId("memories");
      list.replaceChildren();
      const memories = Array.isArray(items) ? items : [];
      setText("memory-count", `LATEST ${Math.min(memories.length, 3)}`);
      if (!memories.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No memories stored yet. Ask your assistant to remember something useful.";
        list.appendChild(empty);
        return;
      }
      for (const item of memories.slice(0, 3)) {
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

    // The three answers the page offers to an open conflict. "Restore" is left to the assistants: it
    // puts the older fact back but leaves the question open, which is not an answer.
    const CONFLICT_CHOICES = [
      ["keep_both", "Keep both", "Both are true. Both stay in recall."],
      ["supersede", "Newer replaces older", "The newer fact wins. The older one leaves recall but is kept, and can be brought back."],
      ["revert", "Keep the older", "The newer update was wrong. It is rejected and the older fact comes back."],
    ];

    function conflictActions(conflictId) {
      const box = document.createElement("div");
      box.className = "gov-actions";
      const help = document.createElement("div");
      help.className = "gov-help";
      help.textContent = "Decide this: pick one, then confirm.";
      const buttons = [];
      for (const [action, labelText, explanation] of CONFLICT_CHOICES) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "gov-action";
        button.textContent = labelText;
        button.setAttribute("aria-label", `${labelText}: ${explanation}`);
        let armed = false;
        let timer = null;
        const disarm = () => {
          armed = false;
          clearTimeout(timer);
          button.classList.remove("confirm");
          button.textContent = labelText;
          help.textContent = "Decide this: pick one, then confirm.";
        };
        button.addEventListener("click", async () => {
          // A decision changes what the assistants recall, so the first click only asks.
          if (!armed) {
            for (const other of buttons) if (other !== button) other.dispatchEvent(new Event("disarm"));
            armed = true;
            button.classList.add("confirm");
            button.textContent = "Confirm";
            help.textContent = explanation;
            timer = setTimeout(disarm, 6000);
            return;
          }
          clearTimeout(timer);
          for (const each of buttons) each.disabled = true;
          button.textContent = "\u2026";
          try {
            await request("tools/call", {
              name: "memorysafe_resolve_conflict",
              arguments: { conflict_id: conflictId, action, confirm: true },
            });
            byId("refresh").click();
          } catch (error) {
            for (const each of buttons) each.disabled = false;
            disarm();
            const note = document.createElement("div");
            note.className = "gov-error";
            note.textContent = String(error?.message ?? "That decision could not be saved.");
            box.append(note);
          }
        });
        button.addEventListener("disarm", disarm);
        buttons.push(button);
      }
      box.append(...buttons, help);
      return box;
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
      // Folded by default so it stops crowding the page; this keeps the one thing that needs
      // the person visible without opening it.
      const waiting = rows.filter((event) => event?.status === "open").length;
      const note = document.getElementById("governance-note");
      if (note) {
        note.textContent = waiting ? `${waiting} NEED${waiting === 1 ? "S" : ""} A DECISION` : "EVERY DECISION, WITH ITS REASON";
        note.classList.toggle("needs", waiting > 0);
      }

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
      // What needs the person comes first and is never cut off by the cap on the rest.
      const open = rows.filter((event) => event?.status === "open");
      const ordered = [...open, ...rows.filter((event) => event?.status !== "open")];
      const limit = Math.max(5, open.length);
      for (const event of ordered) {
        if (shown >= limit) break;
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
        if (event.status === "open" && Number.isInteger(event.conflict_id)) item.append(conflictActions(event.conflict_id));
        list.append(item);
        shown += 1;
      }
    }

    // The local store's plan. Out of sight while local storage has no limit (local_plan is
    // null), and on the hosted page, which never sends it.
    function renderPlan(plan) {
      const panel = byId("plan-panel");
      if (!panel) return;
      panel.hidden = !plan;
      if (!plan) return;
      const name = plan.plan === "free" ? "Free" : "Paid";
      const used = number(plan.used).toLocaleString();
      const limit = number(plan.limit).toLocaleString();
      setText("plan-note", `${name.toUpperCase()} · ${used} OF ${limit}`);
      let text = `${name} plan: ${used} of ${limit} memories. A full store stops accepting new memories and tells you; nothing is removed to make room.`;
      if (plan.expires_at) {
        text += ` Your plan key is valid until ${new Date(plan.expires_at * 1000).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}; get a new one from your account page before then.`;
      } else {
        text += " A paid plan holds more: paste the plan key from your account page.";
      }
      setText("plan-text", text);
      byId("plan-remove").hidden = plan.plan === "free";
    }

    function render(payload) {
      const data = unwrap(payload);
      renderPlan(data.local_plan ?? null);
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
      if (data.version) setText("live-label", `LOCAL · PRIVATE · ${String(data.version)}`);
      const termsNotice = byId("terms-notice");
      if (termsNotice) {
        if (data.terms_update_pending) {
          termsNotice.textContent = `${String(data.legal_change_note ?? "The Beta Terms or Privacy Policy changed.")} Nothing has stopped working. `;
          const review = document.createElement("a");
          review.href = "/";
          review.textContent = "Read it and accept it in Setup";
          termsNotice.appendChild(review);
          termsNotice.style.display = "block";
        } else {
          termsNotice.style.display = "none";
        }
      }

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
      const breakEvenFacts = number(tokenBenchmark.break_even_facts);
      if (payingOff) {
        setText("hero-title", "Modeled context per turn");
        setText("hero-note", "Without MemorySafe, every stored fact is restated. With MemorySafe, only the facts actually recalled plus a fixed tool cost.");
        setText("tokens-saved", savedTokens.toLocaleString());
        setText("tokens-saved-pct", `${Math.round(pctSaved)}% less`);
        setText("tokens-saved-hero", savedTokens.toLocaleString());
        setText("tokens-saved-label", "ESTIMATED TOKENS SAVED / TURN");
        byId("score-ring").style.setProperty("--score", Math.max(0, Math.min(100, pctSaved)));
      } else {
        // Until the store pays off, the first thing on the page is what it holds, not
        // a cost that swings with every early memory. The cost stays in the details.
        setText("hero-title", "Your memory, on this computer");
        setText(
          "hero-note",
          breakEvenFacts
            ? `Every assistant here reads and saves the same memories. Token savings show here once the store holds about ${breakEvenFacts.toLocaleString()} of them.`
            : "Every assistant here reads and saves the same memories. Token savings show here once the store holds enough of them.",
        );
        setText("tokens-saved", "0");
        setText("tokens-saved-pct", extraTokens ? `${extraTokens.toLocaleString()} extra for now` : "not yet paying off");
        setText("tokens-saved-hero", stored.toLocaleString());
        setText("tokens-saved-label", stored === 1 ? "MEMORY KEPT" : "MEMORIES KEPT");
        byId("score-ring").style.setProperty("--score", 0);
      }
      setText("token-model", "Estimated from tokens counted on this computer. Not anyone’s billed usage.");

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
        (data.memory_health == null ? "Health: no score until a memory is saved. " : `Health ${number(data.memory_health)} — `)
        + `${String(data.formula ?? "")} `
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

    function agentNode(tag, className, text) {
      const node = document.createElement(tag);
      node.className = className;
      if (text !== undefined) node.textContent = String(text);
      return node;
    }

    let storageMode = "local";

    function renderAgents(agents, autoConnect, mode) {
      // Installing MemorySafe in one assistant used to leave the others to be found and
      // installed one guide at a time. This panel lists every assistant on the computer
      // and connects the rest from here, each through its own installer.
      if (mode === "local" || mode === "hosted") storageMode = mode;
      const hostedMode = storageMode === "hosted";
      const panel = byId("agents-panel");
      const list = byId("agents");
      if (!Array.isArray(agents) || !agents.length) { panel.hidden = true; return; }
      panel.hidden = false;
      byId("agents-mode").hidden = false;
      byId("mode-local").classList.toggle("on", !hostedMode);
      byId("mode-hosted").classList.toggle("on", hostedMode);
      byId("agents-hosted").hidden = !hostedMode;
      // The move-file export is for memories the assistants still use. In hosted mode they
      // use the account and /api/export refuses, so the panel is not offered.
      byId("hosted-panel").hidden = hostedMode;
      list.replaceChildren();
      const present = agents.filter((agent) => agent.present);
      // Asked once. Installing into another app unasked crosses a line; asking on every
      // visit is how a question gets dismissed unread. null means never answered. In
      // hosted mode never: the question installs the local plugin, which the person has
      // decided against.
      const connectable = present.filter((agent) => agent.can_connect && !agent.connected);
      const ask = byId("agents-ask");
      ask.hidden = hostedMode || !(autoConnect === null && connectable.length > 0);
      if (!ask.hidden) {
        const names = connectable.map((agent) => agent.label);
        const listed = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
        const pronoun = names.length > 1 ? "them" : "it";
        setText("agents-ask-text", `MemorySafe found ${listed} on this computer. Connect ${pronoun} to the same memory?`);
        setText("agents-yes", `Yes, connect ${pronoun}`);
      }
      byId("agents-auto").hidden = hostedMode || autoConnect !== true;
      const connected = present.filter((agent) => agent.connected || agent.covered).length;
      setText("agents-note", hostedMode ? "IN YOUR MEMORYSAFE ACCOUNT" : `${present.length} FOUND · ${connected} CONNECTED`);
      if (!present.length) {
        list.append(agentNode("div", "empty", "No assistants found on this computer yet."));
      }
      for (const agent of present) {
        const row = agentNode("div", "agent");
        const copy = agentNode("div", "agent-copy");
        copy.append(agentNode("span", "agent-name", agent.label));
        if (hostedMode) {
          // The account's own connections live on the hosted side and cannot be checked
          // locally, so no row claims one. What is known here is the plugin: in this mode
          // its tools are answered by the account, through the sign-in above.
          const viaPlugin = agent.connected || agent.covered;
          copy.append(agentNode("span", "agent-note", viaPlugin
            ? "Connected through the plugin on this computer, which reads and saves in your account once you have signed in above."
            : "Connect it to your account from the hosted Connect page. Its account connection cannot be checked from here."));
          row.append(copy);
          if (viaPlugin) row.append(agentNode("span", "agent-state", "THROUGH THE PLUGIN"));
          list.append(row);
          continue;
        }
        const note = agent.covered
          ? String(agent.note ?? "")
          : agent.connected
          ? `Connected through its ${agent.how}.`
          : agent.can_connect ? "Installed here. Not connected yet." : String(agent.next_step ?? "");
        copy.append(agentNode("span", "agent-note", note));
        row.append(copy);
        if (agent.covered) {
          row.append(agentNode("span", "agent-state on", "CONNECTED"));
        } else if (agent.connected) {
          row.append(agentNode("span", "agent-state on", "CONNECTED"));
        } else if (agent.can_connect) {
          const button = agentNode("button", "agent-connect", "Connect");
          button.type = "button";
          button.addEventListener("click", () => connectAgent(agent, button));
          row.append(button);
        } else {
          row.append(agentNode("span", "agent-state off", "ONE STEP LEFT"));
        }
        list.append(row);
      }
      const missing = agents.filter((agent) => !agent.present).map((agent) => agent.label);
      const missingNode = byId("agents-missing");
      missingNode.hidden = !missing.length;
      missingNode.textContent = missing.length ? `Not on this computer: ${missing.join(", ")}` : "";
    }

    async function loadAgents() {
      if (!standalone) return;
      try {
        const response = await fetch("/api/agents", { cache: "no-store" });
        const payload = await response.json();
        if (response.ok) { renderAgents(payload.agents, payload.auto_connect ?? null, payload.storage_mode); renderLink(payload); }
      } catch (_) {
        // Nothing else on the dashboard depends on this panel, so it simply stays hidden.
      }
    }

    async function setStorageMode(mode) {
      // The person's one choice of where memories live. Saving it moves no memories and
      // connects nothing; it changes what this panel offers.
      if (mode === storageMode) return;
      const message = byId("agents-message");
      const buttons = [byId("mode-local"), byId("mode-hosted")];
      buttons.forEach((button) => { button.disabled = true; });
      try {
        const response = await fetch("/api/storage-mode", {
          method: "POST",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
            "X-MemorySafe-Setup-Token": localApiToken,
          },
          body: JSON.stringify({ mode }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "Your choice could not be saved.");
        message.hidden = true;
        message.textContent = "";
        renderAgents(payload.agents, payload.auto_connect ?? null, payload.storage_mode);
        renderLink(payload);
        if (mode === "local" && payload.signed_out && payload.signed_out.revoked !== undefined
            && payload.signed_out.was_linked !== false) {
          // Coming home signs the device link out; say so, since nothing else does.
          message.hidden = false;
          message.className = "agents-message";
          message.textContent = payload.signed_out.revoked
            ? "Memories live on this computer again. The plugin's sign-in to your hosted account was ended, on this and any other computer using it; your memories there were not changed."
            : payload.signed_out.reached
              ? "Memories live on this computer again. The sign-in was removed here, but your hosted account did not confirm ending it elsewhere; end it from your account page if you want that."
              : "Memories live on this computer again. Your hosted account could not be reached, so the sign-in was removed here only.";
        }
      } catch (error) {
        message.hidden = false;
        message.className = "agents-message bad";
        message.textContent = error.message;
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    }

    byId("mode-local").addEventListener("click", () => setStorageMode("local"));
    byId("mode-hosted").addEventListener("click", () => setStorageMode("hosted"));

    // The device link: the one sign-in to the hosted account, shared by every
    // assistant through the plugin. Offered the moment hosted is chosen; the browser goes to
    // the hosted sign-in and comes back to this dashboard's /callback.
    let linkWatch = null;
    function renderLink(payload) {
      const hostedMode = (payload.storage_mode ?? storageMode) === "hosted";
      const link = payload.device_link ?? {};
      const count = Number(payload.local_memories ?? 0);
      const countNode = byId("agents-local-count");
      countNode.hidden = !(hostedMode && count > 0);
      if (!countNode.hidden) {
        countNode.textContent = `${count} ${count === 1 ? "memory stays" : "memories stay"} on this computer, untouched, until you come back or delete ${count === 1 ? "it" : "them"}.`;
      }
      byId("agents-link").hidden = !hostedMode;
      if (!hostedMode) { if (linkWatch) { clearInterval(linkWatch); linkWatch = null; } return; }
      const since = link.linked_at ? new Date(link.linked_at) : null;
      setText("agents-link-text", link.linked
        ? `This computer is signed in to your hosted account${since && !Number.isNaN(since.valueOf()) ? ` since ${since.toLocaleDateString()}` : ""}.`
        : "This computer is not signed in to your hosted account yet. Sign in once here; every assistant connected through the plugin shares it.");
      byId("link-signin").hidden = !!link.linked;
      byId("link-signout").hidden = !link.linked;
      setText("agents-link-note", link.linked
        ? "Signing out ends the plugin's sign-in on every computer where you use it, not only this one. Your memories in the account are not changed."
        : "The sign-in opens in your browser. Nothing is sent until you approve it there.");
      if (link.linked && linkWatch) { clearInterval(linkWatch); linkWatch = null; }
    }

    byId("link-signin").addEventListener("click", async () => {
      const button = byId("link-signin");
      const message = byId("agents-message");
      button.disabled = true;
      // Opened now, inside the click: a browser blocks a tab opened after an await, and the
      // start call below can take seconds. The address is filled in when it is known.
      const tab = window.open("", "_blank");
      try {
        const response = await fetch("/api/link/start", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: "{}",
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "The sign-in could not be started.");
        if (tab) {
          tab.opener = null;
          tab.location.href = String(payload.url);
          setText("agents-link-note", "Finish signing in in the tab that opened; this page updates by itself.");
        } else {
          // The browser blocked the tab. The address is this account's sign-in page; a link
          // the person clicks is always allowed.
          const note = byId("agents-link-note");
          note.textContent = "Your browser blocked the sign-in tab. ";
          const open = document.createElement("a");
          open.href = String(payload.url);
          open.target = "_blank";
          open.rel = "noopener";
          open.textContent = "Open the sign-in page";
          note.append(open, "; this page updates by itself.");
        }
        // The browser comes back to /callback, not to this page: look for the link until it is there.
        if (linkWatch) clearInterval(linkWatch);
        const started = Date.now();
        linkWatch = setInterval(async () => {
          if (Date.now() - started > 10 * 60 * 1000) { clearInterval(linkWatch); linkWatch = null; return; }
          await loadAgents();
        }, 2000);
      } catch (error) {
        if (tab) tab.close();
        message.hidden = false;
        message.className = "agents-message bad";
        message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });

    byId("link-signout").addEventListener("click", async () => {
      const button = byId("link-signout");
      const message = byId("agents-message");
      button.disabled = true;
      try {
        const response = await fetch("/api/link/signout", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: "{}",
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "The sign-out did not go through.");
        renderAgents(payload.agents, payload.auto_connect ?? null, payload.storage_mode);
        renderLink(payload);
        message.hidden = false;
        message.className = "agents-message";
        message.textContent = payload.signed_out?.revoked
          ? "Signed out. The plugin's sign-in to your hosted account was ended on every computer using it; your memories there were not changed."
          : payload.signed_out?.reached
            ? "Signed out here. Your hosted account did not confirm ending the sign-in, so it may still count there until it expires or you end it from your account page."
            : "Signed out here. Your hosted account could not be reached, so the sign-in still counts there until it expires or you end it from your account page.";
      } catch (error) {
        message.hidden = false;
        message.className = "agents-message bad";
        message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });

    async function decide(enabled) {
      const message = byId("agents-message");
      const buttons = [byId("agents-yes"), byId("agents-no"), byId("agents-auto-off")];
      buttons.forEach((button) => { button.disabled = true; });
      message.hidden = false;
      message.className = "agents-message";
      message.textContent = enabled ? "Connecting your other assistants. This can take a minute each." : "";
      message.hidden = !enabled;
      try {
        const response = await fetch("/api/agents/decision", {
          method: "POST",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
            "X-MemorySafe-Setup-Token": localApiToken,
          },
          body: JSON.stringify({ auto_connect: enabled }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "Your answer could not be saved.");
        const results = Array.isArray(payload.results) ? payload.results : [];
        if (results.length) {
          message.hidden = false;
          message.className = payload.ok ? "agents-message" : "agents-message bad";
          message.textContent = results.map((result) => String(result.message ?? "")).join(" ");
        } else {
          // Nothing left to connect -- the list the question was asked from had gone stale.
          // "Connecting..." must not stay up as if work were still running.
          message.hidden = true;
          message.textContent = "";
        }
        renderAgents(payload.agents, payload.auto_connect ?? null);
      } catch (error) {
        message.hidden = false;
        message.className = "agents-message bad";
        message.textContent = error.message;
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    }

    byId("agents-yes").addEventListener("click", () => decide(true));
    byId("agents-no").addEventListener("click", () => decide(false));
    byId("agents-auto-off").addEventListener("click", () => decide(false));

    async function connectAgent(agent, button) {
      const message = byId("agents-message");
      button.disabled = true;
      button.textContent = "Connecting…";
      message.hidden = false;
      message.className = "agents-message";
      message.textContent = `Installing MemorySafe in ${agent.label}. This can take a minute.`;
      try {
        const response = await fetch("/api/agents/connect", {
          method: "POST",
          cache: "no-store",
          headers: {
            "Content-Type": "application/json",
            "X-MemorySafe-Setup-Token": localApiToken,
          },
          body: JSON.stringify({ agent: agent.id }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? `${agent.label} could not be connected.`);
        message.className = payload.ok ? "agents-message" : "agents-message bad";
        message.textContent = String(payload.result?.message ?? "");
        renderAgents(payload.agents, payload.auto_connect ?? null);
      } catch (error) {
        message.className = "agents-message bad";
        message.textContent = error.message;
        button.disabled = false;
        button.textContent = "Connect";
      }
    }

    byId("refresh").addEventListener("click", async () => {
      const button = byId("refresh");
      button.disabled = true;
      button.textContent = "Refreshing…";
      loadAgents();
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

    // Report a problem used to stop at a ZIP: no destination, and nowhere to say what had
    // happened, so a tester with a problem had nothing to do with it. It now asks what
    // went wrong, saves the bundle, and opens an email to support that the person reviews,
    // attaches the file to and sends. Nothing is sent without them.
    byId("support-bundle").addEventListener("click", () => {
      const form = byId("report-form");
      form.hidden = !form.hidden;
      if (!form.hidden) {
        byId("support-result").textContent = "";
        byId("report-description").focus();
      }
    });
    byId("report-cancel").addEventListener("click", () => { byId("report-form").hidden = true; });

    byId("hosted-export").addEventListener("click", async () => {
      const result = byId("hosted-result");
      const button = byId("hosted-export");
      result.className = "support-result";
      result.textContent = "Exporting…";
      button.disabled = true;
      try {
        const response = await fetch("/api/export", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: "{}",
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "The export could not be written");
        const fileName = String(payload?.file_name ?? "");
        const download = await fetch("/api/export/download", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: JSON.stringify({ name: fileName }),
        });
        if (!download.ok) throw new Error("The export could not be downloaded");
        const link = document.createElement("a");
        link.href = URL.createObjectURL(await download.blob());
        link.download = fileName;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 60000);
        result.replaceChildren();
        const text = document.createElement("span");
        text.textContent = `${payload.count} memories saved to your Downloads as ${fileName}. Next: open `;
        const anchor = document.createElement("a");
        anchor.href = "https://memory.memorysafe.ca/account/import";
        anchor.target = "_blank";
        anchor.rel = "noopener";
        anchor.textContent = "memory.memorysafe.ca/account/import";
        const tail = document.createElement("span");
        tail.textContent = " and choose that file. Delete the file when you are done.";
        result.append(text, anchor, tail);
      } catch (error) {
        result.className = "support-result bad";
        result.textContent = error instanceof Error ? error.message : String(error);
      } finally {
        button.disabled = false;
      }
    });

    // The way back from Hosted: the account page's move file, read here in the browser and
    // handed to /api/import as its body. No path reaches the server; the import runs every
    // memory through remember(), so the result says what merged or needs a decision.
    async function sendPlan(body) {
      const result = byId("plan-result");
      result.className = "support-result";
      result.textContent = "";
      try {
        const response = await fetch("/api/plan", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "The plan key could not be saved");
        byId("plan-key").value = "";
        renderPlan(payload.local_plan ?? null);
        result.textContent = body.remove ? "The key was removed." : "The key was accepted.";
      } catch (error) {
        result.className = "support-result bad";
        result.textContent = error instanceof Error ? error.message : String(error);
      }
    }
    byId("plan-save").addEventListener("click", () => {
      const key = byId("plan-key").value.trim();
      if (key) sendPlan({ key });
    });
    byId("plan-remove").addEventListener("click", () => sendPlan({ remove: true }));

    const importInput = byId("hosted-import-file");
    byId("hosted-import").addEventListener("click", () => { importInput.value = ""; importInput.click(); });
    importInput.addEventListener("change", async () => {
      const file = importInput.files && importInput.files[0];
      if (!file) return;
      const result = byId("hosted-import-result");
      const button = byId("hosted-import");
      result.className = "support-result";
      result.textContent = `Importing ${file.name}…`;
      button.disabled = true;
      try {
        const text = await file.text();
        try { JSON.parse(text); } catch (_error) { throw new Error("This is not a MemorySafe export file."); }
        const response = await fetch("/api/import", {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
          body: text,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.error ?? "The file could not be imported");
        const parts = [`Imported ${payload.total} memories: ${payload.stored} new, ${payload.merged} merged with ones already here.`];
        if (payload.replaced_older) parts.push(`${payload.replaced_older} replaced an older memory (still restorable).`);
        if (payload.needs_review) parts.push(`${payload.needs_review} may conflict with another memory; see the conflicts above.`);
        if (payload.protected) parts.push(`${payload.protected} kept the protection they had.`);
        if (payload.failed) parts.push(`${payload.failed} could not be imported.`);
        parts.push("Delete the file when you are done.");
        result.textContent = parts.join(" ");
        refresh();
      } catch (error) {
        result.className = "support-result bad";
        result.textContent = error instanceof Error ? error.message : String(error);
      } finally {
        button.disabled = false;
      }
    });
    byId("report-send").addEventListener("click", async () => {
      const button = byId("report-send");
      const result = byId("support-result");
      const description = byId("report-description").value;
      button.disabled = true;
      button.textContent = "Creating…";
      result.className = "support-result";
      // A retry must not leave the last attempt's message up, restyled, while this one runs.
      result.textContent = "";
      try {
        const payload = await request("tools/call", { name: "memorysafe_support_bundle", arguments: { description } });
        const fileName = String(payload?.file_name ?? "");
        const savedAt = String(payload?.path ?? "the local support folder");
        let downloaded = false;
        // The bundle is written under MemorySafe's own data folder, which on Windows is a
        // hidden AppData path (inside the Store app's container, for Claude Desktop) that
        // nobody finds. Handing it to the browser puts it in Downloads, where people look.
        if (standalone && fileName) {
          try {
            const response = await fetch("/api/support-bundle/download", {
              method: "POST",
              cache: "no-store",
              headers: { "Content-Type": "application/json", "X-MemorySafe-Setup-Token": localApiToken },
              body: JSON.stringify({ name: fileName }),
            });
            if (response.ok) {
              const link = document.createElement("a");
              link.href = URL.createObjectURL(await response.blob());
              link.download = fileName;
              document.body.append(link);
              link.click();
              link.remove();
              setTimeout(() => URL.revokeObjectURL(link.href), 60000);
              downloaded = true;
            }
          } catch (_) {
            // Fall through to naming the folder it was saved in.
          }
        }
        // The page can't tell whether the browser kept the file: Safari may ask first, and a
        // browser set to ask where to save can be cancelled. So the copy on disk stays named.
        const where = downloaded
          ? `your Downloads folder (${fileName}; if it isn't there, a copy is at ${savedAt})`
          : savedAt;
        const email = payload?.email;
        // Only ever a mailto: link, never another scheme, whatever the payload says.
        if (typeof email?.mailto === "string" && email.mailto.startsWith("mailto:")) {
          const lead = document.createElement("strong");
          lead.textContent = "Almost done. ";
          const again = document.createElement("a");
          again.href = email.mailto;
          again.textContent = `No email appeared? Open it again, or write to ${email.to}.`;
          result.replaceChildren(
            lead,
            document.createTextNode(
              `An email to ${email.to} has opened. Attach the report from ${where}, then press Send. ` +
              // The description the person typed is in the report too, as what-went-wrong.txt.
              "It holds status, counts, sanitized error signatures and what you typed: no memories, no conversations, no keys. Nothing is sent until you send it. "
            ),
            again,
          );
          const open = document.createElement("a");
          open.href = email.mailto;
          document.body.append(open);
          open.click();
          open.remove();
        } else {
          result.textContent = `Support bundle saved to ${where}. It holds no memories, conversations or keys, and nothing was uploaded.`;
        }
        byId("report-form").hidden = true;
        byId("report-description").value = "";
      } catch (error) {
        // A fetch that never reached the dashboard throws a TypeError, and an answer from
        // something else on the port fails to parse. Anything else is the dashboard's own
        // reason, such as a session that expired when it restarted: reloading the page fixes
        // that, and restarting the assistant does not.
        const unreachable = error instanceof TypeError || error instanceof SyntaxError;
        result.className = "support-result bad";
        result.textContent = `The report could not be created. No information was uploaded. ${
          unreachable ? "The dashboard may have stopped: restart your assistant and try again, or write to contact@memorysafe.ca." : String(error?.message ?? "")
        }`;
      } finally {
        button.disabled = false;
        button.textContent = "Create report and email it";
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
    document = document.replace("__LOCAL_API_TOKEN__", json.dumps(local_api_token))
    if hosted:
        document = _hosted_wording(document, account_url or "")
    return document


# Each pair is (local text, hosted text). Applied only to the hosted page, so the local
# page stays byte-identical (tests/fixtures/dashboard_v3_local.html pins it). A pair that
# no longer matches fails loudly instead of leaving "this computer" on a remote page.
_HOSTED_WORDING = (
    ("Private local memory governance", "Private memory governance"),
    ('id="live-label">LOCAL · PRIVATE</div>', 'id="live-label">MEMORYSAFE CLOUD</div>'),
    ("`LOCAL · PRIVATE · ${String(data.version)}`", "`MEMORYSAFE CLOUD · ${String(data.version)}`"),
    ('id="agents-note">ON THIS COMPUTER</span>', 'id="agents-note">YOUR ASSISTANTS</span>'),
    (
        'id="token-model">Estimated from tokens counted on this computer. Not anyone’s billed usage.</p>',
        'id="token-model">Not available</p>',
    ),
    (
        'setText("token-model", "Estimated from tokens counted on this computer. Not anyone’s billed usage.");',
        'setText("token-model", String(data.token_estimate?.note ?? "Not available"));',
    ),
    (
        "const liveTokens = data.live_token_metrics ?? {};",
        "const liveTokens = data.live_token_metrics ?? data.token_estimate ?? {};",
    ),
    (
        '<p class="store-path">Reading <code id="database-path">—</code></p>',
        '<p class="store-path"><code id="database-path">Stored in MemorySafe cloud</code>'
        ' · <a id="manage-link" href="__ACCOUNT_HREF__">Manage on the web</a></p>',
    ),
    (
        'setText("database-path", String(data.database_path ?? "unknown store"));',
        'setText("database-path", String(data.stored_in ?? "Stored in MemorySafe cloud"));\n'
        "      const manageLink = byId(\"manage-link\");\n"
        "      if (manageLink && /^https:\\/\\//.test(accountUrl)) manageLink.href = accountUrl;",
    ),
    ("const localApiToken = ", "const accountUrl = __ACCOUNT_URL__;\n    const localApiToken = "),
    # 0.4.27's Move to Hosted panel is for local users; on Hosted its export fetch has no
    # server in a host's sandbox. Hidden, not removed: the script binds #hosted-export at
    # load, and a missing element would throw and stop the whole page.
    (
        '<section class="panel hosted-panel" id="hosted-panel" aria-label="Take your memory everywhere">',
        '<section class="panel hosted-panel" id="hosted-panel" aria-label="Take your memory everywhere" hidden>',
    ),
    (
        '<p class="hosted-text">Hosted gives every assistant you use, on every device, this same memory. '
        "Export a copy here, then import it into your Hosted account; nothing leaves this computer "
        "until you upload the file yourself.</p>",
        '<p class="hosted-text"></p>',
    ),
    # The storage-mode chooser stays hidden on the hosted page (renderAgents never runs
    # there), but its static label must not call the device a computer the page is not on.
    (">On this computer</button>", ">On this device</button>"),
    ("on this computer", "on this device"),
)


def _hosted_wording(document: str, account_url: str) -> str:
    for local, hosted in _HOSTED_WORDING:
        if local not in document:
            raise AssertionError(f"hosted wording no longer matches: {local[:50]!r}")
        document = document.replace(local, hosted)
    # json.dumps leaves "</script>" and "<!--" intact, so a URL could close the tag the
    # constant sits in. \u003c and friends are the same string to JavaScript.
    encoded = (
        json.dumps(account_url).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    # The href attribute is for readers without script; only https is ever linked.
    href = html.escape(account_url, quote=True) if account_url.startswith("https://") else "#"
    return document.replace("__ACCOUNT_URL__", encoded).replace("__ACCOUNT_HREF__", href)


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
      font: 16px/1.4 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
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
    .brand strong { display: block; font-size: 16px; letter-spacing: -.3px; }
    .brand span { display: block; color: var(--muted); font-size: 9px; }
    .live { margin-left: auto; color: #a6d9b8; font: 700 14px/1 ui-monospace, Menlo, monospace; letter-spacing: .08em; }
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
    .score-value strong { display: block; font: 800 22px/1 ui-monospace, Menlo, monospace; }
    .score-value span { display: block; margin-top: 3px; color: var(--muted); font-size: 7px; letter-spacing: .05em; }
    .hero-copy { min-width: 0; flex: 1; }
    .hero-copy strong { display: block; font-size: 14px; }
    .hero-copy p { margin: 3px 0 0; color: var(--muted); font-size: 10px; }
    .fresh { display: inline-block; margin-top: 6px; padding: 2px 7px; border-radius: 999px;
      font: 800 14px ui-monospace, Menlo, monospace; letter-spacing: .04em; border: 1px solid transparent; }
    .fresh.active { color: var(--green); border-color: rgba(82,220,136,.4); background: rgba(82,220,136,.1); }
    .fresh.quiet { color: var(--amber); border-color: rgba(244,183,94,.4); background: rgba(244,183,94,.1); }
    .fresh.stale, .fresh.never { color: var(--pink); border-color: rgba(255,76,133,.45); background: rgba(255,76,133,.12); }
    .metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
    .metric { padding: 9px 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); min-width: 0; }
    .metric span { display: block; color: var(--muted); font-size: 8px; }
    .metric strong { display: block; margin-top: 3px; font: 800 18px/1 ui-monospace, Menlo, monospace; }
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
      font: 800 14px ui-monospace, Menlo, monospace;
    }
    .toggle.on { border-color: rgba(82,220,136,.45); background: rgba(82,220,136,.1); color: var(--green); }
    .toggle:disabled { opacity: .45; }
    .memories { flex: 1; min-height: 0; padding: 10px 11px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .memories h2 { margin: 0 0 8px; font-size: 11px; display: flex; justify-content: space-between; }
    .memories h2 span { color: var(--dim); font: 700 14px ui-monospace, Menlo, monospace; }
    .row { display: grid; grid-template-columns: 7px 1fr; gap: 8px; align-items: start; padding: 7px 0;
      border-top: 1px solid rgba(190,218,245,.06); }
    .row:first-of-type { border-top: 0; }
    .dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--blue); }
    .row.protected .dot { background: var(--cyan); box-shadow: 0 0 6px rgba(25,228,233,.55); }
    .row p { margin: 0; font-size: 11px; color: #dce5ed; overflow-wrap: anywhere; white-space: pre-line; }
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
      <div class="brand"><strong>MemorySafe</strong><span>On this computer</span></div>
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
      // An empty store has no score: 100 there made the first good memory look like a loss.
      const scored = data.memory_health !== null && data.memory_health !== undefined;
      const health = scored ? Math.round(n(data.memory_health)) : 0;
      byId("score").textContent = scored ? String(health) : "—";
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
        // A memory saved by hand counts as well, so this says when, never "capturing".
        fresh.textContent =
          state === "active" ? (n(data.days_since_last_capture) === 1 ? "SAVED YESTERDAY" : "SAVED TODAY")
          : state === "never" ? "NOTHING SAVED YET"
          : `LAST SAVED ${n(data.days_since_last_capture)}D AGO`;
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
