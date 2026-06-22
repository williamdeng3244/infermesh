# SPDX-License-Identifier: Apache-2.0
"""Self-contained admin dashboard (single HTML page, no build step, no CDN, no deps).

Served by the gateway at ``GET /`` and ``GET /admin``. Four sections via a left
sidebar — Models, Chat, Logs, Metrics, Devices, Benchmark, Settings — driven by the public HTTP API
(``/api/status``, ``/api/logs``, ``/api/settings``, ``/v1/*``). Dark "developer
tool" palette; system mono/sans stacks (Fira Code / Inter approximations) so it
renders offline.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>infermesh · admin</title>
<style>
:root{
  --bg:#0b1120; --surface:#0f172a; --card:#1b2336; --card2:#141d2e; --mutedbg:#272f42;
  --border:#1f2a3b; --border2:#334155;
  --text:#f8fafc; --muted:#94a3b8; --dim:#64748b;
  --accent:#22c55e; --accent2:#16a34a; --blue:#58a6ff; --warn:#d29922; --danger:#ef4444;
  --radius:10px; --sb:236px;
  --mono:ui-monospace,"Cascadia Code","Fira Code","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
}
:root[data-theme="light"]{
  --bg:#eef2f6; --surface:#ffffff; --card:#ffffff; --card2:#f1f5f9; --mutedbg:#e2e8f0;
  --border:#e2e8f0; --border2:#cbd5e1;
  --text:#0f172a; --muted:#475569; --dim:#94a3b8;
  --accent:#16a34a; --accent2:#15803d; --blue:#2563eb; --warn:#b45309; --danger:#dc2626;
}
:root[data-theme="light"] .topbar{background:rgba(255,255,255,.72)}
:root[data-theme="light"] .msg.user{color:#fff}
:root[data-theme="light"] .btn.primary{color:#fff}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
a{color:var(--blue);text-decoration:none}
.app{display:grid;grid-template-columns:var(--sb) 1fr;min-height:100dvh}
.sidebar{background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;position:sticky;top:0;height:100dvh}
.brand{display:flex;align-items:center;gap:10px;padding:18px 18px 12px;font-weight:700;font-size:16px;letter-spacing:.3px}
.brand .mark{color:var(--accent);display:flex}
.nav{padding:8px;display:flex;flex-direction:column;gap:3px}
.nav button{display:flex;align-items:center;gap:11px;width:100%;padding:9px 12px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--muted);font:500 13.5px var(--sans);cursor:pointer;text-align:left;transition:.15s}
.nav button:hover{background:var(--card2);color:var(--text)}
.nav button.active{background:var(--card);color:var(--text);border-color:var(--border2)}
.nav button.active svg{color:var(--accent)}
.nav svg{width:18px;height:18px;flex:none}
.sb-foot{margin-top:auto;padding:14px 16px;border-top:1px solid var(--border);font-size:12px;color:var(--dim);display:flex;flex-direction:column;gap:9px}
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;gap:12px;padding:13px 24px;border-bottom:1px solid var(--border);background:rgba(15,23,42,.7);backdrop-filter:blur(6px);position:sticky;top:0;z-index:5}
.topbar h2{margin:0;font-size:16px;font-weight:600}
.spacer{flex:1}
.pill{font:500 12px var(--sans);padding:3px 10px;border-radius:999px;border:1px solid var(--border2);color:var(--muted);display:inline-flex;align-items:center;gap:7px}
.seg{display:inline-flex;border:1px solid var(--border2);border-radius:8px;overflow:hidden}
.seg-btn{background:transparent;border:0;color:var(--muted);padding:5px 15px;cursor:pointer;font:500 13px var(--sans)}
.seg-btn.active{background:var(--blue);color:#0b1120}
.prefill{color:var(--dim);font-style:italic}
.msg-meta{font-size:11px;color:var(--dim);margin-top:4px}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--dim)}
.pill.ok{color:var(--accent);border-color:rgba(34,197,94,.4)}.pill.ok .dot{background:var(--accent);box-shadow:0 0 8px var(--accent)}
.pill.bad{color:var(--danger);border-color:rgba(239,68,68,.4)}.pill.bad .dot{background:var(--danger)}
.content{padding:24px;overflow:auto}
.section{display:none}
.section.active{display:block;animation:fade .2s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
input,select,textarea{font:14px var(--sans);background:var(--card2);border:1px solid var(--border2);color:var(--text);border-radius:8px;padding:8px 11px;outline:none}
input:focus,select:focus,textarea:focus,button:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
.btn{font:500 12.5px var(--sans);padding:6px 12px;border-radius:7px;border:1px solid var(--border2);background:var(--card2);color:var(--text);cursor:pointer;transition:.15s}
.btn:hover:not(:disabled){border-color:var(--blue)}
.btn:disabled{opacity:.35;cursor:default}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#06210f;font-weight:600}
.btn.primary:hover{background:var(--accent2)}
.btn.sm{padding:4px 9px;font-size:11.5px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}
.card .k{color:var(--muted);font:500 11px var(--sans);text-transform:uppercase;letter-spacing:.7px}
.card .v{font:600 26px/1.1 var(--mono);margin-top:8px}
.card .v small{font-size:14px;color:var(--muted);font-weight:500}
.bar{height:6px;background:var(--mutedbg);border-radius:3px;margin-top:12px;overflow:hidden}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--accent));transition:width .5s ease}
.stat-viz{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
.stack{display:flex;height:16px;border-radius:8px;overflow:hidden;margin-top:14px;background:var(--mutedbg)}
.stack>span{display:block;height:100%;transition:width .5s ease}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:middle}
.legend b{color:var(--text);font-weight:600;font-family:var(--mono);margin-left:3px}
.panel{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:13.5px}
thead th{text-align:left;padding:11px 16px;color:var(--muted);font:600 11px var(--sans);text-transform:uppercase;letter-spacing:.6px;background:var(--card2);border-bottom:1px solid var(--border)}
tbody td{padding:11px 16px;border-bottom:1px solid var(--border);white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--card2)}
.mono{font-family:var(--mono)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.badge{font:600 11px var(--mono);padding:2px 8px;border-radius:6px;border:1px solid var(--border2);color:var(--muted)}
.badge.loaded{color:var(--accent);border-color:rgba(34,197,94,.4);background:rgba(34,197,94,.08)}
.badge.loading{color:var(--blue);border-color:rgba(88,166,255,.4)}
.badge.pinned{color:var(--warn);border-color:rgba(210,153,34,.4);background:rgba(210,153,34,.08)}
.rowact{display:flex;gap:6px}
.muted{color:var(--muted)}
.err{color:var(--danger);font-size:13px;min-height:18px;margin-top:12px}
.chat-wrap{display:flex;flex-direction:column;height:calc(100dvh - 112px)}
.chat-bar{display:flex;gap:10px;align-items:center;margin-bottom:12px}
.msgs{flex:1;overflow:auto;display:flex;flex-direction:column;gap:14px;padding:4px 2px}
.msg{max-width:80%;padding:11px 14px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}
.msg.user{align-self:flex-end;background:var(--blue);color:#04121f;border-bottom-right-radius:4px}
.msg.assistant{align-self:flex-start;background:var(--card);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg .who{font:600 10px var(--sans);text-transform:uppercase;letter-spacing:.6px;opacity:.65;margin-bottom:4px}
.composer{display:flex;gap:10px;margin-top:12px}
.composer textarea{flex:1;resize:none;min-height:46px;max-height:150px}
.logs{background:#070b14;border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;font:12.5px/1.65 var(--mono);height:calc(100dvh - 158px);overflow:auto}
.logline{white-space:pre-wrap;word-break:break-word}
.logline.INFO{color:#cbd5e1}.logline.WARNING{color:var(--warn)}.logline.ERROR{color:#fda4af}.logline.DEBUG{color:var(--dim)}
.form{max-width:580px}
.form h3{margin:0 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}
.field{margin-bottom:20px}
.field>label{display:block;font:600 12.5px var(--sans);margin-bottom:7px}
.field .row{display:flex;gap:10px}
.field .hint{font-size:12px;color:var(--dim);margin-top:6px}
.kv{display:grid;grid-template-columns:210px 1fr;gap:9px 16px;font-size:13.5px;margin-top:6px}
.kv dt{color:var(--muted)} .kv dd{margin:0;font-family:var(--mono);font-variant-numeric:tabular-nums}
.bm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px;padding:16px;background:var(--card2);border-top:1px solid var(--border)}
.bm-block .bm-bt{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin-bottom:6px;font-weight:600}
.kv-sm{grid-template-columns:135px 1fr;gap:5px 10px;font-size:12.5px;margin-top:0}
.bm-exp{padding:2px 8px;line-height:1}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--border2);padding:10px 18px;border-radius:9px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:50}
.toast.show{opacity:1}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand"><span class="mark"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="M12 7l4.5 2.5v5L12 17l-4.5-2.5v-5z" opacity=".55"/></svg></span> infermesh</div>
    <nav class="nav" id="nav" aria-label="Sections">
      <button data-sec="models" class="active" aria-label="Models"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3"/></svg> Models</button>
      <button data-sec="chat" aria-label="Chat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> Chat</button>
      <button data-sec="logs" aria-label="Logs"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg> Logs</button>
      <button data-sec="metrics" aria-label="Metrics"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg> Metrics</button>
      <button data-sec="devices" aria-label="Devices"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="5" rx="1"/><rect x="2" y="13" width="20" height="5" rx="1"/><line x1="6" y1="8.5" x2="6.01" y2="8.5"/><line x1="6" y1="15.5" x2="6.01" y2="15.5"/></svg> Devices</button>
      <button data-sec="download" aria-label="Download"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg> Download</button>
      <button data-sec="benchmark" aria-label="Benchmark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 19a9 9 0 1 1 15 0"/><path d="M12 14l3.5-3.5"/></svg> Benchmark</button>
      <button data-sec="settings" aria-label="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg> Settings</button>
    </nav>
    <div class="sb-foot">
      <span id="sb-health" class="pill"><span class="dot"></span> connecting</span>
      <span id="sb-ver">v0.3.2 · mock / vllm / openai / transformers</span>
    </div>
  </aside>

  <div class="main">
    <div class="topbar">
      <h2 id="title">Models</h2>
      <span class="spacer"></span>
      <button class="btn sm" id="themeBtn" aria-label="Toggle light/dark theme" title="Toggle theme"></button>
      <input id="apikey" placeholder="API key (if enabled)" size="20" autocomplete="off" aria-label="API key"/>
      <button class="btn sm" id="refreshBtn">&#8635; Refresh</button>
    </div>
    <div class="content">

      <section class="section active" id="sec-models">
        <div class="cards" id="cards"></div>
        <div class="chat-bar" style="margin-bottom:12px">
          <label class="muted" style="font-size:12px">Load on device</label>
          <select id="devSel" style="min-width:220px"><option value="">auto</option></select>
          <span class="muted" style="font-size:11px">applies to the next Load (Transformers backend)</span>
        </div>
        <div class="panel">
          <table>
            <thead><tr><th>Model</th><th>Type</th><th>Backend</th><th>Status</th><th>Mem MB</th><th>Gen tps</th><th>Leases</th><th>Actions</th></tr></thead>
            <tbody id="rows"><tr><td colspan="8" class="muted">loading&hellip;</td></tr></tbody>
          </table>
        </div>
        <p id="models-err" class="err"></p>
      </section>

      <section class="section" id="sec-chat">
        <div class="chat-wrap">
          <div class="chat-bar">
            <label class="muted" style="font-size:12px">Model</label>
            <select id="chatModel" style="min-width:190px"></select>
            <span class="spacer"></span>
            <button class="btn sm" id="chatClear">Clear</button>
          </div>
          <div class="msgs" id="msgs"></div>
          <div class="composer">
            <textarea id="chatInput" placeholder="Message the model&hellip;  (Enter to send, Shift+Enter for newline)" aria-label="Chat message"></textarea>
            <button class="btn primary" id="sendBtn">Send</button>
          </div>
        </div>
      </section>

      <section class="section" id="sec-logs">
        <div class="chat-bar" style="margin-bottom:12px">
          <span class="muted" style="font-size:12px">Live tail of infermesh logs (pool · server · backends)</span>
          <span class="spacer"></span>
          <label class="muted" style="font-size:12px"><input type="checkbox" id="logsPause"/> pause</label>
        </div>
        <div class="logs" id="logs"><div class="muted">loading&hellip;</div></div>
      </section>

      <section class="section" id="sec-metrics">
        <div class="panel" style="padding:14px 16px;margin-bottom:14px">
          <div class="chat-bar">
            <div class="seg"><button id="stScopeSession" class="seg-btn active">Session</button><button id="stScopeAll" class="seg-btn">All-Time</button></div>
            <select id="stModel" style="min-width:160px"><option value="">All models</option></select>
            <span class="muted" style="font-size:11px">aggregate request stats &mdash; All-Time survives restarts</span>
            <span class="spacer"></span>
            <button class="btn sm" id="stCopy">Copy</button>
            <button class="btn sm" id="stExport">Export CSV</button>
            <button class="btn sm" id="stClear">Clear</button>
          </div>
        </div>
        <div class="cards" id="liveBar" style="margin-bottom:14px"></div>
        <div class="seg" id="mtTabs" style="margin-bottom:14px">
          <button class="seg-btn active" data-mt="overview">Overview</button>
          <button class="seg-btn" data-mt="permodel">Per-model</button>
          <button class="seg-btn" data-mt="charts">Charts</button>
          <button class="seg-btn" data-mt="rejections">Rejections</button>
        </div>
        <div class="mt-panel" id="mt-overview">
          <div class="cards" id="statCards"></div>
          <div class="stat-viz">
            <div class="card">
              <div class="k">Token composition</div>
              <div class="stack" id="tokBar"></div>
              <div class="legend" id="tokLeg"></div>
            </div>
            <div class="card">
              <div class="k">Cache efficiency</div>
              <div class="v" id="cacheV">&mdash;<small> %</small></div>
              <div class="bar"><i id="cacheBar" style="width:0%"></i></div>
              <div class="muted" id="cacheSub" style="font-size:11px;margin-top:10px">&mdash;</div>
            </div>
          </div>
        </div>
        <div class="mt-panel" id="mt-permodel" style="display:none">
          <div class="panel">
            <table>
              <thead><tr><th data-sort="model">Model</th><th data-sort="total_requests">Requests</th><th data-sort="generation_tps">Gen tok/s</th><th data-sort="total_tokens_served">Tokens</th><th data-sort="cache_efficiency">Cache %</th></tr></thead>
              <tbody id="pmRows"><tr><td colspan="5" class="muted">no per-model data yet</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="mt-panel" id="mt-charts" style="display:none">
          <div class="seg" id="chRange" style="margin-bottom:14px">
            <button class="seg-btn" data-r="300">5m</button>
            <button class="seg-btn" data-r="3600">1h</button>
            <button class="seg-btn active" data-r="0">All</button>
          </div>
          <div class="cards" id="metricCards"></div>
          <div class="panel" style="padding:18px;margin-bottom:16px">
            <div class="muted" style="font-size:12px;margin-bottom:10px">Latency per request (ms)</div>
            <canvas id="chartLatency" style="width:100%;display:block"></canvas>
          </div>
          <div class="panel" style="padding:18px">
            <div class="muted" style="font-size:12px;margin-bottom:10px">Throughput per request (tokens/s)</div>
            <canvas id="chartTps" style="width:100%;display:block"></canvas>
          </div>
          <p class="muted" style="font-size:12px;margin-top:12px">History records one point per chat completion — use the <strong>Chat</strong> tab (or send API requests) to generate data.</p>
        </div>
        <div class="mt-panel" id="mt-rejections" style="display:none">
          <div class="panel" style="padding:16px">
            <div class="muted" style="font-size:12px;margin-bottom:10px">Requests rejected before serving, by reason</div>
            <div id="statRej" class="muted" style="font-size:13px">none</div>
          </div>
        </div>
      </section>

      <section class="section" id="sec-devices">
        <div class="chat-bar" style="margin-bottom:12px">
          <span class="muted" style="font-size:12px">Detected compute devices &mdash; pick one per model on the Models tab</span>
          <span class="spacer"></span>
          <button class="btn sm" id="devRefresh">&#8635; Refresh</button>
        </div>
        <div class="panel">
          <table>
            <thead><tr><th>Device</th><th>Vendor</th><th>Name</th><th>VRAM used</th><th>VRAM free</th><th>VRAM total</th></tr></thead>
            <tbody id="devRows"><tr><td colspan="6" class="muted">loading&hellip;</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="section" id="sec-download">
        <div class="chat-bar" style="margin-bottom:12px">
          <input id="dlSearch" placeholder="Search HuggingFace models (e.g. Qwen2.5-0.5B-Instruct)" style="flex:1;min-width:240px"/>
          <select id="dlTask" title="Filter by task">
            <option value="">Any task</option>
            <option value="text-generation">Text generation</option>
            <option value="image-text-to-text">Vision (VLM)</option>
            <option value="feature-extraction">Embedding</option>
          </select>
          <select id="dlSort" title="Sort by">
            <option value="downloads">Most downloads</option>
            <option value="trending_score">Trending</option>
            <option value="likes">Most likes</option>
            <option value="lastModified">Recently updated</option>
          </select>
          <button class="btn primary" id="dlBtn">Search</button>
        </div>
        <p class="muted" style="font-size:12px;margin:0 0 10px">Downloads land in the server's <code>--model-dir</code> and appear under Models when finished.</p>
        <div class="panel" style="margin-bottom:16px">
          <table>
            <thead><tr><th>Model</th><th>Task</th><th>Downloads</th><th>Likes</th><th></th></tr></thead>
            <tbody id="dlResults"><tr><td colspan="5" class="muted">popular models load here&hellip;</td></tr></tbody>
          </table>
        </div>
        <div class="chat-bar" style="margin-bottom:8px"><span class="muted" style="font-size:12px">Downloads</span></div>
        <div class="panel">
          <table>
            <thead><tr><th>Repo</th><th>Status</th><th>Progress</th><th>Size</th></tr></thead>
            <tbody id="dlJobs"><tr><td colspan="4" class="muted">no downloads yet</td></tr></tbody>
          </table>
        </div>
        <p id="dl-err" class="err"></p>
      </section>

      <section class="section" id="sec-benchmark">
        <div class="controls" style="flex-wrap:wrap;gap:12px">
          <label class="muted" style="font-size:12px">Model</label>
          <select id="bmModel" style="min-width:180px"></select>
          <label class="muted" style="font-size:12px">Requests</label>
          <input id="bmReq" type="number" min="1" max="200" value="20" style="width:78px"/>
          <label class="muted" style="font-size:12px">Concurrency</label>
          <input id="bmConc" type="number" min="1" max="32" value="4" style="width:70px"/>
          <label class="muted" style="font-size:12px">Max tokens</label>
          <input id="bmTok" type="number" min="1" max="1024" value="64" style="width:78px"/>
          <label class="muted" style="font-size:12px">Mode</label>
          <select id="bmMode" style="width:140px"><option value="same">same prompt</option><option value="different">different</option></select>
          <button class="btn primary" id="bmRun">Run benchmark</button>
          <button class="btn sm" id="bmSingle">Single request</button>
          <button class="btn sm" id="bmCopy">Copy</button>
          <span id="bmStatus" class="muted" style="font-size:12px"></span>
        </div>
        <div class="cards" id="bmCards"></div>
        <div class="panel" id="bmDetail" style="display:none;padding:18px">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px">
            <div><div class="muted" style="font-size:12px;margin-bottom:8px">Latency / E2E (ms)</div><dl class="kv" id="bmLatency"></dl></div>
            <div><div class="muted" style="font-size:12px;margin-bottom:8px">Time to first token (ms)</div><dl class="kv" id="bmTtft"></dl></div>
            <div><div class="muted" style="font-size:12px;margin-bottom:8px">Time per output token (ms)</div><dl class="kv" id="bmTpot"></dl></div>
          </div>
          <div class="muted" style="font-size:12px;margin:18px 0 8px">Latency percentiles</div>
          <canvas id="bmChart" style="width:100%;display:block"></canvas>
        </div>
        <div class="panel" style="margin-top:16px">
          <div class="chat-bar" style="padding:12px 14px 0"><span class="muted" style="font-size:12px">Past runs &mdash; persisted across restarts</span></div>
          <table>
            <thead><tr><th style="width:34px"></th><th>When</th><th>Model</th><th>Req&times;Conc</th><th>req/s</th><th>tok/s</th><th>p50 ms</th><th>p99 ms</th></tr></thead>
            <tbody id="bmHist"><tr><td colspan="8" class="muted">no past runs</td></tr></tbody>
          </table>
        </div>
        <p id="bm-err" class="err"></p>
      </section>

      <section class="section" id="sec-settings">
        <div class="form">
          <h3>Runtime-editable</h3>
          <div class="field">
            <label for="setIdle">Idle timeout (seconds)</label>
            <div class="row">
              <input id="setIdle" type="number" min="0" step="0.5" style="width:160px"/>
              <button class="btn" id="saveIdle">Save</button>
            </div>
            <div class="hint">0 disables auto-unload. Applies live to the TTL reaper.</div>
          </div>
          <div class="field">
            <label for="setKey">API key</label>
            <div class="row">
              <input id="setKey" type="text" placeholder="enter key — blank = disable auth" style="width:300px" autocomplete="off"/>
              <button class="btn" id="applyKey">Apply</button>
            </div>
            <div class="hint">Sets or clears the single bearer key the gateway enforces. Current: <span id="keyState" class="mono"></span></div>
          </div>
          <div class="field">
            <label for="setKvHot">KV cache &mdash; hot entries (Transformers tiered KV)</label>
            <div class="row">
              <input id="setKvHot" type="number" min="0" step="1" style="width:140px"/>
              <input id="setKvCold" type="text" placeholder="cold (SSD) dir &mdash; blank = ~/.infermesh/kv" style="width:320px" autocomplete="off"/>
              <button class="btn" id="saveKv">Save</button>
            </div>
            <div class="hint">Hot RAM entries for the tiered KV cache (0 = off). Applies to models loaded after saving.</div>
          </div>
          <div class="field">
            <label for="setHfEndpoint">HuggingFace endpoint (mirror)</label>
            <div class="row">
              <input id="setHfEndpoint" type="text" placeholder="blank = huggingface.co &middot; e.g. https://hf-mirror.com" style="width:340px" autocomplete="off"/>
              <button class="btn" id="saveHf">Save</button>
            </div>
            <div class="hint">Search + download via a mirror (faster/accessible in some regions). Applies immediately.</div>
          </div>
          <h3 style="margin-top:26px">Generation defaults</h3>
          <div class="field">
            <label for="setGenTemp">Sampling defaults &mdash; applied when a request omits the parameter</label>
            <div class="row">
              <input id="setGenTemp" type="number" min="0" max="2" step="0.05" placeholder="temperature" title="temperature 0&ndash;2" style="width:130px"/>
              <input id="setGenTopP" type="number" min="0" max="1" step="0.05" placeholder="top_p" title="top_p 0&ndash;1" style="width:115px"/>
              <input id="setGenTopK" type="number" min="0" step="1" placeholder="top_k" title="top_k (0 = off)" style="width:110px"/>
              <input id="setGenMax" type="number" min="1" step="1" placeholder="max_tokens" title="max output tokens" style="width:135px"/>
              <button class="btn" id="saveGen">Save</button>
            </div>
            <div class="hint">Blank = no server default (the client's value or the built-in fallback applies). A request's own values always win.</div>
          </div>
          <p id="settings-err" class="err"></p>
          <h3 style="margin-top:26px">All settings</h3>
          <dl class="kv" id="settingsKv"></dl>
        </div>
      </section>

    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
let active='models', logsPaused=false, lastBench=null;
const TITLES={models:'Models',chat:'Chat',logs:'Logs',metrics:'Metrics',devices:'Devices',download:'Download',benchmark:'Benchmark',settings:'Settings'};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>(n==null?'—':Number(n).toLocaleString());
const authHeaders=()=>{const k=$('#apikey').value.trim();return k?{'Authorization':'Bearer '+k}:{}};
async function api(path,method,body){
  const opt={method:method||'GET',headers:Object.assign({},authHeaders())};
  if(body!==undefined){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(body);}
  const r=await fetch(path,opt);
  if(!r.ok) throw new Error('HTTP '+r.status+' · '+path);
  return r.json();
}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600);}
function setHealth(ok){const p=$('#sb-health');p.className='pill '+(ok?'ok':'bad');p.innerHTML='<span class="dot"></span> '+(ok?'healthy':'unreachable');}
const SUN='<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON='<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem('infermesh-theme',t);}catch(e){}const b=$('#themeBtn');if(b)b.innerHTML=(t==='light'?MOON:SUN);if(active==='metrics'&&typeof refreshMetrics==='function')refreshMetrics();}
applyTheme((function(){try{return localStorage.getItem('infermesh-theme');}catch(e){return null;}})()||'dark');
$('#themeBtn').onclick=function(){applyTheme(document.documentElement.getAttribute('data-theme')==='light'?'dark':'light');};

$$('#nav button').forEach(b=>b.onclick=()=>switchSection(b.dataset.sec));
function switchSection(sec){
  active=sec;
  $$('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.sec===sec));
  $$('.section').forEach(s=>s.classList.toggle('active',s.id==='sec-'+sec));
  $('#title').textContent=TITLES[sec];
  if(sec==='chat') loadChatModels();
  if(sec==='logs') refreshLogs();
  if(sec==='settings') loadSettings();
  if(sec==='metrics'){ refreshMetrics(); refreshStats(); }
  if(sec==='benchmark'){ loadBenchModels(); refreshBenchHistory(); }
  if(sec==='devices') refreshDevices();
  if(sec==='download'){ refreshDownloads(); if(!dlLoaded){ dlLoaded=true; runHfSearch(); } }
  if(sec==='models') loadDevicePicker();
}

/* Models */
function renderModels(s){
  const pct=s.ceiling_mb?Math.min(100,Math.round(100*s.used_mb_live/s.ceiling_mb)):0;
  $('#cards').innerHTML=
    '<div class="card"><div class="k">Models loaded</div><div class="v">'+s.loaded_count+'<small> / '+s.model_count+'</small></div></div>'+
    '<div class="card"><div class="k">Committed memory</div><div class="v">'+fmt(s.current_model_memory_mb)+'<small> MB</small></div></div>'+
    '<div class="card"><div class="k">Live used / ceiling</div><div class="v">'+fmt(s.used_mb_live)+'<small> / '+fmt(s.ceiling_mb)+' MB</small></div><div class="bar"><i style="width:'+pct+'%"></i></div></div>'+
    '<div class="card"><div class="k">Host RAM</div><div class="v">'+fmt(s.total_mb)+'<small> MB</small></div></div>';
  $('#rows').innerHTML=(s.models||[]).map(m=>{
    const st=m.is_loading?'<span class="badge loading">loading</span>':m.loaded?'<span class="badge loaded">loaded</span>':'<span class="badge">idle</span>';
    const pin=m.pinned?' <span class="badge pinned">pinned</span>':'';
    const tps=m.stats?m.stats.generation_tps:null, mem=m.stats?m.stats.used_mem_mb:m.estimated_mb, id=esc(m.id);
    return '<tr><td><strong>'+id+'</strong></td><td class="muted">'+m.model_type+'</td><td class="muted mono">'+(m.backend||'—')+'</td>'+
      '<td>'+st+pin+'</td><td class="num">'+fmt(mem)+'</td><td class="num">'+(tps==null?'—':tps.toFixed(1))+'</td><td class="num">'+m.in_use+'</td>'+
      '<td class="rowact">'+
        '<button class="btn sm" data-id="'+id+'" data-act="load" '+(m.loaded?'disabled':'')+'>Load</button>'+
        '<button class="btn sm" data-id="'+id+'" data-act="unload?force=true" '+(m.loaded?'':'disabled')+'>Unload</button>'+
        '<button class="btn sm" data-id="'+id+'" data-act="'+(m.pinned?'unpin':'pin')+'">'+(m.pinned?'Unpin':'Pin')+'</button>'+
      '</td></tr>';
  }).join('')||'<tr><td colspan="8" class="muted">no models discovered</td></tr>';
}
$('#rows').addEventListener('click',async e=>{
  const b=e.target.closest('button[data-act]'); if(!b) return;
  let act=b.dataset.act;
  if(act==='load'){ const dev=$('#devSel')&&$('#devSel').value; if(dev) act='load?device='+encodeURIComponent(dev); }
  try{ await api('/v1/models/'+b.dataset.id+'/'+act,'POST'); }
  catch(err){ $('#models-err').textContent=String(err); }
  tick();
});

/* Chat */
async function loadChatModels(){
  try{ const d=await api('/v1/models'); const sel=$('#chatModel'); const cur=sel.value;
    sel.innerHTML=d.data.map(m=>'<option value="'+esc(m.id)+'">'+esc(m.id)+'</option>').join('');
    if(cur&&d.data.some(m=>m.id===cur)) sel.value=cur;
  }catch(e){}
}
function addMsg(role,text){
  const d=document.createElement('div'); d.className='msg '+role;
  d.innerHTML='<div class="who">'+role+'</div><div class="body"></div>';
  d.querySelector('.body').textContent=text; $('#msgs').appendChild(d); scrollMsgs(); return d;
}
function scrollMsgs(){const m=$('#msgs');m.scrollTop=m.scrollHeight;}
async function sendChat(){
  const model=$('#chatModel').value, text=$('#chatInput').value.trim();
  if(!model||!text) return;
  addMsg('user',text); $('#chatInput').value='';
  const msgEl=addMsg('assistant',''); const body=msgEl.querySelector('.body'); let acc='';
  body.innerHTML='<span class="prefill">&#9203; prefilling&hellip;</span>';   // until the first token (TTFT)
  const t0=performance.now(); let ttft=null;
  try{
    const r=await fetch('/v1/chat/completions',{method:'POST',headers:Object.assign({'Content-Type':'application/json'},authHeaders()),
      body:JSON.stringify({model:model,messages:[{role:'user',content:text}],stream:true})});
    if(!r.ok){
      let detail=''; try{ const e=await r.json(); detail=(e&&e.error&&e.error.message)||''; }catch(_){}
      body.textContent = r.status===503
        ? '⚠ GPU busy — '+(detail||'cannot load this model while another model is in use')+'. Wait for the in-flight request to finish, or Unload/Pin from the Models tab, then resend.'
        : 'error: HTTP '+r.status+(detail?' · '+detail:'');
      return;
    }
    const reader=r.body.getReader(), dec=new TextDecoder(); let buf='';
    while(true){
      const {done,value}=await reader.read(); if(done) break;
      buf+=dec.decode(value,{stream:true}); let i;
      while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim(); buf=buf.slice(i+1);
        if(!line.startsWith('data:')) continue;
        const p=line.slice(5).trim(); if(p==='[DONE]') continue;
        try{ const o=JSON.parse(p); const dc=o.choices&&o.choices[0]&&o.choices[0].delta&&o.choices[0].delta.content;
          if(dc){ if(ttft==null){ ttft=performance.now()-t0; body.textContent=''; } acc+=dc; body.textContent=acc; scrollMsgs(); } }catch(e){}
      }
    }
    if(!acc) body.textContent='(empty response)';
    if(ttft!=null){ const meta=document.createElement('div'); meta.className='msg-meta'; meta.textContent='first token '+(ttft/1000).toFixed(2)+'s'; msgEl.appendChild(meta); scrollMsgs(); }
  }catch(e){ body.textContent='error: '+e; }
}
$('#sendBtn').onclick=sendChat;
$('#chatClear').onclick=()=>{ $('#msgs').innerHTML=''; };
$('#chatInput').addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendChat(); }});

/* Logs */
async function refreshLogs(){
  if(logsPaused) return;
  try{ const d=await api('/api/logs?limit=300'); const el=$('#logs');
    const atBottom=el.scrollHeight-el.scrollTop-el.clientHeight<40;
    el.innerHTML=(d.lines||[]).map(l=>'<div class="logline '+esc(l.level)+'">'+esc(l.line)+'</div>').join('')||'<div class="muted">no logs yet</div>';
    if(atBottom) el.scrollTop=el.scrollHeight;
  }catch(e){}
}
$('#logsPause').onchange=e=>{ logsPaused=e.target.checked; };

/* Settings */
async function loadSettings(){
  try{ const s=await api('/api/settings');
    $('#setIdle').value=s.idle_timeout;
    if($('#setKvHot')) $('#setKvHot').value=s.kv_hot_capacity;
    if($('#setKvCold')) $('#setKvCold').value=s.kv_cold_dir||'';
    if($('#setHfEndpoint')) $('#setHfEndpoint').value=s.hf_endpoint||'';
    const gv=(el,v)=>{ if($(el)) $(el).value=(v==null?'':v); };
    gv('#setGenTemp',s.gen_temperature); gv('#setGenTopP',s.gen_top_p); gv('#setGenTopK',s.gen_top_k); gv('#setGenMax',s.gen_max_tokens);
    $('#keyState').textContent=s.api_key?'set':'unset';
    const order=['backend','model_dir','host','port','max_concurrent_requests','idle_timeout','max_process_memory','ttl_check_interval','sse_keepalive_interval','kv_hot_capacity','kv_cold_dir','hf_endpoint','gen_temperature','gen_top_p','gen_top_k','gen_max_tokens','api_key'];
    $('#settingsKv').innerHTML=order.filter(k=>k in s).map(k=>'<dt>'+k+'</dt><dd>'+(k==='api_key'?(s[k]?'set':'unset'):esc(s[k]==null?'—':s[k]))+'</dd>').join('');
  }catch(e){ $('#settings-err').textContent=String(e); }
}
async function saveIdle(){
  try{ const v=parseFloat($('#setIdle').value); await api('/api/settings','PUT',{idle_timeout:isNaN(v)?0:v}); toast('Idle timeout saved'); loadSettings(); }
  catch(e){ $('#settings-err').textContent=String(e); }
}
async function applyKey(){
  const v=$('#setKey').value;
  try{ const r=await api('/api/settings','PUT',{api_key:v}); $('#setKey').value='';
    if(r.settings.api_key){ $('#apikey').value=v; toast('API key set — dashboard will use it'); }
    else { $('#apikey').value=''; toast('API key cleared (auth off)'); }
    loadSettings();
  }catch(e){ $('#settings-err').textContent=String(e); }
}
async function saveKv(){
  try{ const hot=parseInt($('#setKvHot').value); const cold=$('#setKvCold').value;
    await api('/api/settings','PUT',{kv_hot_capacity:isNaN(hot)?0:hot, kv_cold_dir:cold});
    toast('KV cache settings saved'); loadSettings();
  }catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveIdle').onclick=saveIdle;
$('#applyKey').onclick=applyKey;
$('#saveKv').onclick=saveKv;
async function saveHf(){
  try{ await api('/api/settings','PUT',{hf_endpoint:$('#setHfEndpoint').value}); toast('HuggingFace endpoint saved'); loadSettings(); }
  catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveHf').onclick=saveHf;
async function saveGen(){
  const num=el=>{ const v=$(el).value.trim(); if(v==='') return null; const n=Number(v); return isNaN(n)?null:n; };
  try{ await api('/api/settings','PUT',{gen_temperature:num('#setGenTemp'),gen_top_p:num('#setGenTopP'),gen_top_k:num('#setGenTopK'),gen_max_tokens:num('#setGenMax')});
    toast('generation defaults saved'); loadSettings();
  }catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveGen').onclick=saveGen;

/* Metrics */
function drawChart(id, vals, color, unit){
  const c=$('#'+id); if(!c) return;
  const w=c.clientWidth||600, h=130, dpr=window.devicePixelRatio||1;
  c.width=w*dpr; c.height=h*dpr; const x=c.getContext('2d'); x.setTransform(dpr,0,0,dpr,0,0);
  x.clearRect(0,0,w,h);
  if(!vals.length){ x.fillStyle='#64748b'; x.font='12px ui-monospace,monospace'; x.fillText('no data yet — generate chat completions',12,h/2); return; }
  const max=(Math.max.apply(null,vals)||1)*1.15, n=vals.length, padL=42;
  const px=i=> padL + (w-padL-8)*(n<=1?0.5:i/(n-1));
  const py=v=> h-8 - (h-26)*(v/max);
  const cs=getComputedStyle(document.documentElement);
  const gridC=(cs.getPropertyValue('--border')||'#1f2a3b').trim(), labC=(cs.getPropertyValue('--dim')||'#64748b').trim();
  x.strokeStyle=gridC; x.lineWidth=1; x.fillStyle=labC; x.font='10px ui-monospace,monospace';
  for(let g=0;g<=2;g++){ const yy=py(max*g/2); x.beginPath(); x.moveTo(padL,yy); x.lineTo(w-8,yy); x.stroke(); x.fillText(Math.round(max*g/2),6,yy+3); }
  x.beginPath(); vals.forEach((v,i)=>{ const X=px(i),Y=py(v); i?x.lineTo(X,Y):x.moveTo(X,Y); });
  x.strokeStyle=color; x.lineWidth=2; x.stroke();
  x.lineTo(px(n-1),h-8); x.lineTo(px(0),h-8); x.closePath(); x.fillStyle=color+'22'; x.fill();
  x.fillStyle=color; x.font='600 12px ui-monospace,monospace'; x.fillText(vals[n-1]+' '+unit, w-118, 16);
}
/* Stats (session / all-time) */
let statsScope='session', lastStats=null;
function statN(n){ return (n!=null)?(typeof n==='number'?n.toLocaleString():n):'—'; }
function statCard(k,v){ return '<div class="card"><div class="k">'+k+'</div><div class="v">'+v+'</div></div>'; }
function fmtUptime(sec){ sec=Math.floor(sec||0); const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60),s=sec%60; if(d) return d+'d '+h+'h'; if(h) return h+'h '+m+'m'; if(m) return m+'m '+s+'s'; return s+'s'; }
async function refreshStats(){
  try{ const sel=$('#stModel'); const model=sel?sel.value:'';
    const s=await api('/api/stats?scope='+statsScope+(model?'&model='+encodeURIComponent(model):'')); lastStats=s;
    if(sel){ const cur=sel.value; sel.innerHTML='<option value="">All models</option>'+(s.models||[]).map(m=>'<option value="'+esc(m)+'">'+esc(m)+'</option>').join(''); sel.value=cur; }
    const req=s.total_requests||0, rej=s.total_rejections||0, served=s.total_tokens_served||0;
    const pt=s.total_prompt_tokens||0, ct=s.total_completion_tokens||0, cached=s.total_cached_tokens||0;
    const avgTok=req?Math.round(served/req):0, succ=(req+rej)?(req/(req+rej)*100):100;
    $('#statCards').innerHTML=
      statCard('Requests', statN(req))+
      statCard('Tokens served', statN(served))+
      statCard('Avg tokens/req', statN(avgTok))+
      statCard('Prompt tokens', statN(pt))+
      statCard('Completion tokens', statN(ct))+
      statCard('Cached tokens', statN(cached))+
      statCard('Prefill', statN(s.prefill_tps)+'<small> tok/s</small>')+
      statCard('Generation', statN(s.generation_tps)+'<small> tok/s</small>')+
      statCard('Uptime', fmtUptime(s.uptime_seconds))+
      statCard('Success rate', (req+rej?succ.toFixed(1):'100')+'<small> % &middot; '+statN(rej)+' rej</small>');
    const pNew=Math.max(0,pt-cached), tot=(pNew+cached+ct)||1;
    const seg=(v,c)=> v>0?'<span style="width:'+(v/tot*100)+'%;background:'+c+'"></span>':'';
    if($('#tokBar')) $('#tokBar').innerHTML=seg(pNew,'var(--blue)')+seg(cached,'var(--accent)')+seg(ct,'var(--warn)');
    const leg=(c,l,v)=>'<span><i style="background:'+c+'"></i>'+l+'<b>'+statN(v)+'</b></span>';
    if($('#tokLeg')) $('#tokLeg').innerHTML=leg('var(--blue)','Prompt (new)',pNew)+leg('var(--accent)','Cached',cached)+leg('var(--warn)','Completion',ct);
    const ce=+s.cache_efficiency||0;
    if($('#cacheV')) $('#cacheV').innerHTML=statN(s.cache_efficiency)+'<small> %</small>';
    if($('#cacheBar')) $('#cacheBar').style.width=Math.min(100,ce)+'%';
    if($('#cacheSub')) $('#cacheSub').textContent=statN(cached)+' of '+statN(pt)+' prompt tokens reused from cache';
    const rj=s.rejections||{}; const rks=Object.keys(rj);
    if($('#statRej')) $('#statRej').innerHTML = rks.length? ('rejected &mdash; '+rks.map(k=>esc(k)+': '+rj[k]).join(' &middot; ')) : 'none';
  }catch(e){}
}
function setStatsScope(sc){ statsScope=sc;
  $('#stScopeSession').classList.toggle('active',sc==='session');
  $('#stScopeAll').classList.toggle('active',sc==='alltime');
  refreshStats(); refreshPerModel();
}
$('#stScopeSession').onclick=()=>setStatsScope('session');
$('#stScopeAll').onclick=()=>setStatsScope('alltime');
$('#stClear').onclick=async()=>{ try{ await api('/api/stats/clear?scope='+statsScope,'POST'); refreshStats(); toast('cleared '+statsScope+' stats'); }catch(e){} };
$('#stModel').onchange=refreshStats;
/* Metrics sub-tabs + per-model table */
let pmRows=[], pmSort={key:'total_requests',dir:-1};
function setMetricsTab(t){
  $$('#mtTabs .seg-btn').forEach(b=>b.classList.toggle('active',b.dataset.mt===t));
  ['overview','permodel','charts','rejections'].forEach(p=>{ const el=$('#mt-'+p); if(el) el.style.display=(p===t)?'':'none'; });
  refreshLive();
  if(t==='charts') refreshMetrics(); else if(t==='permodel') refreshPerModel(); else refreshStats();
}
$$('#mtTabs .seg-btn').forEach(b=>b.onclick=()=>setMetricsTab(b.dataset.mt));
async function refreshPerModel(){
  try{ const d=await api('/api/stats/models?scope='+statsScope); pmRows=d.models||[]; renderPerModel(); }catch(e){}
}
function renderPerModel(){
  const rows=pmRows.slice().sort((a,b)=>{ const k=pmSort.key, av=a[k], bv=b[k];
    return (typeof av==='string')? pmSort.dir*String(av).localeCompare(String(bv)) : pmSort.dir*((av||0)-(bv||0)); });
  $('#pmRows').innerHTML=rows.map(r=>'<tr><td><strong>'+esc(r.model)+'</strong></td><td class="num">'+statN(r.total_requests)+'</td><td class="num">'+statN(r.generation_tps)+'</td><td class="num">'+statN(r.total_tokens_served)+'</td><td class="num">'+statN(r.cache_efficiency)+'</td></tr>').join('')||'<tr><td colspan="5" class="muted">no per-model data yet</td></tr>';
}
$('#mt-permodel').addEventListener('click',e=>{ const th=e.target.closest('th[data-sort]'); if(!th) return;
  const k=th.dataset.sort; pmSort.dir=(pmSort.key===k)?-pmSort.dir:-1; pmSort.key=k; renderPerModel(); });
/* Metrics: live bar + export/copy */
async function refreshLive(){
  try{ const s=await api('/api/status'); let active=0, queue=0, loaded=0;
    (s.models||[]).forEach(m=>{ if(m.loaded){ loaded++; if(m.stats){ active+=m.stats.active_requests||0; queue+=m.stats.queue_depth||0; } } });
    let tps=0; try{ const ms=await api('/api/metrics'); const r=(ms.samples||[]).slice(-5); if(r.length) tps=r.reduce((a,x)=>a+(x.tps||0),0)/r.length; }catch(_){}
    if($('#liveBar')) $('#liveBar').innerHTML=
      statCard('Loaded models', statN(loaded))+
      statCard('Active requests', statN(active))+
      statCard('Queue depth', statN(queue))+
      statCard('Recent', statN(Math.round(tps))+'<small> tok/s</small>');
  }catch(e){}
}
$('#stCopy').onclick=()=>{ if(!lastStats){ toast('no stats yet'); return; }
  const txt=JSON.stringify(lastStats,null,2);
  if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(()=>toast('stats copied')).catch(()=>toast('copy failed'));
  else toast('clipboard unavailable'); };
$('#stExport').onclick=async()=>{ try{ const ms=await api('/api/metrics'); const rows=ms.samples||[];
    const head='t,model,latency_ms,tokens,tps'; const body=rows.map(r=>[r.t,r.model,r.latency_ms,r.tokens,r.tps].join(',')).join('\n');
    const blob=new Blob([head+'\n'+body],{type:'text/csv'}); const a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download='infermesh-metrics.csv'; a.click(); URL.revokeObjectURL(a.href); toast('exported '+rows.length+' samples');
  }catch(e){ toast('export failed'); } };
let chRange=0;  // charts time window in seconds (0 = all)
async function refreshMetrics(){
  try{ const d=await api('/api/metrics'); let s=d.samples||[];
    if(chRange){ const now=Date.now()/1000; s=s.filter(p=>now-(p.t||0)<=chRange); }
    const lat=s.map(p=>p.latency_ms), tps=s.map(p=>p.tps);
    const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
    const sl=lat.slice().sort((a,b)=>a-b), p95=sl.length?sl[Math.min(sl.length-1,Math.floor(0.95*sl.length))]:0;
    const peak=tps.length?Math.max.apply(null,tps):0;
    $('#metricCards').innerHTML=
      '<div class="card"><div class="k">Requests</div><div class="v">'+s.length+'</div></div>'+
      '<div class="card"><div class="k">Avg latency</div><div class="v">'+avg(lat).toFixed(0)+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">p95 latency</div><div class="v">'+p95.toFixed(0)+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">Avg throughput</div><div class="v">'+avg(tps).toFixed(1)+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">Peak throughput</div><div class="v">'+peak.toFixed(1)+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">Last latency</div><div class="v">'+(s.length?Math.round(s[s.length-1].latency_ms):'—')+'<small> ms</small></div></div>';
    const cs=getComputedStyle(document.documentElement);
    const cBlue=(cs.getPropertyValue('--blue')||'#58a6ff').trim(), cGreen=(cs.getPropertyValue('--accent')||'#22c55e').trim();
    drawChart('chartLatency', lat, cBlue, 'ms');
    drawChart('chartTps', tps, cGreen, 'tok/s');
  }catch(e){}
}
$$('#chRange .seg-btn').forEach(b=>b.onclick=()=>{ chRange=+b.dataset.r;
  $$('#chRange .seg-btn').forEach(x=>x.classList.toggle('active',x===b)); refreshMetrics(); });

/* Benchmark */
async function loadBenchModels(){
  try{ const d=await api('/v1/models'); const sel=$('#bmModel'); const cur=sel.value;
    sel.innerHTML=d.data.map(m=>'<option value="'+esc(m.id)+'">'+esc(m.id)+'</option>').join('');
    if(cur&&d.data.some(m=>m.id===cur)) sel.value=cur;
  }catch(e){}
}
async function runBenchmark(){
  const model=$('#bmModel').value;
  if(!model){ $('#bm-err').textContent='pick a model'; return; }
  const body={model:model, requests:(+$('#bmReq').value||20), concurrency:(+$('#bmConc').value||4), max_tokens:(+$('#bmTok').value||64), mode:($('#bmMode')?$('#bmMode').value:'same')};
  $('#bm-err').textContent=''; $('#bmStatus').textContent='running '+body.requests+' req @ conc '+body.concurrency+'… (real models take a few s)';
  $('#bmRun').disabled=true;
  try{
    const r=await api('/api/benchmark','POST',body);
    lastBench=r;
    $('#bmStatus').textContent='done in '+r.wall_time_s+'s · mode: '+(r.mode||'same');
    const pk=(r.peak_mem_mb!=null)?(fmt(r.peak_mem_mb)+' MB'):'—';
    $('#bmCards').innerHTML=
      '<div class="card"><div class="k">Prefill (PP)</div><div class="v">'+r.pp_tps.mean+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">Decode (TG)</div><div class="v">'+r.tg_tps.mean+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">TPOT</div><div class="v">'+r.tpot_ms.mean+'<small> ms/tok</small></div></div>'+
      '<div class="card"><div class="k">TTFT p50</div><div class="v">'+r.ttft_ms.p50+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">E2E p50</div><div class="v">'+r.latency_ms.p50+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">Throughput</div><div class="v">'+r.requests_per_sec+'<small> req/s</small></div></div>'+
      '<div class="card"><div class="k">Output</div><div class="v">'+r.output_tokens_per_sec+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">Peak GPU mem</div><div class="v">'+pk+'</div></div>'+
      '<div class="card"><div class="k">Succeeded</div><div class="v">'+r.succeeded+'<small> / '+(r.succeeded+r.failed)+'</small></div></div>';
    const L=r.latency_ms, T=r.ttft_ms, P=r.tpot_ms;
    $('#bmLatency').innerHTML=['mean','p50','p90','p99','min','max'].map(k=>'<dt>'+k+'</dt><dd>'+L[k]+'</dd>').join('');
    $('#bmTtft').innerHTML=['mean','p50','p90','p99'].map(k=>'<dt>'+k+'</dt><dd>'+T[k]+'</dd>').join('');
    $('#bmTpot').innerHTML=['mean','p50','p90','p99'].map(k=>'<dt>'+k+'</dt><dd>'+P[k]+'</dd>').join('');
    $('#bmDetail').style.display='block';
    drawBars('bmChart', [['p50',L.p50],['p90',L.p90],['p99',L.p99],['max',L.max]]);
    refreshBenchHistory();
  }catch(e){ $('#bm-err').textContent=String(e); $('#bmStatus').textContent=''; }
  finally{ $('#bmRun').disabled=false; }
}
function drawBars(id, pairs){
  const c=$('#'+id); if(!c) return;
  const w=c.clientWidth||600, h=160, dpr=window.devicePixelRatio||1;
  c.width=w*dpr; c.height=h*dpr; const x=c.getContext('2d'); x.setTransform(dpr,0,0,dpr,0,0); x.clearRect(0,0,w,h);
  const cs=getComputedStyle(document.documentElement);
  const labC=(cs.getPropertyValue('--dim')||'#64748b').trim(), barC=(cs.getPropertyValue('--blue')||'#58a6ff').trim();
  const max=(Math.max.apply(null,pairs.map(p=>p[1]))||1), n=pairs.length, slot=(w-20)/n;
  x.font='11px ui-monospace,monospace'; x.textAlign='center';
  pairs.forEach((p,i)=>{ const bh=(h-44)*(p[1]/max), bx=10+i*slot+slot*0.18, bw=slot*0.64, by=h-26-bh;
    x.fillStyle=barC; x.fillRect(bx,by,bw,bh);
    x.fillStyle=labC; x.fillText(p[0], bx+bw/2, h-9); x.fillText(p[1], bx+bw/2, by-5); });
}
$('#bmRun').onclick=runBenchmark;
$('#bmSingle').onclick=()=>{ $('#bmReq').value=1; $('#bmConc').value=1; runBenchmark(); };
$('#bmCopy').onclick=()=>{ if(!lastBench){ toast('run a benchmark first'); return; }
  const txt=JSON.stringify(lastBench,null,2);
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(()=>toast('results copied')).catch(()=>toast('copy failed')); }
  else { toast('clipboard unavailable in this context'); }
};

/* Devices */
function devCell(n){ return n ? (fmt(n)+' MB') : '—'; }
async function refreshDevices(){
  try{ const d=await api('/api/devices');
    $('#devRows').innerHTML=(d.devices||[]).map(x=>'<tr><td class="mono">'+esc(x.id)+'</td><td>'+esc(x.vendor)+'</td><td>'+esc(x.name)+'</td><td class="num">'+devCell(x.mem_used_mb)+'</td><td class="num">'+devCell(x.mem_free_mb)+'</td><td class="num">'+devCell(x.mem_total_mb)+'</td></tr>').join('')||'<tr><td colspan="6" class="muted">none</td></tr>';
  }catch(e){ $('#devRows').innerHTML='<tr><td colspan="6" class="err">'+esc(String(e))+'</td></tr>'; }
}
async function loadDevicePicker(){
  const sel=$('#devSel'); if(!sel) return;
  try{ const d=await api('/api/devices'); const cur=sel.value;
    sel.innerHTML='<option value="">auto</option>'+(d.devices||[]).map(x=>'<option value="'+esc(x.id)+'">'+esc(x.id)+' · '+esc(x.name)+'</option>').join('');
    if(cur) sel.value=cur;
  }catch(e){}
}
$('#devRefresh').onclick=refreshDevices;
/* Benchmark history */
async function refreshBenchHistory(){
  try{ const h=await api('/api/history'); const rows=(h.benchmarks||[]).slice().reverse();
    $('#bmHist').innerHTML=rows.map((x,i)=>bmSummaryRow(x,i)+bmDetailRow(x,i)).join('')||'<tr><td colspan="8" class="muted">no past runs</td></tr>';
  }catch(e){}
}
function bmn(v){ return v!=null?v:'—'; }
function bmKv(obj,keys){ return '<dl class="kv kv-sm">'+keys.map(k=>'<dt>'+k+'</dt><dd>'+bmn(obj&&obj[k])+'</dd>').join('')+'</dl>'; }
function bmRows(pairs){ return '<dl class="kv kv-sm">'+pairs.map(p=>'<dt>'+p[0]+'</dt><dd>'+bmn(p[1])+'</dd>').join('')+'</dl>'; }
function bmBlock(title,body){ return '<div class="bm-block"><div class="bm-bt">'+title+'</div>'+body+'</div>'; }
function bmSummaryRow(x,i){
  const r=x.result||{}, L=r.latency_ms||{}, p=x.params||{};
  let when=''; try{ when=new Date((x.t||0)*1000).toLocaleString(); }catch(_){ }
  return '<tr><td><button class="btn sm bm-exp" data-i="'+i+'" aria-label="expand">&#9656;</button></td>'+
    '<td class="muted">'+esc(when)+'</td><td><strong>'+esc(x.model||'')+'</strong> <span class="muted" style="font-size:11px">'+esc(r.mode||'')+'</span></td>'+
    '<td class="num">'+bmn(p.requests)+'&times;'+bmn(p.concurrency)+'</td>'+
    '<td class="num">'+bmn(r.requests_per_sec)+'</td><td class="num">'+bmn(r.output_tokens_per_sec)+'</td>'+
    '<td class="num">'+bmn(L.p50)+'</td><td class="num">'+bmn(L.p99)+'</td></tr>';
}
function bmDetailRow(x,i){
  return '<tr class="bm-det" id="bm-det-'+i+'" style="display:none"><td colspan="8" style="padding:0">'+bmDetail(x)+'</td></tr>';
}
function bmDetail(x){
  const r=x.result||{}, p=x.params||{};
  const L=r.latency_ms||{}, T=r.ttft_ms||{}, P=r.tpot_ms||{}, pp=r.pp_tps||{}, tg=r.tg_tps||{};
  const single=(p.requests==1&&p.concurrency==1);
  const pk=r.peak_mem_mb!=null?(fmt(r.peak_mem_mb)+' MB'):'—';
  const succ=(r.succeeded!=null?r.succeeded+' / '+((r.succeeded||0)+(r.failed||0)):'—');
  return '<div class="bm-grid">'+
    bmBlock('Context', bmRows([['model',esc(r.model||x.model||'')],['mode',esc(r.mode||'—')],['type',single?'single request':'continuous batching'],['requests',p.requests],['concurrency',p.concurrency],['max tokens',p.max_tokens],['wall time (s)',r.wall_time_s],['succeeded',succ]]))+
    bmBlock('Throughput', bmRows([['requests / s',r.requests_per_sec],['output tok / s',r.output_tokens_per_sec]]))+
    bmBlock('Prefill &mdash; PP TPS', bmRows([['mean',pp.mean],['max',pp.max],['prompt tokens',r.total_prompt_tokens]]))+
    bmBlock('Decode &mdash; TG TPS', bmRows([['mean',tg.mean],['max',tg.max],['output tokens',r.total_output_tokens]]))+
    bmBlock('Single-request latency / E2E (ms)', bmKv(L,['mean','p50','p90','p99','min','max']))+
    bmBlock('Time to first token (ms)', bmKv(T,['mean','p50','p90','p99','min','max']))+
    bmBlock('Time per output token (ms)', bmKv(P,['mean','p50','p90','p99']))+
    bmBlock('Peak GPU memory', bmRows([['peak',pk]]))+
  '</div>';
}
$('#bmHist').addEventListener('click',e=>{ const b=e.target.closest('button.bm-exp'); if(!b) return;
  const det=document.getElementById('bm-det-'+b.dataset.i); if(!det) return;
  const open=det.style.display==='none'; det.style.display=open?'table-row':'none'; b.innerHTML=open?'&#9662;':'&#9656;';
});
/* Download (HuggingFace) */
function fmtBytes(n){ if(!n) return '—'; const u=['B','KB','MB','GB','TB']; let i=0,x=n; while(x>=1024&&i<u.length-1){x/=1024;i++;} return x.toFixed(x<10&&i>0?1:0)+' '+u[i]; }
async function runHfSearch(){
  const q=$('#dlSearch').value.trim();
  const sort=$('#dlSort')?$('#dlSort').value:'downloads', task=$('#dlTask')?$('#dlTask').value:'';
  $('#dl-err').textContent=''; $('#dlResults').innerHTML='<tr><td colspan="5" class="muted">'+(q?'searching':'loading popular models')+'&hellip;</td></tr>';
  try{ const d=await api('/api/hf/search?limit=25&q='+encodeURIComponent(q)+'&sort='+sort+'&task='+encodeURIComponent(task));
    $('#dlResults').innerHTML=(d.models||[]).map(m=>'<tr><td class="mono">'+esc(m.id)+(m.gated?' <span class="badge">gated</span>':'')+'</td><td class="muted">'+esc(m.pipeline_tag||'—')+'</td><td class="num">'+fmt(m.downloads)+'</td><td class="num">'+fmt(m.likes)+'</td><td class="rowact"><button class="btn sm" data-repo="'+esc(m.id)+'">Download</button></td></tr>').join('')||'<tr><td colspan="5" class="muted">no results</td></tr>';
  }catch(e){ $('#dl-err').textContent=String(e); $('#dlResults').innerHTML='<tr><td colspan="5" class="muted">search failed</td></tr>'; }
}
async function hfDownload(repo){
  try{ await api('/api/hf/download','POST',{repo_id:repo}); toast('downloading '+repo); refreshDownloads(); }
  catch(e){ $('#dl-err').textContent=String(e); }
}
async function refreshDownloads(){
  try{ const d=await api('/api/hf/downloads');
    $('#dlJobs').innerHTML=(d.downloads||[]).map(j=>{ const pctn=Math.round((j.progress||0)*100);
      const bar='<div class="bar" style="min-width:90px;display:inline-block;vertical-align:middle"><i style="width:'+pctn+'%"></i></div>';
      const stat=j.status==='error'?'<span class="err">error</span>':esc(j.status);
      return '<tr><td class="mono">'+esc(j.repo_id)+'</td><td>'+stat+(j.error?' <span class="muted">'+esc(j.error)+'</span>':'')+'</td><td>'+(j.status==='done'?'100%':bar+' '+pctn+'%')+'</td><td class="num">'+fmtBytes(j.total_bytes)+'</td></tr>';
    }).join('')||'<tr><td colspan="4" class="muted">no downloads yet</td></tr>';
  }catch(e){}
}
let dlLoaded=false;
$('#dlBtn').onclick=runHfSearch;
$('#dlSort').onchange=runHfSearch; $('#dlTask').onchange=runHfSearch;
$('#dlSearch').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); runHfSearch(); }});
$('#dlResults').addEventListener('click',e=>{ const b=e.target.closest('button[data-repo]'); if(b) hfDownload(b.dataset.repo); });
/* poll */
$('#refreshBtn').onclick=()=>tick();
loadDevicePicker();
fetch('/health').then(r=>r.json()).then(h=>{ if(h&&h.version) $('#sb-ver').textContent='v'+h.version+' · mock / vllm / openai / transformers'; }).catch(()=>{});
async function tick(){
  try{ const s=await api('/api/status'); setHealth(true); if(active==='models'){ renderModels(s); $('#models-err').textContent=''; } }
  catch(e){ setHealth(false); if(active==='models') $('#models-err').textContent=String(e); }
  if(active==='logs') refreshLogs();
  if(active==='metrics'){ refreshMetrics(); refreshStats(); refreshLive(); }
  if(active==='download') refreshDownloads();
}
setInterval(tick,2000); tick();
</script>
</body>
</html>
"""
