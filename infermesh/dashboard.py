# SPDX-License-Identifier: Apache-2.0
"""Self-contained admin dashboard (single HTML page, no build step, no deps).

Served by the gateway at ``GET /`` and ``GET /admin``. The page polls the
existing ``/api/status`` endpoint and posts to the model load/unload/pin/unpin
endpoints — so it adds zero coupling beyond the public HTTP API.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>infermesh · admin</title>
<style>
  :root {
    --bg:#0b0f14; --panel:#131a22; --panel2:#1a232e; --border:#243240;
    --text:#e6edf3; --muted:#8b98a5; --accent:#3fb950; --accent2:#58a6ff;
    --warn:#d29922; --danger:#f85149;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:14px 24px;
    border-bottom:1px solid var(--border); background:var(--panel);
    position:sticky; top:0; z-index:10; }
  header h1 { font-size:17px; margin:0; font-weight:600; letter-spacing:.4px; }
  .logo { color:var(--accent); }
  .pill { font-size:12px; padding:2px 10px; border-radius:999px;
    border:1px solid var(--border); color:var(--muted); }
  .pill.ok { color:var(--accent); border-color:var(--accent); }
  .pill.bad { color:var(--danger); border-color:var(--danger); }
  main { padding:24px; max-width:1120px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
    gap:16px; margin-bottom:24px; }
  .card { background:var(--panel); border:1px solid var(--border);
    border-radius:10px; padding:16px; }
  .card .label { color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.6px; }
  .card .value { font-size:24px; font-weight:600; margin-top:6px; }
  .bar { height:8px; background:var(--panel2); border-radius:4px;
    overflow:hidden; margin-top:12px; }
  .bar > div { height:100%; background:linear-gradient(90deg,var(--accent2),var(--accent));
    transition:width .4s ease; }
  table { width:100%; border-collapse:collapse; background:var(--panel);
    border:1px solid var(--border); border-radius:10px; overflow:hidden; }
  th,td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--border);
    white-space:nowrap; }
  th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.6px; }
  tr:last-child td { border-bottom:none; }
  tbody tr:hover { background:var(--panel2); }
  .badge { font-size:11px; padding:2px 8px; border-radius:6px;
    border:1px solid var(--border); color:var(--muted); }
  .badge.loaded { color:var(--accent); border-color:var(--accent); }
  .badge.loading { color:var(--accent2); border-color:var(--accent2); }
  .badge.pinned { color:var(--warn); border-color:var(--warn); }
  button { font:inherit; font-size:12px; padding:4px 10px; border-radius:6px;
    border:1px solid var(--border); background:var(--panel2); color:var(--text); cursor:pointer; }
  button:hover:not(:disabled) { border-color:var(--accent2); color:#fff; }
  button:disabled { opacity:.35; cursor:default; }
  .actions { display:flex; gap:6px; }
  .controls { display:flex; gap:14px; align-items:center; margin-bottom:14px; }
  input { font:inherit; background:var(--panel2); border:1px solid var(--border);
    color:var(--text); border-radius:6px; padding:6px 10px; }
  .muted { color:var(--muted); }
  .err { color:var(--danger); min-height:18px; margin-top:14px; font-size:13px; }
  a { color:var(--accent2); text-decoration:none; }
  code { background:var(--panel2); padding:1px 5px; border-radius:4px; }
</style>
</head>
<body>
<header>
  <h1><span class="logo">&#9672;</span> infermesh <span class="muted" style="font-weight:400">admin</span></h1>
  <span id="health" class="pill">connecting&hellip;</span>
  <span style="flex:1"></span>
  <input id="apikey" placeholder="API key (only if enabled)" size="22" autocomplete="off"/>
  <span id="updated" class="muted" style="font-size:12px"></span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="controls">
    <strong>Models</strong>
    <span id="counts" class="muted"></span>
    <span style="flex:1"></span>
    <label class="muted" style="font-size:12px"><input type="checkbox" id="auto" checked/> auto-refresh (2s)</label>
    <button onclick="refresh()">&#8635; refresh</button>
  </div>
  <table>
    <thead><tr>
      <th>Model</th><th>Type</th><th>Backend</th><th>Status</th>
      <th>Mem MB</th><th>Gen tps</th><th>Leases</th><th>Actions</th>
    </tr></thead>
    <tbody id="rows"><tr><td colspan="8" class="muted">loading&hellip;</td></tr></tbody>
  </table>
  <p id="error" class="err"></p>
  <p class="muted" style="font-size:12px">
    Polls <a href="/api/status">/api/status</a>. Actions call
    <code>/v1/models/&lt;id&gt;/{load,unload,pin,unpin}</code>.
  </p>
</main>
<script>
const $ = s => document.querySelector(s);
const authHeaders = () => {
  const k = $('#apikey').value.trim();
  return k ? { 'Authorization': 'Bearer ' + k } : {};
};
async function api(path, method) {
  const r = await fetch(path, { method: method || 'GET', headers: authHeaders() });
  if (!r.ok) throw new Error(path + ' → HTTP ' + r.status);
  return r.json();
}
const fmt = n => (n == null ? '—' : Number(n).toLocaleString());

async function refresh() {
  try {
    const s = await api('/api/status');
    $('#error').textContent = '';
    $('#health').textContent = 'healthy';
    $('#health').className = 'pill ok';
    $('#updated').textContent = 'updated ' + new Date().toLocaleTimeString();

    const pct = s.ceiling_mb ? Math.min(100, Math.round(100 * s.used_mb_live / s.ceiling_mb)) : 0;
    $('#cards').innerHTML = `
      <div class="card"><div class="label">Models loaded</div>
        <div class="value">${s.loaded_count} / ${s.model_count}</div></div>
      <div class="card"><div class="label">Committed model mem</div>
        <div class="value">${fmt(s.current_model_memory_mb)} MB</div></div>
      <div class="card"><div class="label">Live used / ceiling</div>
        <div class="value">${fmt(s.used_mb_live)} / ${fmt(s.ceiling_mb)}</div>
        <div class="bar"><div style="width:${pct}%"></div></div></div>
      <div class="card"><div class="label">Host RAM</div>
        <div class="value">${fmt(s.total_mb)} MB</div></div>`;
    $('#counts').textContent = `(${s.model_count} discovered, ${s.loaded_count} loaded)`;

    const rows = (s.models || []).map(m => {
      const status = m.is_loading ? '<span class="badge loading">loading</span>'
        : m.loaded ? '<span class="badge loaded">loaded</span>'
        : '<span class="badge">idle</span>';
      const pinned = m.pinned ? ' <span class="badge pinned">pinned</span>' : '';
      const tps = m.stats ? m.stats.generation_tps : null;
      const mem = m.stats ? m.stats.used_mem_mb : m.estimated_mb;
      const id = m.id;
      return `<tr>
        <td><strong>${id}</strong></td>
        <td class="muted">${m.model_type}</td>
        <td class="muted">${m.backend || '—'}</td>
        <td>${status}${pinned}</td>
        <td>${fmt(mem)}</td>
        <td>${tps == null ? '—' : tps.toFixed(1)}</td>
        <td>${m.in_use}</td>
        <td class="actions">
          <button onclick="act('${id}','load')" ${m.loaded ? 'disabled' : ''}>Load</button>
          <button onclick="act('${id}','unload?force=true')" ${m.loaded ? '' : 'disabled'}>Unload</button>
          <button onclick="act('${id}','${m.pinned ? 'unpin' : 'pin'}')">${m.pinned ? 'Unpin' : 'Pin'}</button>
        </td></tr>`;
    }).join('');
    $('#rows').innerHTML = rows || '<tr><td colspan="8" class="muted">no models discovered</td></tr>';
  } catch (e) {
    $('#health').textContent = 'unreachable';
    $('#health').className = 'pill bad';
    $('#error').textContent = String(e);
  }
}
async function act(id, action) {
  try { await api('/v1/models/' + id + '/' + action, 'POST'); }
  catch (e) { $('#error').textContent = String(e); }
  refresh();
}
setInterval(() => { if ($('#auto').checked) refresh(); }, 2000);
refresh();
</script>
</body>
</html>
"""
