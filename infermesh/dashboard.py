# SPDX-License-Identifier: Apache-2.0
"""Self-contained admin dashboard (single HTML page, no build step, no CDN, no deps).

Served by the gateway at ``GET /`` and ``GET /admin``. Four sections via a left
sidebar — Models, Chat, Logs, Settings — driven entirely by the public HTTP API
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
      <button data-sec="settings" aria-label="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg> Settings</button>
    </nav>
    <div class="sb-foot">
      <span id="sb-health" class="pill"><span class="dot"></span> connecting</span>
      <span>v0.1.0 · mock / vllm</span>
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
let active='models', logsPaused=false;
const TITLES={models:'Models',chat:'Chat',logs:'Logs',metrics:'Metrics',settings:'Settings'};
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
  if(sec==='metrics') refreshMetrics();
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
  try{ await api('/v1/models/'+b.dataset.id+'/'+b.dataset.act,'POST'); }
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
  const body=addMsg('assistant','').querySelector('.body'); let acc='';
  try{
    const r=await fetch('/v1/chat/completions',{method:'POST',headers:Object.assign({'Content-Type':'application/json'},authHeaders()),
      body:JSON.stringify({model:model,messages:[{role:'user',content:text}],stream:true})});
    if(!r.ok){ body.textContent='error: HTTP '+r.status; return; }
    const reader=r.body.getReader(), dec=new TextDecoder(); let buf='';
    while(true){
      const {done,value}=await reader.read(); if(done) break;
      buf+=dec.decode(value,{stream:true}); let i;
      while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim(); buf=buf.slice(i+1);
        if(!line.startsWith('data:')) continue;
        const p=line.slice(5).trim(); if(p==='[DONE]') continue;
        try{ const o=JSON.parse(p); const dc=o.choices&&o.choices[0]&&o.choices[0].delta&&o.choices[0].delta.content;
          if(dc){ acc+=dc; body.textContent=acc; scrollMsgs(); } }catch(e){}
      }
    }
    if(!acc) body.textContent='(empty response)';
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
    $('#keyState').textContent=s.api_key?'set':'unset';
    const order=['backend','model_dir','host','port','max_concurrent_requests','idle_timeout','max_process_memory','ttl_check_interval','api_key'];
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
$('#saveIdle').onclick=saveIdle;
$('#applyKey').onclick=applyKey;

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
async function refreshMetrics(){
  try{ const d=await api('/api/metrics'); const s=d.samples||[];
    const lat=s.map(p=>p.latency_ms), tps=s.map(p=>p.tps);
    const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
    $('#metricCards').innerHTML=
      '<div class="card"><div class="k">Requests</div><div class="v">'+s.length+'</div></div>'+
      '<div class="card"><div class="k">Avg latency</div><div class="v">'+avg(lat).toFixed(0)+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">Avg throughput</div><div class="v">'+avg(tps).toFixed(1)+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">Last latency</div><div class="v">'+(s.length?Math.round(s[s.length-1].latency_ms):'—')+'<small> ms</small></div></div>';
    const cs=getComputedStyle(document.documentElement);
    const cBlue=(cs.getPropertyValue('--blue')||'#58a6ff').trim(), cGreen=(cs.getPropertyValue('--accent')||'#22c55e').trim();
    drawChart('chartLatency', lat, cBlue, 'ms');
    drawChart('chartTps', tps, cGreen, 'tok/s');
  }catch(e){}
}

/* poll */
$('#refreshBtn').onclick=()=>tick();
async function tick(){
  try{ const s=await api('/api/status'); setHealth(true); if(active==='models'){ renderModels(s); $('#models-err').textContent=''; } }
  catch(e){ setHealth(false); if(active==='models') $('#models-err').textContent=String(e); }
  if(active==='logs') refreshLogs();
  if(active==='metrics') refreshMetrics();
}
setInterval(tick,2000); tick();
</script>
</body>
</html>
"""
