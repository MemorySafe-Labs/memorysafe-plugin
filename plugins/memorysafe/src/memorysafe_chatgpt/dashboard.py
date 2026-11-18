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
    /* The brand guide's dark set (17 Nov 2026). */
    :root {
      --bg: #0e1420; --surface: #141b2a; --surface-2: #1c2536; --border: #263249; --inner-line: #263249;
      --text: #f8fafc; --muted: #94a3b8; --dim: #94a3b8;
      --accent: #93c5fd; --accent-2: #60a5fa; --kicker: #94a3b8; --rule: #60a5fa; --link: #93c5fd;
      --btn-bg: #e0f2fe; --btn-text: #0b1220; --btn-hover: #bfdbfe;
      --ok: #93c5fd; --ok-line: rgba(147,197,253,.4); --ok-bg: rgba(147,197,253,.08);
      --warn: #fcd34d; --warn-line: rgba(252,211,77,.4); --warn-bg: rgba(252,211,77,.08);
      --bad: #fca5a5; --bad-line: rgba(252,165,165,.45); --bad-bg: rgba(252,165,165,.08); --bad-solid: #b91c1c;
      --tint: rgba(147,197,253,.07); --tint-line: rgba(147,197,253,.4); --track: #263249; --pill: #1c2536;
      --sans: "Inter", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 0;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.45 "Inter", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button { font: inherit; }
    .shell { margin: 0 auto; max-width: 980px; padding: 28px 22px 56px; }
    .topline { display: flex; align-items: center; gap: 10px; padding-bottom: 8px; }
    .live { display: flex; align-items: center; gap: 6px; margin-left: 0; color: var(--muted); font: 600 14px/1 var(--mono); letter-spacing: .09em; text-transform: uppercase; padding: 9px 13px; border: 1px solid var(--border); border-radius: 999px; background: var(--pill); }
    .live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
    .refresh, .setup-link, .support-bundle { cursor: pointer; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text); padding: 9px 14px; font-size: 14px; font-weight: 600; }
    .setup-link, .support-bundle { display: none; text-decoration: none; }
    .refresh:hover, .setup-link:hover, .support-bundle:hover { border-color: var(--accent); color: var(--text); }
    .refresh:disabled { opacity: .45; cursor: wait; }
    .support-result { margin: 0 0 10px; padding: 10px 12px; border: 1px solid var(--ok-line); border-radius: 9px; font-size: 15px; overflow-wrap: anywhere; background: var(--ok-bg); color: var(--ok); }
    /* Collapsed rather than display:none. Screen readers only announce a live region that
       was already in the page when its text changed, so this one is never taken out. */
    .support-result:empty { margin: 0; padding: 0; border: 0; }
    .support-result.bad { border-color: var(--warn-line); background: var(--warn-bg); color: var(--warn); }
    .support-result a { color: var(--accent); }
    .hosted-text { margin: 0 0 10px; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .hosted-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin: 0 0 10px; }
    .plan-key { flex: 1 1 280px; min-width: 0; padding: 9px 11px; border: 1px solid var(--border); border-radius: 9px; background: transparent; color: inherit; font: inherit; }
    .report-form { margin: 0 0 10px; padding: 11px 12px; border: 1px solid var(--tint-line); background: var(--tint); border-radius: 12px; }
    .report-form label { display: block; font-size: 15px; font-weight: 700; color: var(--text); }
    .report-form label span { display: block; margin-top: 3px; color: var(--dim); font-size: 14px; font-weight: 400; }
    .report-form textarea { display: block; width: 100%; margin: 8px 0; padding: 8px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-2); color: var(--text); font-family: inherit; font-size: 15px; line-height: 1.45; resize: vertical; }
    .report-form textarea:focus { outline: none; border-color: var(--accent); }
    .report-actions { display: flex; gap: 7px; flex-wrap: wrap; }
    .hero { margin-top: 10px; display: grid; grid-template-columns: 1fr auto; gap: 20px; align-items: center; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); padding: 26px 28px; }
    .eyebrow { display: flex; align-items: center; gap: 10px; color: var(--kicker); font: 600 14px/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase; margin-bottom: 10px; }
    h1 { line-height: 1.1; font-size: 28px; font-weight: 800; letter-spacing: -.03em; margin: 4px 0 8px; }
    .hero p { margin: 0; font-size: 16px; max-width: 480px; color: var(--muted); }
    .auto-mode { margin-top: 13px; display: flex; align-items: center; gap: 12px; max-width: 520px; border: 1px solid var(--inner-line); background: var(--surface-2); border-radius: 12px; padding: 14px 16px; }
    .auto-copy { min-width: 0; flex: 1; }
    .auto-copy strong { display: block; font-size: 15px; }
    .auto-copy span { display: block; margin-top: 2px; font-size: 14px; color: var(--muted); }
    .auto-copy small { display: block; margin-top: 5px; font-size: 14px; line-height: 1.35; color: var(--dim); }
    /* Liveness sits next to the score on purpose. The score cannot fall when capture
       stops, so a stale store otherwise reads as a healthy one. */
    .capture-freshness[hidden] { display: none; }
    .capture-freshness { margin-top: 6px; border-radius: 999px; width: fit-content; border: 1px solid transparent; font: 600 14px var(--mono); letter-spacing: .09em; padding: 5px 11px; }
    .capture-freshness.active { color: var(--ok); border-color: var(--ok-line); background: var(--ok-bg); }
    .capture-freshness.quiet { color: var(--warn); border-color: var(--warn-line); background: var(--warn-bg); }
    .capture-freshness.stale,
    .capture-freshness.never { color: var(--bad); border-color: var(--bad-line); background: var(--bad-bg); }
    .capture-freshness.unknown { color: var(--dim); border-color: var(--border); }
    .auto-counts { white-space: nowrap; color: var(--dim); font: 600 14px var(--mono); letter-spacing: .06em; }
    .auto-toggle { min-width: 50px; border-radius: 999px; cursor: pointer; border: 1.5px solid var(--border); background: var(--surface); color: var(--muted); font: 700 14px var(--mono); padding: 8px 15px; }
    .auto-toggle.on { border-color: var(--btn-bg); background: var(--btn-bg); color: var(--btn-text); }
    .auto-toggle:disabled { opacity: .45; cursor: wait; }
    /* A visible track matters more than the arc: every new store sits near zero, and
       a 10% arc on a faint track just reads as an empty hole in the layout. */
    .score { --score: 0; width: 176px; height: 176px; display: grid; place-items: center; border-radius: 50%; position: relative; background: conic-gradient(var(--accent) calc(var(--score) * 1%), var(--track) 0); }
    .score::before { content: ""; position: absolute; inset: 7px; border-radius: inherit; background: var(--surface); }
    .score-value { position: relative; text-align: center; }
    .score-value strong { display: block; font: 800 34px/1 var(--sans); letter-spacing: -.03em; }
    .score-value span { display: block; margin-top: 4px; max-width: 118px; font: 600 14px/1.25 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
    .metrics { margin-top: 10px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .metric { min-width: 0; border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; background: var(--surface); }
    .metric span { display: block; font-size: 14px; color: var(--muted); }
    .metric strong { display: block; font: 800 27px/1.05 var(--sans); letter-spacing: -.03em; color: var(--text); margin: 8px 0 4px; }
    .metric small { font-size: 14px; color: var(--dim); }
    .metric-cyan strong { color: var(--text); }
    .metric-blue strong { color: var(--text); }
    .metric-green strong { color: var(--text); }
    .content-grid { margin-top: 10px; display: grid; grid-template-columns: .9fr 1.1fr; gap: 10px; }
    .panel { border: 1px solid var(--border); min-width: 0; border-radius: 16px; background: var(--surface); padding: 26px 28px; }
    .step-label { display: flex; align-items: center; gap: 10px; color: var(--kicker); font: 600 14px/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase; margin-bottom: 10px; }
    .storage-panel { margin-top: 10px; }
    .panel-title { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 11px; }
    .panel-title strong { font-size: 21px; font-weight: 800; letter-spacing: -.02em; }
    .panel-title span { color: var(--dim); font: 600 14px var(--mono); letter-spacing: .09em; text-transform: uppercase; }
    .compare { display: grid; grid-template-columns: 1fr 18px 1fr; align-items: stretch; gap: 7px; }
    .compare-card { padding: 12px; border: 1px solid var(--inner-line); background: var(--surface-2); border-radius: 12px; }
    .compare-card.with { border-color: var(--tint-line); background: var(--tint); }
    .compare-card span { font-size: 14px; color: var(--muted); }
    .compare-card strong { display: block; margin-top: 6px; font: 800 27px/1.05 var(--sans); letter-spacing: -.03em; color: var(--text); margin: 8px 0 4px; }
    .compare-card small { display: block; margin-top: 5px; font-size: 14px; color: var(--dim); }
    .compare-card.with strong { color: var(--accent); }
    .arrow { display: grid; place-items: center; font-size: 17px; color: var(--accent); }
    .savings { margin-top: 9px; display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .saving { padding: 9px; border-radius: 9px; border: 1px solid var(--ok-line); background: var(--ok-bg); }
    .saving strong { display: block; font: 800 16px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ok); }
    .saving span { font-size: 14px; color: var(--muted); }
    .memory-list { display: grid; gap: 7px; }
    .memory { display: grid; grid-template-columns: 8px 1fr auto; gap: 9px; align-items: start; background: var(--surface-2); border: 1px solid var(--inner-line); border-radius: 12px; padding: 13px 16px; }
    .memory-dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--accent-2); }
    .memory.protected .memory-dot { background: var(--accent); }
    .memory-copy { min-width: 0; }
    .memory-copy p { margin: 0; font-size: 15px; overflow-wrap: anywhere; white-space: pre-line; color: var(--text); }
    .memory-copy span { display: block; margin-top: 4px; font-size: 14px; color: var(--dim); }
    .priority { color: var(--muted); font: 600 14px var(--mono); }
    .store-path { margin: 9px 0 0; font-size: 14px; color: var(--dim); }
    .store-path code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; color: var(--muted); }
    .memory-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
    .memory-forget { font: 600 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .09em; text-transform: uppercase; padding: 3px 7px; cursor: pointer; border: 1px solid var(--border); color: var(--dim); background: transparent; border-radius: 8px; }
    .memory-forget:hover { color: var(--bad); border-color: var(--bad-line); }
    .memory-forget.confirm { color: #fff; background: var(--bad-solid); border-color: var(--bad-solid); }
    .memory-forget:disabled { opacity: .5; cursor: default; }
    .memory-forget:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .empty { padding: 19px 10px; text-align: center; color: var(--muted); font-size: 15px; border: 1px dashed var(--border); border-radius: 9px; }
    .agents-panel { margin-top: 17px; }
    .agent { display: grid; grid-template-columns: 1fr auto; gap: 9px; align-items: center; background: var(--surface-2); border: 1px solid var(--inner-line); border-radius: 12px; padding: 13px 16px; }
    .agent-copy { min-width: 0; }
    .agent-name { display: block; font-size: 15px; font-weight: 700; color: var(--text); }
    .agent-note { display: block; margin-top: 4px; font-size: 14px; overflow-wrap: anywhere; color: var(--dim); }
    .agent-state { white-space: nowrap; font: 600 14px var(--mono); letter-spacing: .09em; padding: 6px 11px; border-radius: 999px; }
    .agent-state.on { color: var(--ok); border: 1px solid var(--ok-line); background: var(--ok-bg); }
    .agent-state.off { color: var(--warn); border: 1px solid var(--warn-line); background: var(--warn-bg); }
    .agent-connect { font-family: inherit; font-size: 14px; font-weight: 600; line-height: 1.1; cursor: pointer; white-space: nowrap; border: 1.5px solid var(--btn-bg); background: var(--btn-bg); color: var(--btn-text); border-radius: 10px; padding: 10px 16px; }
    .agent-connect:hover { background: var(--btn-hover); border-color: var(--btn-hover); }
    .agent-connect:disabled { opacity: .5; cursor: wait; }
    .agent-connect:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .agents-missing { margin: 9px 0 0; color: var(--dim); font-size: 14px; }
    .agents-ask { margin-bottom: 9px; padding: 11px 12px; border: 1px solid var(--tint-line); background: var(--tint); border-radius: 12px; }
    .agents-ask p { margin: 0 0 9px; font-size: 15px; color: var(--text); }
    .agents-ask-actions { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
    .agents-ask small { display: block; margin-top: 8px; color: var(--dim); font-size: 14px; }
    .agents-no, .agents-link { font-family: inherit; font-size: 14px; font-weight: 600; line-height: 1.1; text-decoration: none; padding: 9px 14px; cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: 10px; }
    .agents-no:hover, .agents-link:hover { border-color: var(--accent); color: var(--text); }
    .agents-link { margin-left: 4px; }
    .agents-auto { margin: 9px 0 0; font-size: 14px; color: var(--dim); }
    .agents-mode { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 12px; }
    .agents-mode-label { color: var(--dim); font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
    .agents-mode-choice { text-align: left; font: inherit; cursor: pointer; background: var(--surface); border: 1.5px solid var(--border); border-radius: 14px; padding: 18px 20px; color: var(--text); }
    .agents-mode-choice strong { display: block; margin-bottom: 4px; font-size: 16.5px; }
    .agents-mode-choice span { display: block; font-size: 14px; line-height: 1.45; color: var(--muted); }
    .agents-mode-choice em { display: inline-block; margin-top: 10px; visibility: hidden; text-transform: uppercase; color: var(--accent); font: 600 14px var(--mono); letter-spacing: .09em; }
    .agents-mode-choice.on em { visibility: visible; }
    .agents-mode-choice:hover { border-color: var(--accent); }
    .agents-mode-choice.on { cursor: default; border-color: var(--accent); background: var(--tint); }
    .agents-mode-choice:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .agents-hosted { margin: 0 0 9px; padding: 11px 12px; border-radius: 9px; border: 1px solid var(--border); font-size: 14px; color: var(--dim); }
    .agents-hosted p { margin: 0; }
    .agents-hosted a { color: var(--link); }
    .agents-hosted #agents-local-count { margin: 8px 0 0; color: var(--muted); }
    .device-link { margin: 10px 0 0; padding-top: 10px; border-top: 1px solid var(--border); }
    .device-link p { margin: 0 0 8px; color: var(--text); font-size: 15px; }
    .device-link small { display: block; margin-top: 6px; color: var(--muted); font-size: 14px; line-height: 1.4; }
    .agents-message { margin: 9px 0 0; font-size: 14px; overflow-wrap: anywhere; color: var(--ok); }
    .agents-message.bad { color: var(--warn); }
    .token-panel { margin-top: 10px; }
    .token-badge { letter-spacing: .08em; color: var(--dim) !important; font: 600 14px var(--mono) !important; }
    .token-live-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .token-live-stat { padding: 11px 12px; border: 1px solid var(--inner-line); min-width: 0; background: var(--surface-2); border-radius: 12px; }
    .token-live-stat span { display: block; font-size: 14px; color: var(--muted); }
    .token-live-stat strong { display: block; font: 800 27px/1.05 var(--sans); letter-spacing: -.03em; color: var(--text); margin: 8px 0 4px; }
    .token-live-stat small { font-size: 14px; color: var(--dim); }
    .gov-item { padding: 11px 1px; border-bottom: 1px solid var(--border); }
    .gov-item:last-child { border-bottom: 0; }
    .gov-head { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; flex-wrap: wrap; }
    .gov-tag { font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; padding: 3px 7px; border-radius: 4px; }
    .gov-supersede { background: var(--warn-bg); color: var(--warn); }
    .gov-restore { background: var(--ok-bg); color: var(--ok); }
    .gov-review { background: var(--tint); color: var(--accent); }
    .gov-when { font: 500 15px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--dim); }
    .gov-reason { font-size: 16px; line-height: 1.45; margin-bottom: 8px; color: var(--text); }
    .gov-pair { display: grid; gap: 5px; }
    .gov-line { display: grid; grid-template-columns: 62px 1fr; gap: 9px; align-items: baseline; font-size: 16px; line-height: 1.4; }
    .gov-label { font: 700 14px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .07em; padding-top: 2px; color: var(--dim); }
    .gov-out { text-decoration: line-through; text-decoration-color: var(--border); color: var(--dim); }
    .gov-in { color: var(--text); }
    .token-section-label { display: flex; align-items: center; gap: 9px; margin: 12px 1px 8px; letter-spacing: .08em; color: var(--dim); font: 600 14px var(--mono); }
    .token-section-label::after { content: ""; height: 1px; flex: 1; background: var(--border); }
    .token-grid { display: grid; grid-template-columns: .72fr .72fr 1.28fr 1.28fr; gap: 8px; }
    .token-stat, .token-saving { padding: 12px; border: 1px solid var(--inner-line); min-width: 0; background: var(--surface-2); border-radius: 12px; }
    .token-stat span, .token-saving span { display: block; font-size: 14px; color: var(--muted); }
    .token-stat strong { display: block; font: 800 27px/1.05 var(--sans); letter-spacing: -.03em; color: var(--text); margin: 8px 0 4px; }
    .token-stat small { font-size: 14px; color: var(--dim); }
    .token-saving-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
    .token-saving-head strong { font: 800 17px/1 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--ok); }
    .token-bar { height: 5px; margin-top: 10px; overflow: hidden; border-radius: 999px; background: var(--track); }
    .token-bar i { display: block; width: 0; height: 100%; border-radius: inherit; transition: width .35s ease; background: var(--accent); }
    .token-note { margin: 9px 1px 0; font-size: 14px; color: var(--dim); }
    .token-note strong { color: var(--warn); }
    .formula { margin-top: 10px; padding: 10px 12px; display: flex; gap: 9px; align-items: flex-start; border: 1px solid var(--border); border-radius: 10px; font-size: 14px; background: var(--surface-2); color: var(--muted); }
    .formula strong { flex: 0 0 auto; color: var(--warn); }
    .error { margin-top: 12px; padding: 10px 12px; border-radius: 9px; display: none; background: var(--bad-bg); color: var(--bad); }
    .notice { margin-top: 12px; display: none; background: var(--tint); border: 1px solid var(--tint-line); color: var(--text); border-radius: 12px; padding: 14px 18px; font-size: 15px; }
    .notice a { color: var(--link); }
    /* Brand guide, 17 Nov 2026: rules for selectors that had none of their own. */
    .brand-logo { display: block; margin-right: auto; }
    .brand-logo svg { display: block; height: 40px; width: auto; }
    .step-label::before, .eyebrow::before { content: ""; width: 22px; height: 2px; background: var(--rule); }
    a, a:visited { color: var(--link); }
    @media (max-width: 620px) {
      .shell { padding: 12px; }
      .topline { flex-wrap: wrap; }
      .brand-logo { flex: 1; }
      .live { display: none; }
      .hero { grid-template-columns: 1fr; gap: 14px; padding: 18px 16px; }
      .panel { padding: 18px 16px; }
      .metric { padding: 14px; }
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
      .gov-action { border: 1px solid var(--border); background: transparent; font: 600 14px ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 7px 13px; cursor: pointer; color: var(--text); border-radius: 10px; }
      .gov-action:hover { border-color: var(--accent); color: var(--accent); }
      .gov-action.confirm { color: var(--btn-text); background: var(--btn-bg); border-color: var(--btn-bg); }
      .gov-action:disabled { opacity: .5; cursor: default; }
      .gov-action:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
      .gov-help { flex-basis: 100%; color: var(--muted); font-size: 14px; line-height: 1.4; min-height: 1.4em; }
      .gov-error { flex-basis: 100%; font-size: 14px; color: var(--bad); }
      .fold-panel { margin-top: 10px; }
      .fold-panel > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
      .fold-panel > summary::-webkit-details-marker { display: none; }
      .fold-panel > summary strong { font-size: 17px; font-weight: 700; }
      .fold-panel > summary strong::before { content: "\25B8"; display: inline-block; width: 14px; transition: transform .15s; color: var(--dim); }
      .fold-panel[open] > summary strong::before { transform: rotate(90deg); }
      .fold-panel > summary span { color: var(--dim); font: 600 14px var(--mono); letter-spacing: .09em; text-transform: uppercase; }
      .fold-panel[open] > summary { margin-bottom: 11px; }
      .fold-panel > summary span.needs { color: var(--warn); }
      .content-grid { grid-template-columns: 1fr; }
      details.tech { margin-top: 18px; border-top: 1px solid var(--border); padding-top: 12px; }
      details.tech summary { cursor: pointer; text-transform: uppercase; font: 600 14px var(--mono); letter-spacing: .1em; color: var(--dim); opacity: 1; }
      details.tech p { font-size: 16px; opacity: .65; line-height: 1.6; margin: 10px 0 0; }
    </style>
</head>
<body>
  <main class="shell">
    <header class="topline">
      <span class="brand-logo"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 528 112" role="img" aria-label="MemorySafe Labs">
<g transform="translate(8.0,8.0) rotate(-6 48 48)"><circle cx="16" cy="16" r="8" fill="#3B82F6"/><circle cx="16" cy="37.3" r="8" fill="#3B82F6"/><circle cx="16" cy="58.7" r="8" fill="#3B82F6"/><circle cx="16" cy="80" r="8" fill="#3B82F6"/><circle cx="37.3" cy="16" r="8" fill="#60A5FA"/><circle cx="37.3" cy="37.3" r="8" fill="#60A5FA"/><circle cx="37.3" cy="58.7" r="8" fill="#60A5FA"/><circle cx="37.3" cy="80" r="8" fill="#60A5FA"/><circle cx="58.7" cy="16" r="8" fill="#93C5FD"/><circle cx="58.7" cy="37.3" r="8" fill="#93C5FD"/><circle cx="58.7" cy="58.7" r="8" fill="#93C5FD"/><circle cx="58.7" cy="80" r="8" fill="#93C5FD"/><circle cx="80" cy="16" r="8" fill="#E0F2FE"/><circle cx="80" cy="37.3" r="8" fill="#E0F2FE"/><circle cx="80" cy="58.7" r="8" fill="#E0F2FE"/><circle cx="80" cy="80" r="8" fill="#E0F2FE"/></g>
<g fill="#F8FAFC" transform="translate(138.00,60.00) scale(1,-1)">
<path transform="translate(0.00,0) scale(0.031250)" d="M150 0V1490H552L835 721Q850 678 868.5 610.5Q887 543 906.5 465.0Q926 387 943.5 312.5Q961 238 973 181H919Q931 237 948.5 310.5Q966 384 985.5 462.5Q1005 541 1023.5 609.0Q1042 677 1056 721L1336 1490H1739V0H1473V752Q1473 800 1474.0 868.0Q1475 936 1477.0 1014.0Q1479 1092 1481.0 1171.5Q1483 1251 1483 1323H1502Q1482 1244 1458.5 1161.5Q1435 1079 1412.0 1001.5Q1389 924 1368.5 859.0Q1348 794 1333 752L1058 0H831L552 752Q537 794 516.5 857.5Q496 921 472.5 998.0Q449 1075 425.5 1158.5Q402 1242 379 1323H401Q402 1256 404.0 1177.5Q406 1099 407.5 1020.0Q409 941 410.5 871.5Q412 802 412 752V0Z"/>
<path transform="translate(57.43,0) scale(0.031250)" d="M632 -23Q463 -23 341.5 48.0Q220 119 154.5 248.0Q89 377 89 552Q89 725 153.5 855.0Q218 985 336.5 1058.5Q455 1132 615 1132Q717 1132 809.5 1099.0Q902 1066 973.5 997.0Q1045 928 1085.5 821.5Q1126 715 1126 568V486H212V663H997L875 611Q875 705 846.0 776.5Q817 848 759.5 888.0Q702 928 616 928Q530 928 470.0 887.5Q410 847 378.5 779.5Q347 712 347 629V507Q347 401 383.0 328.0Q419 255 484.0 218.0Q549 181 635 181Q692 181 738.5 197.5Q785 214 819.0 246.5Q853 279 870 326L1109 277Q1082 187 1017.0 119.5Q952 52 854.5 14.5Q757 -23 632 -23Z"/>
<path transform="translate(93.67,0) scale(0.031250)" d="M138 0V1118H382L392 849H373Q397 949 447.5 1012.0Q498 1075 565.5 1105.5Q633 1136 707 1136Q828 1136 902.5 1060.0Q977 984 1008 836H977Q1000 936 1055.5 1002.5Q1111 1069 1187.5 1102.5Q1264 1136 1351 1136Q1452 1136 1532.0 1092.0Q1612 1048 1659.0 963.5Q1706 879 1706 754V0H1446V714Q1446 818 1389.0 866.0Q1332 914 1252 914Q1190 914 1144.0 887.0Q1098 860 1073.5 812.5Q1049 765 1049 702V0H795V726Q795 811 742.0 862.5Q689 914 606 914Q549 914 501.5 888.0Q454 862 426.0 811.0Q398 760 398 685V0Z"/>
<path transform="translate(149.70,0) scale(0.031250)" d="M623 -23Q460 -23 340.0 49.5Q220 122 154.5 251.5Q89 381 89 553Q89 727 154.5 857.5Q220 988 340.0 1060.0Q460 1132 623 1132Q787 1132 907.0 1060.0Q1027 988 1092.5 857.5Q1158 727 1158 553Q1158 381 1092.5 251.5Q1027 122 907.0 49.5Q787 -23 623 -23ZM623 188Q714 188 774.5 237.0Q835 286 864.5 369.0Q894 452 894 554Q894 657 864.5 740.0Q835 823 774.5 872.0Q714 921 623 921Q532 921 472.5 872.0Q413 823 383.5 740.5Q354 658 354 554Q354 452 383.5 369.0Q413 286 472.5 237.0Q532 188 623 188Z"/>
<path transform="translate(187.07,0) scale(0.031250)" d="M138 0V1118H390V931H402Q432 1028 507.0 1080.5Q582 1133 678 1133Q700 1133 727.0 1131.0Q754 1129 773 1126V887Q757 892 721.0 896.0Q685 900 650 900Q578 900 520.5 869.0Q463 838 430.5 783.5Q398 729 398 658V0Z"/>
<path transform="translate(210.88,0) scale(0.031250)" d="M127 -399 188 -196 219 -204Q278 -219 324.0 -212.5Q370 -206 401.0 -172.5Q432 -139 445 -75L461 -4L39 1118H317L521 510Q557 402 580.0 295.0Q603 188 631 76H563Q590 188 617.0 295.5Q644 403 680 510L891 1118H1166L686 -144Q652 -233 601.0 -296.5Q550 -360 476.0 -393.0Q402 -426 301 -426Q246 -426 199.5 -418.0Q153 -410 127 -399Z"/>
<path transform="translate(246.93,0) scale(0.031250)" d="M673 -23Q500 -23 372.5 31.0Q245 85 173.0 188.0Q101 291 95 438H358Q365 360 407.0 308.0Q449 256 518.0 230.5Q587 205 671 205Q759 205 826.5 232.0Q894 259 932.0 307.5Q970 356 970 420Q970 478 936.5 516.0Q903 554 842.5 580.5Q782 607 701 627L532 671Q345 719 240.5 816.0Q136 913 136 1071Q136 1203 207.0 1302.0Q278 1401 401.0 1455.5Q524 1510 680 1510Q839 1510 959.0 1455.0Q1079 1400 1146.5 1303.0Q1214 1206 1217 1082H958Q948 1178 872.5 1230.5Q797 1283 676 1283Q592 1283 531.5 1257.5Q471 1232 438.5 1188.0Q406 1144 406 1087Q406 1025 444.5 985.0Q483 945 541.5 921.0Q600 897 660 882L799 846Q882 826 960.0 793.0Q1038 760 1100.5 709.5Q1163 659 1200.0 587.0Q1237 515 1237 418Q1237 287 1170.0 187.5Q1103 88 977.0 32.5Q851 -23 673 -23Z"/>
<path transform="translate(286.96,0) scale(0.031250)" d="M450 -23Q344 -23 259.0 15.5Q174 54 125.0 129.0Q76 204 76 314Q76 409 111.5 471.0Q147 533 207.5 570.0Q268 607 344.0 626.0Q420 645 502 653Q599 664 660.0 672.0Q721 680 749.5 698.0Q778 716 778 754V759Q778 814 756.0 852.5Q734 891 690.5 911.5Q647 932 583 932Q518 932 470.5 912.0Q423 892 393.0 860.0Q363 828 349 791L108 840Q141 939 210.0 1003.5Q279 1068 374.5 1100.0Q470 1132 582 1132Q661 1132 741.5 1113.5Q822 1095 889.0 1051.0Q956 1007 997.0 933.0Q1038 859 1038 747V0H789V154H779Q754 107 710.5 66.5Q667 26 602.5 1.5Q538 -23 450 -23ZM517 170Q598 170 656.5 202.0Q715 234 747.5 286.5Q780 339 780 401V533Q767 523 736.5 514.0Q706 505 668.5 498.0Q631 491 594.5 486.0Q558 481 533 478Q475 470 428.0 452.0Q381 434 354.5 401.5Q328 369 328 317Q328 269 352.5 236.5Q377 204 419.5 187.0Q462 170 517 170Z"/>
<path transform="translate(322.11,0) scale(0.031250)" d="M726 1118V914H20V1118ZM225 0V1225Q225 1337 271.5 1411.0Q318 1485 397.5 1522.5Q477 1560 572 1560Q641 1560 694.0 1549.0Q747 1538 772 1529L719 1327Q702 1332 677.5 1337.5Q653 1343 620 1343Q547 1343 515.5 1307.0Q484 1271 484 1205V0Z"/>
<path transform="translate(345.38,0) scale(0.031250)" d="M632 -23Q463 -23 341.5 48.0Q220 119 154.5 248.0Q89 377 89 552Q89 725 153.5 855.0Q218 985 336.5 1058.5Q455 1132 615 1132Q717 1132 809.5 1099.0Q902 1066 973.5 997.0Q1045 928 1085.5 821.5Q1126 715 1126 568V486H212V663H997L875 611Q875 705 846.0 776.5Q817 848 759.5 888.0Q702 928 616 928Q530 928 470.0 887.5Q410 847 378.5 779.5Q347 712 347 629V507Q347 401 383.0 328.0Q419 255 484.0 218.0Q549 181 635 181Q692 181 738.5 197.5Q785 214 819.0 246.5Q853 279 870 326L1109 277Q1082 187 1017.0 119.5Q952 52 854.5 14.5Q757 -23 632 -23Z"/>
</g>
<g fill="#93C5FD" transform="translate(140.00,90.00) scale(1,-1)">
<path transform="translate(0.00,0) scale(0.009277)" d="M135 0V1490H440V253H1083V0Z"/>
<path transform="translate(19.10,0) scale(0.009277)" d="M49 0 558 1490H958L1480 0H1141L902 719Q859 858 814.5 1023.5Q770 1189 721 1385H788Q740 1188 698.5 1021.5Q657 855 616 719L386 0ZM367 346V585H1162V346Z"/>
<path transform="translate(41.65,0) scale(0.009277)" d="M135 0V1490H726Q890 1490 999.5 1440.5Q1109 1391 1163.5 1305.0Q1218 1219 1218 1107Q1218 1019 1183.0 953.5Q1148 888 1087.5 846.5Q1027 805 950 787V772Q1034 769 1108.5 724.5Q1183 680 1229.5 600.5Q1276 521 1276 411Q1276 293 1218.0 200.0Q1160 107 1046.5 53.5Q933 0 764 0ZM440 251H704Q838 251 900.0 303.0Q962 355 962 440Q962 503 931.5 551.5Q901 600 845.0 627.5Q789 655 712 655H440ZM440 864H681Q746 864 798.0 887.5Q850 911 879.5 954.5Q909 998 909 1058Q909 1139 851.5 1190.0Q794 1241 687 1241H440Z"/>
<path transform="translate(62.58,0) scale(0.009277)" d="M681 -22Q502 -22 369.5 33.0Q237 88 163.0 196.0Q89 304 85 462H382Q388 387 427.0 336.5Q466 286 531.0 261.0Q596 236 678 236Q760 236 820.5 259.5Q881 283 915.0 326.0Q949 369 949 426Q949 477 918.5 511.5Q888 546 831.0 571.0Q774 596 692 615L528 656Q339 702 232.0 800.5Q125 899 125 1061Q125 1196 197.5 1297.0Q270 1398 396.5 1454.0Q523 1510 685 1510Q850 1510 973.0 1453.5Q1096 1397 1165.0 1296.5Q1234 1196 1236 1065H941Q933 1155 864.5 1204.0Q796 1253 682 1253Q605 1253 550.0 1231.0Q495 1209 466.5 1170.0Q438 1131 438 1081Q438 1026 471.0 989.5Q504 953 559.0 930.5Q614 908 676 893L811 860Q905 839 986.0 803.0Q1067 767 1128.0 714.5Q1189 662 1222.5 590.0Q1256 518 1256 424Q1256 289 1188.0 188.5Q1120 88 991.0 33.0Q862 -22 681 -22Z"/>
</g>
</svg></span>
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

    <section class="panel agents-panel" id="agents-panel" aria-label="Your assistants" hidden>
      <span class="step-label">Step 1</span>
      <div class="panel-title"><strong>Connect your assistants</strong><span id="agents-note">ON THIS COMPUTER</span></div>
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
    <section class="panel storage-panel" id="storage-panel" aria-label="Where your memories live" hidden>
      <span class="step-label">Step 2</span>
      <div class="panel-title"><strong>Where should your memories live?</strong></div>
      <div class="agents-mode" id="agents-mode" hidden>
        <button class="agents-mode-choice" id="mode-local" type="button"><strong>On this computer</strong><span>No account. Nothing is uploaded.</span><em>Selected</em></button>
        <button class="agents-mode-choice" id="mode-hosted" type="button"><strong>In my cloud account</strong><span>The same memory on every device. Sign in once.</span><em>Selected</em></button>
      </div>
      <div class="agents-hosted" id="agents-hosted" hidden>
        <p>Each assistant connects to your account from its own settings; the steps are on
        <a href="https://memory.memorysafe.ca/connect" target="_blank" rel="noopener">your cloud Connect page</a>.
        This choice moves no memories: to take the ones on this computer with you, export them below and
        import the file on your account page. The way back works too: download the move file from your
        account page, set memories to live on this computer again, and import it below.</p>
        <p>The numbers and memories on this page are still the ones left on this computer. Your account's are on
        <a href="https://memory.memorysafe.ca/account" target="_blank" rel="noopener">your account page</a>.</p>
        <p id="agents-local-count" hidden></p>
        <div class="device-link" id="agents-link">
          <p id="agents-link-text"></p>
          <div class="agents-ask-actions">
            <button class="agent-connect" id="link-signin" type="button">Sign in to your account</button>
            <button class="agents-no" id="link-signout" type="button" hidden>Sign out</button>
          </div>
          <small id="agents-link-note"></small>
        </div>
      </div>
      <p class="agents-message" id="storage-message" hidden></p>
    </section>
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
    <section class="metrics" aria-label="What MemorySafe gave back">
      <div class="metric metric-green"><span>Memory searches</span><strong id="recall-count">—</strong><small>find calls recorded by MemorySafe</small></div>
      <div class="metric metric-cyan"><span>Memories used</span><strong id="recall-used">—</strong><small id="recall-used-note">of those stored</small></div>
      <div class="metric metric-blue"><span>Never used</span><strong id="recall-unused">—</strong><small>stored, never recalled</small></div>
      <div class="metric"><span>Active memories</span><strong id="active">—</strong><small id="protected-note">available for recall</small></div>
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
    <section class="panel hosted-panel" id="hosted-panel" aria-label="Take your memory everywhere">
      <div class="panel-title"><strong>Take your memory everywhere</strong><span>CLOUD ACCOUNT · FREE</span></div>
      <p class="hosted-text">MemorySafe Cloud gives every assistant you use, on every device, this same memory. Export a copy here, then import it into your cloud account; nothing leaves this computer until you upload the file yourself.</p>
      <div class="hosted-actions">
        <button class="agent-connect" id="hosted-export" type="button">Export my memories for the cloud</button>
        <a class="agents-link" href="https://memory.memorysafe.ca/account/start?signup=1&amp;next=/account/import&amp;lang=en" target="_blank" rel="noopener">Create a free cloud account</a>
      </div>
      <div class="support-result" id="hosted-result" role="status"></div>
      <p class="hosted-text hosted-return">Coming back from the cloud? Download the move file from
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
          termsNotice.textContent = `${String(data.legal_change_note ?? "The Terms or Privacy Policy changed.")} Nothing has stopped working. `;
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
      if (!Array.isArray(agents) || !agents.length) { panel.hidden = true; byId("storage-panel").hidden = true; return; }
      panel.hidden = false;
      byId("storage-panel").hidden = false;
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
            ? "Connected through the plugin on this computer, which reads and saves in your account once you have signed in below."
            : "Connect it to your account from the cloud Connect page. Its account connection cannot be checked from here."));
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
      const message = byId("storage-message");
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
            ? "Memories live on this computer again. The plugin's sign-in to your cloud account was ended, on this and any other computer using it; your memories there were not changed."
            : payload.signed_out.reached
              ? "Memories live on this computer again. The sign-in was removed here, but your cloud account did not confirm ending it elsewhere; end it from your account page if you want that."
              : "Memories live on this computer again. Your cloud account could not be reached, so the sign-in was removed here only.";
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
        ? `This computer is signed in to your cloud account${since && !Number.isNaN(since.valueOf()) ? ` since ${since.toLocaleDateString()}` : ""}.`
        : "This computer is not signed in to your cloud account yet. Sign in once here; every assistant connected through the plugin shares it.");
      byId("link-signin").hidden = !!link.linked;
      byId("link-signout").hidden = !link.linked;
      setText("agents-link-note", link.linked
        ? "Signing out ends the plugin's sign-in on every computer where you use it, not only this one. Your memories in the account are not changed."
        : "The sign-in opens in your browser. Nothing is sent until you approve it there.");
      if (link.linked && linkWatch) { clearInterval(linkWatch); linkWatch = null; }
    }

    byId("link-signin").addEventListener("click", async () => {
      const button = byId("link-signin");
      const message = byId("storage-message");
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
      const message = byId("storage-message");
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
          ? "Signed out. The plugin's sign-in to your cloud account was ended on every computer using it; your memories there were not changed."
          : payload.signed_out?.reached
            ? "Signed out here. Your cloud account did not confirm ending the sign-in, so it may still count there until it expires or you end it from your account page."
            : "Signed out here. Your cloud account could not be reached, so the sign-in still counts there until it expires or you end it from your account page.";
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
        '<p class="hosted-text">MemorySafe Cloud gives every assistant you use, on every device, this same memory. '
        "Export a copy here, then import it into your cloud account; nothing leaves this computer "
        "until you upload the file yourself.</p>",
        '<p class="hosted-text"></p>',
    ),
    # The storage-mode chooser stays hidden on the hosted page (renderAgents never runs
    # there), but its static label must not call the device a computer the page is not on.
    (">On this computer</strong>", ">On this device</strong>"),
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
    /* The brand guide's dark set (17 Nov 2026), as on the full dashboard. */
    :root {
      --bg: #0e1420; --surface: #141b2a; --surface-2: #1c2536; --border: #263249;
      --text: #f8fafc; --muted: #94a3b8; --dim: #94a3b8; --accent: #93c5fd; --accent-2: #60a5fa;
      --btn-bg: #e0f2fe; --btn-text: #0b1220; --track: #263249; --tint-line: rgba(147,197,253,.4);
      --ok: #93c5fd; --ok-line: rgba(147,197,253,.4); --ok-bg: rgba(147,197,253,.08);
      --warn: #fcd34d; --warn-line: rgba(252,211,77,.4); --warn-bg: rgba(252,211,77,.08);
      --bad: #fca5a5; --bad-line: rgba(252,165,165,.45); --bad-bg: rgba(252,165,165,.08);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
      font: 16px/1.4 "Inter", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body {
      background: var(--bg);
    }
    .shell { padding: 14px 14px 12px; min-height: 100%; display: flex; flex-direction: column; gap: 12px; }
    header { display: flex; align-items: center; gap: 10px; }
    .mark { display: grid; flex: 0 0 auto; grid-template-columns: repeat(4, 6px); gap: 3px; margin: 0 4px 0 3px; transform: rotate(-6deg); }
    .mark i { display: block; width: 6px; height: 6px; border-radius: 50%; background: #3b82f6; }
    .mark i:nth-child(4n+2) { background: #60a5fa; }
    .mark i:nth-child(4n+3) { background: #93c5fd; }
    .mark i:nth-child(4n) { background: #e0f2fe; }
    .brand strong { display: block; font-size: 16px; letter-spacing: -.3px; }
    .brand span { display: block; color: var(--muted); font-size: 9px; }
    .live { margin-left: auto; color: var(--muted); font: 700 14px/1 ui-monospace, Menlo, monospace; letter-spacing: .08em; }
    .live::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 5px;
      border-radius: 50%; background: var(--accent); vertical-align: 0; }
    .hero {
      padding: 12px; display: flex; gap: 12px; align-items: center;
      border: 1px solid var(--border); border-radius: 12px;
      background: var(--surface);
    }
    .score {
      --score: 0; width: 72px; height: 72px; flex: 0 0 72px; display: grid; place-items: center;
      border-radius: 50%; background: conic-gradient(var(--accent) calc(var(--score) * 1%), var(--track) 0);
    }
    .score::before { content: ""; position: absolute; width: 58px; height: 58px; border-radius: inherit; background: var(--surface); }
    .score { position: relative; }
    .score-value { position: relative; text-align: center; }
    .score-value strong { display: block; font: 800 22px/1 ui-monospace, Menlo, monospace; }
    .score-value span { display: block; margin-top: 3px; color: var(--muted); font-size: 7px; letter-spacing: .05em; }
    .hero-copy { min-width: 0; flex: 1; }
    .hero-copy strong { display: block; font-size: 14px; }
    .hero-copy p { margin: 3px 0 0; color: var(--muted); font-size: 10px; }
    .fresh { display: inline-block; margin-top: 6px; padding: 2px 7px; border-radius: 999px;
      font: 800 14px ui-monospace, Menlo, monospace; letter-spacing: .04em; border: 1px solid transparent; }
    .fresh.active { color: var(--ok); border-color: var(--ok-line); background: var(--ok-bg); }
    .fresh.quiet { color: var(--warn); border-color: var(--warn-line); background: var(--warn-bg); }
    .fresh.stale, .fresh.never { color: var(--bad); border-color: var(--bad-line); background: var(--bad-bg); }
    .metrics { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
    .metric { padding: 9px 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); min-width: 0; }
    .metric span { display: block; color: var(--muted); font-size: 8px; }
    .metric strong { display: block; margin-top: 3px; font: 800 18px/1 ui-monospace, Menlo, monospace; }
    .auto {
      padding: 10px 11px; display: flex; align-items: center; gap: 10px;
      border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2);
    }
    .auto div { min-width: 0; flex: 1; }
    .auto strong { display: block; font-size: 11px; }
    .auto small { display: block; margin-top: 2px; color: var(--muted); font-size: 9px; }
    .toggle {
      min-width: 48px; padding: 7px 8px; border: 1px solid var(--border); border-radius: 999px;
      background: var(--surface); color: var(--muted); cursor: pointer;
      font: 800 14px ui-monospace, Menlo, monospace;
    }
    .toggle.on { border-color: var(--btn-bg); background: var(--btn-bg); color: var(--btn-text); }
    .toggle:disabled { opacity: .45; }
    .memories { flex: 1; min-height: 0; padding: 10px 11px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .memories h2 { margin: 0 0 8px; font-size: 11px; display: flex; justify-content: space-between; }
    .memories h2 span { color: var(--dim); font: 700 14px ui-monospace, Menlo, monospace; }
    .row { display: grid; grid-template-columns: 7px 1fr; gap: 8px; align-items: start; padding: 7px 0;
      border-top: 1px solid var(--border); }
    .row:first-of-type { border-top: 0; }
    .dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--accent-2); }
    .row.protected .dot { background: var(--accent); }
    .row p { margin: 0; font-size: 11px; color: var(--text); overflow-wrap: anywhere; white-space: pre-line; }
    .row em { display: block; margin-top: 2px; color: var(--dim); font-style: normal; font-size: 8px; }
    .empty { color: var(--muted); font-size: 11px; padding: 12px 0; text-align: center; }
    footer { display: flex; gap: 8px; }
    footer a, footer button {
      flex: 1; text-align: center; text-decoration: none; cursor: pointer;
      padding: 8px 9px; border-radius: 9px; font-size: 11px;
      border: 1px solid var(--border); background: var(--surface); color: var(--muted);
    }
    footer a.primary { border-color: var(--tint-line); color: var(--accent); }
    .error { display: none; color: var(--bad); font-size: 10px; }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
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
