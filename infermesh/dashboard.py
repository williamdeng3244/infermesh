# SPDX-License-Identifier: Apache-2.0
"""Self-contained admin dashboard (single HTML page, no build step, no CDN, no deps).

Served by the gateway at ``GET /`` and ``GET /admin``. Four sections via a left
sidebar — Models, Chat, Logs, Metrics, Devices, Benchmark, Settings — driven by the public HTTP API
(``/api/status``, ``/api/logs``, ``/api/settings``, ``/v1/*``). "Instrument
bench" theme from ``docs/design/console-redesign-v2.html``: graphite-blue
ground, signal-amber accent, categorical chip palette, tabular numerics.
System font stacks only, renders offline.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>infermesh · admin</title>
<style>
/* ============ instrument-bench theme (docs/design/console-redesign-v2.html) ============
   Graphite-blue ground, signal-amber accent, categorical chip palette --c1..--c5,
   datasheet numerics (mono + tabular-nums). Legacy names below alias into v2 tokens. */
:root{
  --bg:#0C1117; --bg2:#0E141B; --panel:#121A23; --panel2:#0F161E; --inset:#0A0F14;
  --line:#1D2833; --line2:#2C3A4A; --linesoft:rgba(140,160,180,.10);
  --text:#E7EDF4; --mut:#8DA0B3; --dim:#5D7183;
  --sig:#FFB224; --sig-soft:rgba(255,178,36,.14); --sig-ink:#221500;
  --ok:#3FB950; --warn:#D29922; --err:#F85149; --info:#58A6FF;
  --c1:#FFB224; --c2:#38BDF8; --c3:#A78BFA; --c4:#F472B6; --c5:#9AA8B6;
  --r:10px; --sb:240px; --dot:rgba(141,160,179,.16);
  --mono:ui-monospace,"SFMono-Regular","Cascadia Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --sans:-apple-system,"Segoe UI",system-ui,Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --shadow:0 1px 0 rgba(0,0,0,.25), 0 8px 24px -18px rgba(0,0,0,.6);
  /* legacy aliases — pre-redesign rules reference these names */
  --surface:var(--bg2); --card:var(--panel); --card2:var(--panel2); --mutedbg:var(--inset);
  --border:var(--line); --border2:var(--line2); --muted:var(--mut);
  --accent:var(--sig); --accent2:var(--sig); --blue:var(--info); --danger:var(--err);
  --radius:var(--r);
}
:root[data-theme="light"]{
  --bg:#F2F4F7; --bg2:#ECEFF3; --panel:#FFFFFF; --panel2:#F7F9FB; --inset:#EDF0F4;
  --line:#DFE5EC; --line2:#C6D0DB; --linesoft:rgba(40,60,80,.08);
  --text:#1B2430; --mut:#54677A; --dim:#8C9BAB;
  --sig:#B36D00; --sig-soft:rgba(179,109,0,.12); --sig-ink:#FFFFFF;
  --ok:#1A7F37; --warn:#9A6700; --err:#CF222E; --info:#0969DA;
  --c1:#C77800; --c2:#0284C7; --c3:#7C3AED; --c4:#DB2777; --c5:#64748B;
  --dot:rgba(60,80,100,.14);
  --shadow:0 1px 2px rgba(16,24,40,.06), 0 8px 24px -18px rgba(16,24,40,.25);
}
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
.topbar{display:flex;align-items:center;gap:12px;padding:13px 24px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--bg) 78%,transparent);backdrop-filter:blur(8px);position:sticky;top:0;z-index:5}
.topbar h2{margin:0;font-size:16px;font-weight:600}
.spacer{flex:1}
.pill{font:500 12px var(--sans);padding:3px 10px;border-radius:999px;border:1px solid var(--border2);color:var(--muted);display:inline-flex;align-items:center;gap:7px}
.seg{display:inline-flex;border:1px solid var(--border2);border-radius:8px;overflow:hidden}
.seg-btn{background:transparent;border:0;color:var(--muted);padding:5px 15px;cursor:pointer;font:500 13px var(--sans);transition:background .15s ease,color .15s ease,transform .08s ease}
.seg-btn:hover:not(.active){background:var(--mutedbg);color:var(--text)}
.seg-btn:active{transform:scale(.95)}
.seg-btn.active{background:var(--sig);color:var(--sig-ink);font-weight:650}
.prefill{color:var(--dim);font-style:italic}
.msg-meta{font-size:11px;color:var(--dim);margin-top:4px}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--dim)}
.pill.ok{color:var(--ok);border-color:rgba(63,185,80,.4)}.pill.ok .dot{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.pill.bad{color:var(--err);border-color:rgba(248,81,73,.4)}.pill.bad .dot{background:var(--err)}
.content{padding:24px;overflow:auto}
.section{display:none}
.section.active{display:block;animation:fade .2s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
input,select,textarea{font:14px var(--sans);background:var(--card2);border:1px solid var(--border2);color:var(--text);border-radius:8px;padding:8px 11px;outline:none}
input:focus,select:focus,textarea:focus,button:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
.btn{font:500 12.5px var(--sans);padding:6px 12px;border-radius:7px;border:1px solid var(--border2);background:var(--card2);color:var(--text);cursor:pointer;transition:transform .08s ease,border-color .15s ease,background .15s ease,box-shadow .15s ease}
.btn:hover:not(:disabled){border-color:var(--blue);background:var(--mutedbg)}
.btn:active:not(:disabled){transform:translateY(1px) scale(.98)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn.primary:active:not(:disabled){transform:translateY(1px) scale(.98)}
.btn:disabled{opacity:.35;cursor:default}
.btn.primary{background:var(--sig);border-color:var(--sig);color:var(--sig-ink);font-weight:650}
.btn.primary:hover{background:var(--sig);filter:brightness(1.06)}
.btn.sm{padding:4px 9px;font-size:11.5px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}
.card .k{color:var(--muted);font:500 11px var(--sans);text-transform:uppercase;letter-spacing:.7px}
.card .v{font:600 26px/1.1 var(--mono);font-variant-numeric:tabular-nums;margin-top:8px}
.card .v small{font-size:14px;color:var(--muted);font-weight:500}
.bar{height:6px;background:var(--mutedbg);border-radius:3px;margin-top:12px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--sig);transition:width .5s ease}
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
.badge.warn{color:var(--warn);border-color:var(--warn)}
.chip{display:inline-block;font:600 10.5px var(--mono);padding:2px 8px;border-radius:999px;border:1px solid var(--border2);color:var(--muted);vertical-align:middle;letter-spacing:.3px}
.chip.gpu{color:var(--blue);border-color:rgba(88,166,255,.55);background:rgba(88,166,255,.10)}
.chip.cpu{color:var(--dim)}
.bm-ctl{display:flex;flex-wrap:wrap;align-items:flex-end;gap:14px}
.bm-field{display:flex;flex-direction:column;gap:5px}
.bm-field label{font:600 10px var(--sans);text-transform:uppercase;letter-spacing:.6px;color:var(--dim)}
.bm-field input[type=number]{width:92px}
.bm-actions{display:flex;gap:8px;align-items:center}
.mref{margin-top:18px;border:1px solid var(--border);border-radius:var(--radius);background:var(--card);padding:4px 14px 14px}
.mref>summary{cursor:pointer;font:600 13px var(--sans);padding:10px 0;list-style:none}
.mref>summary::-webkit-details-marker{display:none}
.mref>summary::before{content:"▸ ";color:var(--muted)}
.mref[open]>summary::before{content:"▾ "}
.mref-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:6px}
.mref-item{border:1px solid var(--border);border-radius:8px;padding:11px 13px;background:var(--card2)}
.mref-h{font-size:13px;margin-bottom:6px}.mref-h .muted{font-size:11px;font-weight:500}
/* ---- v2 analysis/compare — instrument-bench plot components ---- */
.plotwrap{background:var(--panel2);border:1px solid var(--line);border-radius:var(--r);padding:6px 4px 2px;background-image:radial-gradient(var(--dot) 1px,transparent 1.4px);background-size:22px 22px;background-position:11px 9px}
.plotwrap svg{display:block;width:100%;height:auto}
.axis{font:500 10.5px var(--mono);fill:var(--dim)}
.tooltip{position:fixed;z-index:99;pointer-events:none;background:var(--panel);border:1px solid var(--line2);border-radius:8px;padding:9px 11px;font:11.5px/1.5 var(--mono);color:var(--text);box-shadow:0 12px 30px -12px rgba(0,0,0,.7);opacity:0;transform:translateY(3px);transition:opacity .1s,transform .1s;max-width:280px}
.tooltip.show{opacity:1;transform:none}
.fchip{display:inline-flex;align-items:center;gap:7px;padding:5px 12px;border-radius:999px;border:1px solid var(--line2);background:var(--panel2);color:var(--muted);font:500 12px var(--sans);cursor:pointer}
.fchip.on{color:var(--text);background:var(--panel)}
.fchip .sw,.antag .sw{width:9px;height:9px;border-radius:3px;display:inline-block}
.antag{font:600 11.5px var(--mono);letter-spacing:.2px;display:inline-flex;align-items:center;gap:6px}
.hint{font-size:11.5px;color:var(--dim);margin-top:8px;line-height:1.6}
.eyebrow{color:var(--muted);font:600 10.5px var(--sans);text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px}
.kpi .ro{font:600 24px/1.15 var(--mono);font-variant-numeric:tabular-nums;margin-top:6px}
.kpi .ro small{font-size:12px;color:var(--muted);font-weight:500;margin-left:4px}
.angrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:14px}
.angrid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:14px;margin-bottom:14px}
.anrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
.mref-en{font-size:12px;color:var(--muted);line-height:1.5}
.mref-zh{font-size:12px;color:var(--dim);line-height:1.6;margin-top:4px}
.bm-term{margin-top:14px}
.bm-term>summary{cursor:pointer;font:600 12px var(--sans);color:var(--text);padding:7px 13px;list-style:none;border:1px solid var(--border2);border-radius:7px;background:var(--card2);display:inline-block;transition:border-color .15s ease,background .15s ease}
.bm-term>summary:hover{border-color:var(--blue);background:var(--mutedbg)}
.bm-term>summary::-webkit-details-marker{display:none}
.bm-term>summary::before{content:"▸ "}.bm-term[open]>summary::before{content:"▾ "}
.term-top{margin:11px 0 2px}
.bm-raw{margin-top:6px}
.bm-raw>summary{cursor:pointer;font:600 10px var(--mono);color:var(--dim);text-transform:uppercase;letter-spacing:.5px;list-style:none;padding:4px 0}
.bm-raw>summary::-webkit-details-marker{display:none}
.bm-raw>summary::before{content:"▸ "}.bm-raw[open]>summary::before{content:"▾ "}
.term-h{font:600 10px var(--mono);color:var(--dim);text-transform:uppercase;letter-spacing:.5px;margin:8px 0 3px}
pre.term{background:#0a0e1a;color:#c9d4e3;border:1px solid var(--border);border-radius:7px;padding:11px 13px;font:11.5px/1.5 var(--mono);overflow:auto;white-space:pre;max-height:340px;margin:0}
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
.msg.user{align-self:flex-end;background:var(--sig);color:var(--sig-ink);border-bottom-right-radius:4px}
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
.bm-exp{padding:3px 10px;line-height:1;font-size:13px}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--border2);padding:10px 18px;border-radius:9px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:50}
.toast.show{opacity:1}
/* ---- Explorer (box-plot compare) + Community library ---- */
.ex-build{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-top:13px;padding-top:13px;border-top:1px solid var(--border)}
.ex-series{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}
.ex-cards{display:flex;flex-direction:column;gap:9px;margin-top:13px}
.ex-card{display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px;background:rgba(127,127,127,.05);border:1px solid var(--border2);border-radius:9px;padding:10px 12px}
.ex-dot{width:12px;height:12px;border-radius:3px;flex:none;margin-bottom:7px}
.ex-cardx{background:none;border:none;color:var(--dim);cursor:pointer;font-size:19px;line-height:1;padding:0 4px;margin-bottom:2px}
.ex-cardx:hover{color:#ef4444}
.ex-schip{display:inline-flex;align-items:center;gap:7px;background:rgba(127,127,127,.08);border:1px solid var(--border2);border-radius:20px;padding:4px 6px 4px 11px;font-size:12px}
.ex-schip i{width:10px;height:10px;border-radius:3px;flex:none}
.ex-schip button{background:none;border:none;color:var(--dim);cursor:pointer;font-size:15px;line-height:1;padding:0 3px}
.ex-schip button:hover{color:#ef4444}
.ex-check{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--dim);cursor:pointer;user-select:none}
.ex-check input{cursor:pointer}
#exLegend{display:flex;flex-wrap:wrap;gap:4px 16px;margin-bottom:10px;min-height:16px}
.ex-leg{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text)}
.ex-leg i{width:11px;height:11px;border-radius:3px;display:inline-block;flex:none}
#exChart{display:block;width:100%}
.ex-grid{stroke:var(--border);stroke-width:1}
.ex-axis{stroke:var(--border2);stroke-width:1}
.ex-yl{fill:var(--dim);font:11px ui-monospace,monospace;text-anchor:end}
.ex-xl{fill:var(--dim);font:11px ui-monospace,monospace;text-anchor:middle}
.ex-mlabel{fill:var(--dim);font:11px ui-sans-serif,system-ui}
.cm-filters{display:flex;flex-wrap:wrap;gap:9px;align-items:center}
.cm-filters select,.cm-filters input{font-size:12.5px}
tr.cm-det>td{background:rgba(127,127,127,.04);padding:0}
.cm-detwrap{padding:14px 16px;display:grid;grid-template-columns:1fr 1fr;gap:10px 28px}
.ex-vgrid{stroke:var(--border);stroke-width:1;opacity:.35}
.ex-axt{fill:var(--dim);font:12px ui-sans-serif,system-ui;text-anchor:middle;font-weight:500}
.ex-box{cursor:pointer}
.ex-tip{position:fixed;z-index:60;display:none;background:var(--card);border:1px solid var(--border2);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 6px 22px rgba(0,0,0,.3);pointer-events:none;min-width:158px}
.ex-tip-h{display:flex;align-items:center;gap:6px;font-weight:600;margin-bottom:5px}
.ex-tip-h i{width:9px;height:9px;border-radius:2px;flex:none}
.ex-tip-row{display:flex;justify-content:space-between;gap:18px;line-height:1.6;color:var(--dim)}
.ex-tip-row b{color:var(--text);font-variant-numeric:tabular-nums;font-weight:600}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand"><span class="mark"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="M12 7l4.5 2.5v5L12 17l-4.5-2.5v-5z" opacity=".55"/></svg></span> infermesh</div>
    <nav class="nav" id="nav" aria-label="Sections">
      <button data-sec="models" class="active" aria-label="Models"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3"/></svg> <span data-i18n="Models">Models</span></button>
      <button data-sec="chat" aria-label="Chat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> <span data-i18n="Chat">Chat</span></button>
      <button data-sec="logs" aria-label="Logs"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg> <span data-i18n="Logs">Logs</span></button>
      <button data-sec="metrics" aria-label="Metrics"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg> <span data-i18n="Metrics">Metrics</span></button>
      <button data-sec="devices" aria-label="Devices"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="5" rx="1"/><rect x="2" y="13" width="20" height="5" rx="1"/><line x1="6" y1="8.5" x2="6.01" y2="8.5"/><line x1="6" y1="15.5" x2="6.01" y2="15.5"/></svg> <span data-i18n="Devices">Devices</span></button>
      <button data-sec="download" aria-label="Download"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg> <span data-i18n="Download">Download</span></button>
      <button data-sec="benchmark" aria-label="Benchmark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 19a9 9 0 1 1 15 0"/><path d="M12 14l3.5-3.5"/></svg> <span data-i18n="Benchmark">Benchmark</span></button>
      <button data-sec="explorer" aria-label="Explorer"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="20" x2="3" y2="11"/><line x1="9" y1="20" x2="9" y2="4"/><line x1="15" y1="20" x2="15" y2="13"/><line x1="21" y1="20" x2="21" y2="7"/></svg> <span data-i18n="Explorer">Explorer</span></button>
      <button data-sec="analysis" aria-label="Hardware Analysis"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M3 21V6m0 15L10 8l4 6 7-11"/><path d="M3 6h8M14 21V10" opacity=".4"/></svg> <span data-i18n="Hardware Analysis">Hardware Analysis</span></button>
      <button data-sec="compare" aria-label="Compare A/B"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v16M15 4v16M4 9l3 3-3 3M20 9l-3 3 3 3"/></svg> <span data-i18n="Compare A/B">Compare A/B</span></button>
      <button data-sec="community" aria-label="Community"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> <span data-i18n="Community">Community</span></button>
      <button data-sec="settings" aria-label="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg> <span data-i18n="Settings">Settings</span></button>
      <button data-sec="guide" aria-label="Guide"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> <span data-i18n="Guide">Guide</span></button>
    </nav>
    <div class="sb-foot">
      <span id="sb-health" class="pill"><span class="dot"></span> connecting</span>
      <span id="sb-ver">v__INFERMESH_VERSION__ · mock / vllm / openai / transformers</span>
    </div>
  </aside>

  <div class="main">
    <div class="topbar">
      <h2 id="title" data-i18n="Models">Models</h2>
      <span class="spacer"></span>
      <button class="btn sm" id="langBtn" title="语言 / Language" aria-label="Language">中</button>
      <button class="btn sm" id="themeBtn" aria-label="Toggle light/dark theme" data-i18n-title="Toggle theme" title="Toggle theme"></button>
      <input id="apikey" placeholder="API key (if enabled)" data-i18n-ph="API key (if enabled)" size="20" autocomplete="off" aria-label="API key"/>
      <button class="btn sm" id="refreshBtn"><span aria-hidden="true">&#8635;</span> <span data-i18n="Refresh">Refresh</span></button>
    </div>
    <div class="content">

      <section class="section active" id="sec-models">
        <div class="cards" id="cards"></div>
        <div class="chat-bar" style="margin-bottom:12px">
          <label class="muted" style="font-size:12px" data-i18n="Load on device">Load on device</label>
          <select id="devSel" style="min-width:220px"><option value="">auto</option></select>
          <span class="muted" style="font-size:11px" data-i18n="applies to the next Load (Transformers backend)">applies to the next Load (Transformers backend)</span>
        </div>
        <div class="panel">
          <table>
            <thead><tr><th data-i18n="Model">Model</th><th data-i18n="Type">Type</th><th data-i18n="Backend">Backend</th><th data-i18n="Status">Status</th><th data-i18n="Mem MB">Mem MB</th><th data-i18n="Gen tps">Gen tps</th><th data-i18n="Leases">Leases</th><th data-i18n="Actions">Actions</th></tr></thead>
            <tbody id="rows"><tr><td colspan="8" class="muted" data-i18n="loading…">loading&hellip;</td></tr></tbody>
          </table>
        </div>
        <div class="panel" style="margin-top:16px;padding:14px 16px">
          <div class="chat-bar" style="margin-bottom:10px">
            <label class="muted" style="font-size:12px" data-i18n="Per-model overrides">Per-model overrides</label>
            <select id="msModel" style="min-width:200px"></select>
            <span id="msHas"></span>
            <span class="spacer"></span>
            <span class="muted" style="font-size:11px" data-i18n="override the global generation defaults for one model">override the global generation defaults for one model</span>
          </div>
          <div class="bm-ctl">
            <div class="bm-field"><label>temperature</label><input id="msTemp" type="number" min="0" max="2" step="0.05" placeholder="default"/></div>
            <div class="bm-field"><label>top_p</label><input id="msTopP" type="number" min="0" max="1" step="0.05" placeholder="default"/></div>
            <div class="bm-field"><label>top_k</label><input id="msTopK" type="number" min="0" step="1" placeholder="default"/></div>
            <div class="bm-field"><label>max_tokens</label><input id="msMax" type="number" min="1" step="1" placeholder="default"/></div>
            <div class="bm-field"><label data-i18n="max ctx (approx)">max ctx (approx)</label><input id="msCtx" type="number" min="1" step="1" placeholder="off" title="approx, by characters"/></div>
            <span class="spacer"></span>
            <div class="bm-actions">
              <button class="btn" id="msSave" data-i18n="Save">Save</button>
              <button class="btn sm" id="msClear" data-i18n="Clear">Clear</button>
            </div>
          </div>
          <div class="muted" style="font-size:11px;margin-top:8px" data-i18n="Per-model values win over the global defaults; a request's own value still wins. max_context_window rejects over-long prompts (approximate).">Per-model values win over the global defaults; a request's own value still wins. max_context_window rejects over-long prompts (approximate).</div>
        </div>
        <p id="models-err" class="err"></p>
      </section>

      <section class="section" id="sec-chat">
        <div class="chat-wrap">
          <div class="chat-bar">
            <label class="muted" style="font-size:12px" data-i18n="Model">Model</label>
            <select id="chatModel" style="min-width:190px"></select>
            <span class="spacer"></span>
            <button class="btn sm" id="chatClear" data-i18n="Clear">Clear</button>
          </div>
          <div class="msgs" id="msgs"></div>
          <div class="composer">
            <textarea id="chatInput" placeholder="Message the model&hellip;  (Enter to send, Shift+Enter for newline)" data-i18n-ph="Message the model…  (Enter to send, Shift+Enter for newline)" aria-label="Chat message"></textarea>
            <button class="btn primary" id="sendBtn" data-i18n="Send">Send</button>
          </div>
        </div>
      </section>

      <section class="section" id="sec-logs">
        <div class="chat-bar" style="margin-bottom:8px;flex-wrap:wrap;gap:12px">
          <span class="muted" style="font-size:12px" data-i18n="Live tail of infermesh logs (pool · server · backends)">Live tail of infermesh logs (pool · server · backends)</span>
          <span class="spacer"></span>
          <label class="muted" style="font-size:12px" data-i18n="Lines:">Lines:</label>
          <select id="logLines"><option>200</option><option selected>300</option><option>500</option><option>1000</option><option>2000</option></select>
          <label class="muted" style="font-size:12px" data-i18n="Min display level">Min display level</label>
          <select id="logLevel" title="filters the view only — not the saved log file" data-i18n-title="filters the view only — not the saved log file"><option value="" data-i18n="All">All</option><option value="debug">DEBUG</option><option value="info">INFO</option><option value="warning">WARNING</option><option value="error">ERROR</option></select>
          <label class="muted" style="font-size:12px"><input type="checkbox" id="logsPause"/> <span data-i18n="pause">pause</span></label>
          <button class="btn sm" id="logRefresh" data-i18n="Refresh">Refresh</button>
        </div>
        <div class="muted" id="logShowing" style="font-size:11px;margin-bottom:6px"></div>
        <div class="logs" id="logs"><div class="muted" data-i18n="loading…">loading&hellip;</div></div>
      </section>

      <section class="section" id="sec-metrics">
        <div class="panel" style="padding:14px 16px;margin-bottom:14px">
          <div class="chat-bar">
            <div class="seg"><button id="stScopeSession" class="seg-btn active" data-i18n="Session">Session</button><button id="stScopeAll" class="seg-btn" data-i18n="All-Time">All-Time</button></div>
            <select id="stModel" style="min-width:160px"><option value="" data-i18n="All models">All models</option></select>
            <span class="muted" style="font-size:11px" data-i18n="aggregate request stats — All-Time survives restarts">aggregate request stats &mdash; All-Time survives restarts</span>
            <span class="spacer"></span>
            <button class="btn sm" id="stCopy" data-i18n="Copy">Copy</button>
            <button class="btn sm" id="stExport" data-i18n="Export CSV">Export CSV</button>
            <button class="btn sm" id="stClear" data-i18n="Clear">Clear</button>
          </div>
        </div>
        <div class="cards" id="liveBar" style="margin-bottom:14px"></div>
        <div class="seg" id="mtTabs" style="margin-bottom:14px">
          <button class="seg-btn active" data-mt="overview" data-i18n="Overview">Overview</button>
          <button class="seg-btn" data-mt="permodel" data-i18n="Per-model">Per-model</button>
          <button class="seg-btn" data-mt="charts" data-i18n="Charts">Charts</button>
          <button class="seg-btn" data-mt="rejections" data-i18n="Rejections">Rejections</button>
        </div>
        <div class="mt-panel" id="mt-overview">
          <div class="cards" id="statCards"></div>
          <div class="stat-viz">
            <div class="card">
              <div class="k" data-i18n="Token composition">Token composition</div>
              <div class="stack" id="tokBar"></div>
              <div class="legend" id="tokLeg"></div>
            </div>
            <div class="card">
              <div class="k" data-i18n="Cache efficiency">Cache efficiency</div>
              <div class="v" id="cacheV">&mdash;<small> %</small></div>
              <div class="bar"><i id="cacheBar" style="width:0%"></i></div>
              <div class="muted" id="cacheSub" style="font-size:11px;margin-top:10px">&mdash;</div>
            </div>
          </div>
        </div>
        <div class="mt-panel" id="mt-permodel" style="display:none">
          <div class="panel">
            <table>
              <thead><tr><th data-sort="model" data-i18n="Model">Model</th><th data-sort="total_requests" data-i18n="Requests">Requests</th><th data-sort="generation_tps" data-i18n="Gen tok/s">Gen tok/s</th><th data-sort="total_tokens_served" data-i18n="Tokens">Tokens</th><th data-sort="cache_efficiency" data-i18n="Cache %">Cache %</th></tr></thead>
              <tbody id="pmRows"><tr><td colspan="5" class="muted" data-i18n="no per-model data yet">no per-model data yet</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="mt-panel" id="mt-charts" style="display:none">
          <div class="seg" id="chRange" style="margin-bottom:14px">
            <button class="seg-btn" data-r="300">5m</button>
            <button class="seg-btn" data-r="3600">1h</button>
            <button class="seg-btn active" data-r="0" data-i18n="All">All</button>
          </div>
          <div class="cards" id="metricCards"></div>
          <div class="panel" style="padding:18px;margin-bottom:16px">
            <div class="muted" style="font-size:12px;margin-bottom:10px" data-i18n="Latency per request (ms)">Latency per request (ms)</div>
            <canvas id="chartLatency" style="width:100%;display:block"></canvas>
          </div>
          <div class="panel" style="padding:18px">
            <div class="muted" style="font-size:12px;margin-bottom:10px" data-i18n="Throughput per request (tokens/s)">Throughput per request (tokens/s)</div>
            <canvas id="chartTps" style="width:100%;display:block"></canvas>
          </div>
          <p class="muted" style="font-size:12px;margin-top:12px" data-i18n="History records one point per chat completion — use the Chat tab (or send API requests) to generate data.">History records one point per chat completion — use the <strong>Chat</strong> tab (or send API requests) to generate data.</p>
        </div>
        <div class="mt-panel" id="mt-rejections" style="display:none">
          <div class="panel" style="padding:16px">
            <div class="muted" style="font-size:12px;margin-bottom:10px" data-i18n="Requests rejected before serving, by reason">Requests rejected before serving, by reason</div>
            <div id="statRej" class="muted" style="font-size:13px" data-i18n="none">none</div>
          </div>
        </div>
      </section>

      <section class="section" id="sec-devices">
        <div class="chat-bar" style="margin-bottom:12px">
          <span class="muted" style="font-size:12px" data-i18n="Detected compute devices — pick one per model on the Models tab">Detected compute devices &mdash; pick one per model on the Models tab</span>
          <span class="spacer"></span>
          <button class="btn sm" id="devRefresh"><span aria-hidden="true">&#8635;</span> <span data-i18n="Refresh">Refresh</span></button>
        </div>
        <div class="panel">
          <table>
            <thead><tr><th data-i18n="Device">Device</th><th data-i18n="Vendor">Vendor</th><th data-i18n="Name">Name</th><th data-i18n="VRAM used">VRAM used</th><th data-i18n="VRAM free">VRAM free</th><th data-i18n="VRAM total">VRAM total</th></tr></thead>
            <tbody id="devRows"><tr><td colspan="6" class="muted" data-i18n="loading…">loading&hellip;</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="section" id="sec-download">
        <div class="chat-bar" style="margin-bottom:12px">
          <input id="dlSearch" placeholder="Search HuggingFace models (e.g. Qwen2.5-0.5B-Instruct)" data-i18n-ph="Search HuggingFace models (e.g. Qwen2.5-0.5B-Instruct)" style="flex:1;min-width:240px"/>
          <select id="dlTask" title="Filter by task" data-i18n-title="Filter by task">
            <option value="" data-i18n="Any task">Any task</option>
            <option value="text-generation" data-i18n="Text generation">Text generation</option>
            <option value="image-text-to-text" data-i18n="Vision (VLM)">Vision (VLM)</option>
            <option value="feature-extraction" data-i18n="Embedding">Embedding</option>
          </select>
          <select id="dlSort" title="Sort by" data-i18n-title="Sort by">
            <option value="downloads" data-i18n="Most downloads">Most downloads</option>
            <option value="trending_score" data-i18n="Trending">Trending</option>
            <option value="likes" data-i18n="Most likes">Most likes</option>
            <option value="lastModified" data-i18n="Recently updated">Recently updated</option>
          </select>
          <button class="btn primary" id="dlBtn" data-i18n="Search">Search</button>
        </div>
        <p class="muted" style="font-size:12px;margin:0 0 10px" data-i18n="Downloads land in the server's --model-dir and appear under Models when finished.">Downloads land in the server's <code>--model-dir</code> and appear under Models when finished.</p>
        <div class="panel" style="margin-bottom:16px">
          <table>
            <thead><tr><th data-i18n="Model">Model</th><th data-i18n="Task">Task</th><th data-i18n="Downloads">Downloads</th><th data-i18n="Likes">Likes</th><th></th></tr></thead>
            <tbody id="dlResults"><tr><td colspan="5" class="muted" data-i18n="popular models load here…">popular models load here&hellip;</td></tr></tbody>
          </table>
        </div>
        <div class="chat-bar" style="margin-bottom:10px">
          <span class="muted" style="font-size:12px" data-i18n="ModelScope (by model ID)">ModelScope (by model ID)</span>
          <input id="msdlId" placeholder="e.g. Qwen/Qwen2.5-0.5B-Instruct" style="flex:1;min-width:200px"/>
          <button class="btn" id="msdlBtn" data-i18n="Download">Download</button>
        </div>
        <div class="chat-bar" style="margin-bottom:8px"><span class="muted" style="font-size:12px" data-i18n="Download jobs">Download jobs</span></div>
        <div class="panel">
          <table>
            <thead><tr><th data-i18n="Repo">Repo</th><th data-i18n="Status">Status</th><th data-i18n="Progress">Progress</th><th data-i18n="Size">Size</th><th data-i18n="Actions">Actions</th></tr></thead>
            <tbody id="dlJobs"><tr><td colspan="5" class="muted" data-i18n="no downloads yet">no downloads yet</td></tr></tbody>
          </table>
        </div>
        <p id="dl-err" class="err"></p>
      </section>

      <section class="section" id="sec-benchmark">
        <div class="panel" style="padding:15px 16px;margin-bottom:16px">
          <div class="bm-ctl">
            <div class="bm-field"><label data-i18n="Model">Model</label><select id="bmModel" style="min-width:200px"></select></div>
            <div class="bm-field"><label data-i18n="Device">Device</label><select id="bmDevice" style="min-width:190px"></select></div>
            <div class="bm-field"><label data-i18n="Requests">Requests</label><input id="bmReq" type="number" min="1" max="200" value="20"/></div>
            <div class="bm-field"><label data-i18n="Concurrency">Concurrency</label><input id="bmConc" type="number" min="1" max="32" value="4"/></div>
            <div class="bm-field"><label data-i18n="Max tokens">Max tokens</label><input id="bmTok" type="number" min="1" max="1024" value="64"/></div>
            <div class="bm-field"><label data-i18n="Mode">Mode</label><select id="bmMode"><option value="same" data-i18n="same prompt">same prompt</option><option value="different" data-i18n="different">different</option></select></div>
            <span class="spacer"></span>
            <div class="bm-actions">
              <button class="btn primary" id="bmRun" data-i18n="Run benchmark">Run benchmark</button>
              <button class="btn sm" id="bmSingle" data-i18n="Single request">Single request</button>
              <button class="btn sm" id="bmCopy" data-i18n="Copy">Copy</button>
              <label class="ex-check" style="margin-left:4px" title="auto-publish this run to the shared library"><input type="checkbox" id="bmShare" checked/> <span data-i18n="Share to library">Share to library</span></label>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:12px;margin-top:11px;min-height:16px">
            <div id="bmStatus" class="muted" style="font-size:12px"></div>
            <div class="bar" id="bmProg" style="display:none;flex:1;max-width:360px;margin-top:0"><i id="bmProgBar" style="width:0%"></i></div>
            <span id="bmProgTxt" class="muted" style="display:none;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap"></span>
            <button class="btn sm" id="bmCancel" style="display:none" data-i18n="Cancel">Cancel</button>
          </div>
        </div>
        <div class="cards" id="bmCards"></div>
        <div class="panel" id="bmDetail" style="display:none;padding:18px">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px">
            <div><div class="muted" style="font-size:12px;margin-bottom:8px" data-i18n="Latency / E2E (ms)">Latency / E2E (ms)</div><dl class="kv" id="bmLatency"></dl></div>
            <div><div class="muted" style="font-size:12px;margin-bottom:8px" data-i18n="Time to first token (ms)">Time to first token (ms)</div><dl class="kv" id="bmTtft"></dl></div>
            <div><div class="muted" style="font-size:12px;margin-bottom:8px" data-i18n="Time per output token (ms)">Time per output token (ms)</div><dl class="kv" id="bmTpot"></dl></div>
          </div>
          <div class="muted" style="font-size:12px;margin:18px 0 8px" data-i18n="Latency percentiles">Latency percentiles</div>
          <canvas id="bmChart" style="width:100%;display:block"></canvas>
        </div>
        <div class="panel" style="margin-top:16px">
          <div class="chat-bar" style="padding:12px 14px 0"><span class="muted" style="font-size:12px" data-i18n="Past runs — persisted across restarts">Past runs &mdash; persisted across restarts</span></div>
          <table>
            <thead><tr><th style="width:34px"></th><th data-i18n="When">When</th><th data-i18n="Model">Model</th><th data-i18n="Req×Conc">Req&times;Conc</th><th>req/s</th><th>tok/s</th><th>p50 ms</th><th>p99 ms</th></tr></thead>
            <tbody id="bmHist"><tr><td colspan="8" class="muted" data-i18n="no past runs">no past runs</td></tr></tbody>
          </table>
        </div>
        <details class="mref" open>
          <summary data-i18n="Metrics Reference">Metrics Reference</summary>
          <div class="mref-grid">
            <div class="mref-item"><div class="mref-h"><b>TTFT</b> <span class="muted">Time to First Token · 首令牌时间</span></div><div class="mref-en">Wait until the first output token appears — measures prefill (prompt-reading) speed; longer prompts raise it. Lower is better.</div><div class="mref-zh">从发起请求到产出第一个 token 的等待,衡量 prefill(读完整 prompt)速度;prompt 越长越高。越低越好。</div></div>
            <div class="mref-item"><div class="mref-h"><b>TPOT</b> <span class="muted">Time Per Output Token · 每输出令牌时间</span></div><div class="mref-en">Average gap between output tokens during decode. e.g. 20 ms/tok ≈ 50 tok/s. Lower is better.</div><div class="mref-zh">解码阶段相邻输出 token 的平均间隔。例:20ms/tok ≈ 50 tok/s。越低越好。</div></div>
            <div class="mref-item"><div class="mref-h"><b>tg TPS</b> <span class="muted">Token Generation · 解码吞吐</span></div><div class="mref-en">Output tokens per second during decode — the inverse of TPOT and the main "how fast it writes" metric. Higher is better.</div><div class="mref-zh">解码阶段每秒生成的 token 数,是 TPOT 的倒数,衡量"写得多快"。越高越好。</div></div>
            <div class="mref-item"><div class="mref-h"><b>pp TPS</b> <span class="muted">Prompt Processing · 预填充吞吐</span></div><div class="mref-en">Input tokens processed per second during prefill. Faster prefill → lower TTFT; matters most for long context. Higher is better.</div><div class="mref-zh">prefill 阶段每秒处理的输入 token;越快 TTFT 越低,长上下文尤其重要。越高越好。</div></div>
            <div class="mref-item"><div class="mref-h"><b>E2E Latency</b> <span class="muted">End-to-End · 端到端延迟</span></div><div class="mref-en">Total wall-clock from request to full response ≈ TTFT + TPOT × output tokens.</div><div class="mref-zh">从发请求到收到完整回复的总墙钟时间 ≈ TTFT + TPOT × 输出 token 数。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Total Throughput</b> <span class="muted">总吞吐</span></div><div class="mref-en">Combined input + output tokens per second across the run — overall system utilization.</div><div class="mref-zh">整个测试每秒处理的输入+输出 token 总数,反映系统整体利用率。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Batch Size</b> <span class="muted">Concurrency · 批大小/并发</span></div><div class="mref-en">Requests processed at once. Larger batches raise total throughput but add per-request latency; 2× batch ≠ 2× speed (bandwidth limits).</div><div class="mref-zh">同时处理的请求数(并发)。批越大总吞吐越高,但单请求延迟增加;2× 批 ≠ 2× 速度(受带宽限制)。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Peak GPU Mem</b> <span class="muted">峰值显存</span></div><div class="mref-en">Max accelerator memory used during the run — weights + KV cache + activations. Estimates the largest model your hardware can hold.</div><div class="mref-zh">运行中加速器占用的最大显存(权重+KV 缓存+中间激活),可估算硬件能装多大的模型。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Speedup</b> <span class="muted">加速比</span></div><div class="mref-en">Token-generation throughput vs the single-request baseline (1×). Above 1× means batching uses the accelerator more efficiently.</div><div class="mref-zh">相对单请求基线(1×)的生成吞吐倍数;>1× 表示批处理更高效地利用了加速器。</div></div>
          </div>
        </details>
        <p id="bm-err" class="err"></p>
      </section>

      <section class="section" id="sec-explorer">
        <div class="panel" style="padding:15px 16px;margin-bottom:16px">
          <div class="muted" style="font-size:12.5px;margin-bottom:4px" data-i18n="Visualize and compare model performance across context lengths — all data from the shared library.">Visualize and compare model performance across context lengths &mdash; all data from the shared library.</div>
          <div class="bm-ctl">
            <div class="bm-field"><label data-i18n="Metric">Metric</label>
              <select id="exMetric" style="min-width:160px">
                <option value="pp_tps">PP tok/s</option>
                <option value="tg_tps">TG tok/s</option>
                <option value="ttft_ms">TTFT (ms)</option>
                <option value="tpot_ms">TPOT (ms/tok)</option>
                <option value="peak_mem_gb">Peak Mem (GB)</option>
                <option value="e2e_latency_s">E2E (s)</option>
                <option value="total_throughput">Total tok/s</option>
              </select>
            </div>
            <label class="ex-check"><input type="checkbox" id="exPoints"/> <span data-i18n="show data points">show data points</span></label>
            <span class="spacer"></span>
            <div class="bm-actions">
              <button class="btn primary sm" id="exAdd" data-i18n="+ Add comparison">+ Add comparison</button>
              <button class="btn sm" id="exCopy" data-i18n="Copy">Copy</button>
              <button class="btn sm" id="exExport" data-i18n="Export CSV">Export CSV</button>
            </div>
          </div>
          <div id="exSeries" class="ex-cards"></div>
        </div>
        <div class="panel" style="padding:18px">
          <div id="exLegend"></div>
          <svg id="exChart" preserveAspectRatio="xMidYMid meet" role="img" aria-label="benchmark comparison chart"></svg>
          <div id="exTip" class="ex-tip"></div>
          <div id="exEmpty" class="muted" style="text-align:center;padding:48px 10px;font-size:13px" data-i18n="No data yet — run a benchmark (auto-published) or pick a comparison above.">No data yet &mdash; run a benchmark (auto-published) or pick a comparison above.</div>
        </div>
      </section>

      <section class="section" id="sec-analysis">
        <div id="anRoot"></div>
      </section>

      <section class="section" id="sec-compare">
        <div id="cpRoot"></div>
      </section>

      <section class="section" id="sec-guide">
        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <div class="eyebrow">infermesh</div>
          <div class="mref-en">A hardware-agnostic LLM inference bench — install it, point it at your accelerator and your models, measure, and pool the results with your team. Everything below is bilingual; commands are copy-paste ready.</div>
          <div class="mref-zh">硬件无关的大模型推理测量台 —— 安装、接上你的加速卡和模型、开始测量，并与团队共享结果。以下内容中英对照，命令可直接复制。</div>
        </div>

        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <h3 style="margin:0 0 8px" data-i18n="Install">Install</h3>
          <div class="mref-en">One-line install with pipx (isolated environment, on your PATH) — or plain pip. Python ≥ 3.11.</div>
          <div class="mref-zh">用 pipx 一行安装（独立环境、自动加入 PATH），或直接 pip。需要 Python ≥ 3.11。</div>
          <pre class="term">pipx install infermesh              # or: pip install infermesh
infermesh start --backend mock --model-dir ~/models
# dashboard opens automatically 浏览器自动打开 (--no-open to disable)
infermesh desktop-install           # Linux app-menu icon 应用菜单图标（双击即启动）
infermesh status · infermesh stop · infermesh restart</pre>
          <div class="mref-en">Optional extras — install only what your hardware needs: <b>infermesh[transformers]</b> local HuggingFace models on CUDA / CPU / Apple MPS · <b>infermesh[vllm]</b> production NVIDIA serving · <b>infermesh[downloader]</b> in-dashboard HuggingFace search &amp; download · <b>infermesh[modelscope]</b> ModelScope downloads.</div>
          <div class="mref-zh">可选附加依赖 —— 按硬件按需安装：<b>infermesh[transformers]</b> 本地 HuggingFace 模型（CUDA / CPU / Apple MPS）· <b>infermesh[vllm]</b> NVIDIA 生产级推理 · <b>infermesh[downloader]</b> 仪表盘内搜索下载 HuggingFace 模型 · <b>infermesh[modelscope]</b> ModelScope 下载源。</div>
          <pre class="term">pipx install 'infermesh[transformers,downloader]'    # pick your extras 按需选择</pre>
        </div>

        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <h3 style="margin:0 0 8px" data-i18n="System overview">System overview</h3>
          <div class="mref-en">One gateway speaks both OpenAI and Anthropic protocols. A multi-model pool loads, evicts and pins models (LRU + TTL) behind an admission gate, so benchmarks and live traffic share one concurrency budget instead of trampling each other. The control plane never imports a vendor SDK — compute lives in pluggable backends (mock / transformers / vLLM / hosted providers). Every benchmark lands in local history and, when sharing is on, in the team community library.</div>
          <div class="mref-zh">一个网关同时兼容 OpenAI 与 Anthropic 协议。多模型池负责加载/淘汰/固定（LRU + TTL），准入闸门让基准测试与线上流量共享同一并发预算、互不践踏。控制面永不 import 厂商 SDK —— 计算全部在可插拔后端里（mock / transformers / vLLM / 托管提供商）。每次基准测试写入本机历史，开启共享后同时进入团队社区库。</div>
          <div class="mref-grid" style="margin-top:10px">
            <div class="mref-item"><div class="mref-h"><b>Models · Chat · Logs</b></div><div class="mref-en">Load / pin / per-model overrides; talk to a loaded model; live log tail.</div><div class="mref-zh">加载/固定/按模型覆盖；与已加载模型对话；日志实时跟踪。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Devices · Download</b></div><div class="mref-en">Detected accelerators + a per-model GPU picker; HuggingFace / ModelScope downloads with progress.</div><div class="mref-zh">检测到的加速卡与按模型选卡；HuggingFace / ModelScope 带进度下载。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Benchmark · Metrics</b></div><div class="mref-en">Background benchmark jobs with live progress and cancel; request stats plus latency / throughput charts.</div><div class="mref-zh">后台基准任务（实时进度、可取消）；请求统计与延迟/吞吐图表。</div></div>
            <div class="mref-item"><div class="mref-h"><b>Explorer · Analysis · Compare · Community</b></div><div class="mref-en">Box-plot compare across context lengths; MBU / MFU, roofline and the throughput–latency frontier; baseline + N-column regression check; everyone's runs in one place.</div><div class="mref-zh">跨上下文长度的箱线图对比；MBU/MFU、roofline、吞吐–延迟前沿；基线+多列回归判定；全团队的测试记录。</div></div>
          </div>
        </div>

        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <h3 style="margin:0 0 8px" data-i18n="Connect a GPU">Connect a GPU</h3>
          <div class="mref-en"><b>NVIDIA.</b> 1) Check the driver — if <code>nvidia-smi</code> lists your card, you are ready. 2) Install a compute backend: <b>[transformers]</b> (flexible, CUDA/CPU) or <b>[vllm]</b> (fastest serving). 3) Start with that backend. The card shows up on the Devices tab; assign a model to it on the Models tab ("Load on device").</div>
          <div class="mref-zh"><b>NVIDIA。</b>1) 查驱动 —— <code>nvidia-smi</code> 能列出显卡即就绪。2) 安装计算后端：<b>[transformers]</b>（灵活，CUDA/CPU）或 <b>[vllm]</b>（推理最快）。3) 用该后端启动。显卡会出现在「设备」页；在「模型」页为模型指定设备（加载到设备）。</div>
          <pre class="term">nvidia-smi                                    # driver check 查驱动
pipx install 'infermesh[transformers]'        # or [vllm]
infermesh start --backend transformers --model-dir ~/models</pre>
          <div class="mref-en"><b>Enflame GCU.</b> Install the vendor torch_gcu build first, then use the transformers backend — a GCU-specific crash guard is built in. <b>CPU / Apple MPS.</b> No accelerator needed: transformers falls back to CPU (slow, fine for smoke tests); the mock backend needs nothing at all.</div>
          <div class="mref-zh"><b>燧原 GCU。</b>先安装厂商 torch_gcu 版本，再用 transformers 后端 —— 已内置 GCU 崩溃防护。<b>CPU / Apple MPS。</b>无需加速卡：transformers 自动回退 CPU（慢，冒烟测试够用）；mock 后端则什么都不需要。</div>
        </div>

        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <h3 style="margin:0 0 8px" data-i18n="Connect a model">Connect a model</h3>
          <div class="mref-en">Use the <b>Download</b> tab: search HuggingFace (sort by trending / downloads, filter by task) and one-click download into your <code>--model-dir</code> — a background job with progress, auto-registered when finished. ModelScope works by model ID (needs <b>[modelscope]</b>). On a restricted network, set a mirror under Settings → HuggingFace endpoint. Then on <b>Models</b>: Load (or pick a device) and Pin to keep it resident; say hi on <b>Chat</b> to verify; measure it on <b>Benchmark</b>.</div>
          <div class="mref-zh">用「<b>下载</b>」页：搜索 HuggingFace（按趋势/下载量排序、按任务筛选）一键下载到 <code>--model-dir</code> —— 后台任务带进度，完成后自动注册。ModelScope 按模型 ID 下载（需 <b>[modelscope]</b>）。内网受限时在 设置 → HuggingFace 端点 填镜像。之后在「<b>模型</b>」页：加载（或选卡加载）、固定常驻；到「<b>对话</b>」页发条消息验证；再到「<b>基准测试</b>」页测量。</div>
          <pre class="term"># a model is just a folder under --model-dir 模型即目录
~/models/Qwen2.5-0.5B-Instruct/     # downloaded, or copied by hand 下载或手动拷贝</pre>
        </div>

        <div class="panel" style="padding:16px 18px;margin-bottom:14px">
          <h3 style="margin:0 0 8px" data-i18n="Team shared library">Team shared library</h3>
          <div class="mref-en">Pick one always-on machine as the <b>hub</b> (add <code>--api-key</code> if it is reachable beyond your team). Each teammate then points at it: Settings → Shared library → display name + hub URL (+ hub API key if the hub enforces one) → Save. From then on completed benchmarks auto-publish, and Explorer / Community / Compare read the pooled library. Leave hub URL blank to keep runs local — that machine can itself be the hub.</div>
          <div class="mref-zh">选一台常开的机器当 <b>hub</b>（若团队之外也能访问，加 <code>--api-key</code>）。每位同事在自己机器上：设置 → 共享库 → 填显示名称 + Hub URL（hub 开鉴权则再填 hub API key）→ 保存。之后完成的基准测试自动发布，性能浏览器 / 社区基准 / A/B 对比读取的都是汇聚后的库。Hub URL 留空 = 记录只存本机 —— 该机器自身即可作为 hub。</div>
          <pre class="term"># hub — one machine 一台机器
infermesh start --host 0.0.0.0 --port 8000 --api-key TEAMKEY
# teammates 同事端 → Settings → Shared library → http://hub-host:8000 (+ TEAMKEY)</pre>
        </div>
      </section>

      <section class="section" id="sec-community">
        <div class="panel" style="padding:13px 14px;margin-bottom:14px">
          <div class="cm-filters">
            <select id="cmChip"><option value="" data-i18n="all chips">all chips</option></select>
            <select id="cmVendor"><option value="" data-i18n="all variants">all variants</option></select>
            <input id="cmModel" type="text" placeholder="search model…" data-i18n-ph="search model…" style="width:160px"/>
            <select id="cmQuant"><option value="" data-i18n="all quants">all quants</option></select>
            <select id="cmContext"><option value="" data-i18n="all contexts">all contexts</option></select>
            <input id="cmMinPp" type="number" min="0" placeholder="Min pp" data-i18n-ph="Min pp" style="width:92px"/>
            <input id="cmMinTg" type="number" min="0" placeholder="Min TG" data-i18n-ph="Min TG" style="width:92px"/>
            <select id="cmSort">
              <option value="recent" data-i18n="Recent">Recent</option>
              <option value="pp" data-i18n="Highest pp">Highest pp</option>
              <option value="tg" data-i18n="Highest TG">Highest TG</option>
              <option value="model" data-i18n="Model">Model</option>
              <option value="chip" data-i18n="Chip">Chip</option>
            </select>
            <button class="btn sm" id="cmExport" data-i18n="Export CSV">Export CSV</button>
            <span class="spacer"></span>
            <span class="muted" id="cmCount" style="font-size:12px"></span>
          </div>
        </div>
        <div class="panel">
          <table>
            <thead><tr><th style="width:30px"></th><th data-i18n="Chip">Chip</th><th data-i18n="Model">Model</th><th data-i18n="Quant">Quant</th><th data-i18n="Context">Context</th><th>pp tok/s</th><th>TG tok/s</th><th data-i18n="Peak Mem">Peak Mem</th><th data-i18n="Submitter">Submitter</th><th data-i18n="Date">Date</th></tr></thead>
            <tbody id="cmRows"><tr><td colspan="10" class="muted" data-i18n="no benchmarks yet">no benchmarks yet</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="section" id="sec-settings">
        <div class="form">
          <h3 data-i18n="Runtime-editable">Runtime-editable</h3>
          <div class="field">
            <label for="setIdle" data-i18n="Idle timeout (seconds)">Idle timeout (seconds)</label>
            <div class="row">
              <input id="setIdle" type="number" min="0" step="0.5" style="width:160px"/>
              <button class="btn" id="saveIdle" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="0 disables auto-unload. Applies live to the TTL reaper.">0 disables auto-unload. Applies live to the TTL reaper.</div>
          </div>
          <div class="field">
            <label for="setConc" data-i18n="Max concurrent requests">Max concurrent requests</label>
            <div class="row">
              <input id="setConc" type="number" min="1" step="1" style="width:140px"/>
              <input id="setQueue" type="number" min="0" step="1" placeholder="queue bound (0 = unbounded)" data-i18n-ph="queue bound (0 = unbounded)" style="width:240px"/>
              <button class="btn" id="saveConc" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Admission cap applied live. Queue bound > 0 returns 503 once that many requests are waiting.">Admission cap applied live. Queue bound &gt; 0 returns 503 once that many requests are waiting.</div>
          </div>
          <div class="field">
            <label for="setKey" data-i18n="API key">API key</label>
            <div class="row">
              <input id="setKey" type="text" placeholder="enter key — blank = disable auth" data-i18n-ph="enter key — blank = disable auth" style="width:300px" autocomplete="off"/>
              <button class="btn" id="applyKey" data-i18n="Apply">Apply</button>
            </div>
            <div class="hint"><span data-i18n="Sets or clears the single bearer key the gateway enforces. Current:">Sets or clears the single bearer key the gateway enforces. Current:</span> <span id="keyState" class="mono"></span></div>
          </div>
          <div class="field">
            <label for="setKvHot" data-i18n="KV cache — hot entries (Transformers tiered KV)">KV cache &mdash; hot entries (Transformers tiered KV)</label>
            <div class="row">
              <input id="setKvHot" type="number" min="0" step="1" style="width:140px"/>
              <input id="setKvCold" type="text" placeholder="cold (SSD) dir &mdash; blank = ~/.infermesh/kv" data-i18n-ph="cold (SSD) dir — blank = ~/.infermesh/kv" style="width:320px" autocomplete="off"/>
              <button class="btn" id="saveKv" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Hot RAM entries for the tiered KV cache (0 = off). Applies to models loaded after saving.">Hot RAM entries for the tiered KV cache (0 = off). Applies to models loaded after saving.</div>
          </div>
          <div class="field">
            <label for="setHfEndpoint" data-i18n="HuggingFace endpoint (mirror)">HuggingFace endpoint (mirror)</label>
            <div class="row">
              <input id="setHfEndpoint" type="text" placeholder="blank = huggingface.co &middot; e.g. https://hf-mirror.com" data-i18n-ph="blank = huggingface.co · e.g. https://hf-mirror.com" style="width:340px" autocomplete="off"/>
              <button class="btn" id="saveHf" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Search + download via a mirror (faster/accessible in some regions). Applies immediately.">Search + download via a mirror (faster/accessible in some regions). Applies immediately.</div>
          </div>
          <h3 style="margin-top:26px" data-i18n="Generation defaults">Generation defaults</h3>
          <div class="field">
            <label for="setGenTemp" data-i18n="Sampling defaults — applied when a request omits the parameter">Sampling defaults &mdash; applied when a request omits the parameter</label>
            <div class="row">
              <input id="setGenTemp" type="number" min="0" max="2" step="0.05" placeholder="temperature" title="temperature 0&ndash;2" style="width:130px"/>
              <input id="setGenTopP" type="number" min="0" max="1" step="0.05" placeholder="top_p" title="top_p 0&ndash;1" style="width:115px"/>
              <input id="setGenTopK" type="number" min="0" step="1" placeholder="top_k" title="top_k (0 = off)" style="width:110px"/>
              <input id="setGenMax" type="number" min="1" step="1" placeholder="max_tokens" title="max output tokens" style="width:135px"/>
              <button class="btn" id="saveGen" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Blank = no server default (the client's value or the built-in fallback applies). A request's own values always win.">Blank = no server default (the client's value or the built-in fallback applies). A request's own values always win.</div>
          </div>
          <h3 style="margin-top:26px" data-i18n="Shared library">Shared library</h3>
          <div class="field">
            <label for="setSubmitter" data-i18n="Display name — how your runs appear in the Community library">Display name &mdash; how your runs appear in the Community library</label>
            <div class="row">
              <input id="setSubmitter" type="text" placeholder="blank = hostname" data-i18n-ph="blank = hostname" style="width:260px" autocomplete="off"/>
              <label class="ex-check" style="margin:0 4px"><input type="checkbox" id="setAutoPub"/> <span data-i18n="Auto-publish benchmarks">Auto-publish benchmarks</span></label>
              <button class="btn" id="saveCommunity" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Completed benchmarks are submitted to the shared library so colleagues can compare. Hub URL blank = this server is the hub.">Completed benchmarks are submitted to the shared library so colleagues can compare. Hub URL blank = this server is the hub.</div>
            <div class="row" style="margin-top:8px">
              <input id="setHubUrl" type="text" placeholder="hub URL — blank = this server is the hub" data-i18n-ph="hub URL — blank = this server is the hub" style="width:430px" autocomplete="off"/>
              <input id="setHubKey" type="password" placeholder="hub API key — blank = keep unchanged" data-i18n-ph="hub API key — blank = keep unchanged" style="width:270px" autocomplete="new-password"/>
              <span class="muted" id="hubKeyState" style="font-size:12px"></span>
            </div>
          </div>
          <h3 style="margin-top:26px"><span data-i18n="Startup">Startup</span> <span class="badge warn" data-i18n="restart to apply">restart to apply</span></h3>
          <div class="field">
            <label data-i18n="Bind address, model dir &amp; default backend &mdash; saved now, applied on restart">Bind address, model dir &amp; default backend &mdash; saved now, applied on restart</label>
            <div class="row">
              <input id="setHost" type="text" placeholder="host" title="bind host" style="width:140px" autocomplete="off"/>
              <input id="setPort" type="number" min="1" max="65535" step="1" placeholder="port" title="bind port" style="width:110px"/>
              <input id="setBackend" type="text" placeholder="backend" title="default backend" style="width:140px" autocomplete="off"/>
              <input id="setMaxMem" type="text" placeholder="max memory e.g. 80%" data-i18n-ph="max memory e.g. 80%" title="max process memory" style="width:170px" autocomplete="off"/>
            </div>
            <div class="row" style="margin-top:8px">
              <input id="setModelDir" type="text" placeholder="model dir &mdash; blank = none" data-i18n-ph="model dir — blank = none" title="model directory" style="width:430px" autocomplete="off"/>
              <button class="btn" id="saveStartup" data-i18n="Save">Save</button>
            </div>
            <div class="hint" data-i18n="Read once when the server boots. Changing host/port moves the server — you'll reconnect at the new address.">Read once when the server boots. Changing <strong>host/port</strong> moves the server &mdash; you'll reconnect at the new address.</div>
          </div>
          <div id="restartBar" class="field" style="display:none">
            <div class="row" style="align-items:center;gap:10px">
              <span class="badge warn" data-i18n="restart required">restart required</span>
              <span class="muted" id="restartMsg" style="font-size:12px" data-i18n="Saved — restart to apply.">Saved &mdash; restart to apply.</span>
              <button class="btn primary" id="restartBtn" data-i18n="Restart server">Restart server</button>
            </div>
          </div>
          <p id="settings-err" class="err"></p>
          <h3 style="margin-top:26px" data-i18n="All settings">All settings</h3>
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
const TITLES={models:'Models',chat:'Chat',logs:'Logs',metrics:'Metrics',devices:'Devices',download:'Download',benchmark:'Benchmark',explorer:'Explorer',analysis:'Hardware Analysis',compare:'Compare A/B',community:'Community',settings:'Settings',guide:'Guide'};
/* ---- i18n: keys are the English text; only ZH needs entries. Units (tok/s, ms, %, MB) + proper nouns stay. ---- */
const I18N={
"Models":"模型","Chat":"对话","Logs":"日志","Metrics":"指标","Devices":"设备","Download":"下载","Benchmark":"基准测试","Settings":"设置",
"Hardware Analysis":"硬件分析","Compare A/B":"A/B 对比","Guide":"指南",
"Install":"安装","System overview":"系统介绍","Connect a GPU":"连接显卡（GPU）","Connect a model":"连接大模型","Team shared library":"团队共享库",
"Refresh":"刷新","API key (if enabled)":"API 密钥（如启用）","Toggle theme":"切换主题",
"Load on device":"加载到设备","applies to the next Load (Transformers backend)":"应用于下次加载（Transformers 后端）",
"Model":"模型","Type":"类型","Backend":"后端","Status":"状态","Mem MB":"内存 MB","Gen tps":"生成 tps","Leases":"租约","Actions":"操作","loading…":"加载中…",
"Clear":"清除","Send":"发送","Message the model…  (Enter to send, Shift+Enter for newline)":"给模型发消息…（Enter 发送，Shift+Enter 换行）",
"Live tail of infermesh logs (pool · server · backends)":"infermesh 日志实时跟踪（池 · 服务 · 后端）","pause":"暂停",
"Session":"本次会话","All-Time":"全部时间","All models":"所有模型","aggregate request stats — All-Time survives restarts":"汇总请求统计 — 全部时间在重启后保留",
"Copy":"复制","Export CSV":"导出 CSV",
"Overview":"概览","Per-model":"按模型","Charts":"图表","Rejections":"拒绝",
"Token composition":"令牌构成","Cache efficiency":"缓存效率",
"Requests":"请求数","Gen tok/s":"生成 tok/s","Tokens":"令牌","Cache %":"缓存 %","no per-model data yet":"暂无按模型数据",
"All":"全部","Latency per request (ms)":"每请求延迟（ms）","Throughput per request (tokens/s)":"每请求吞吐（tokens/s）",
"History records one point per chat completion — use the Chat tab (or send API requests) to generate data.":"每次对话补全记录一个数据点 — 在「对话」标签页（或发送 API 请求）生成数据。",
"Requests rejected before serving, by reason":"服务前被拒绝的请求（按原因）","none":"无","rejected":"已拒绝",
"Tokens served":"已服务令牌","Avg tokens/req":"平均令牌/请求","Prompt tokens":"提示令牌","Completion tokens":"补全令牌","Cached tokens":"缓存令牌","Prefill":"预填充","Generation":"生成","Uptime":"运行时间","Success rate":"成功率",
"Loaded models":"已加载模型","Active requests":"活跃请求","Queue depth":"队列深度","Recent":"最近",
"Avg latency":"平均延迟","p95 latency":"p95 延迟","Avg throughput":"平均吞吐","Peak throughput":"峰值吞吐","Last latency":"最近延迟",
"Prompt (new)":"提示（新）","Cached":"缓存","Completion":"补全","prompt tokens reused":"提示令牌已复用",
"Detected compute devices — pick one per model on the Models tab":"检测到的计算设备 — 在「模型」标签页为每个模型选择",
"Device":"设备","Vendor":"厂商","Name":"名称","VRAM used":"已用显存","VRAM free":"空闲显存","VRAM total":"总显存",
"Search HuggingFace models (e.g. Qwen2.5-0.5B-Instruct)":"搜索 HuggingFace 模型（例如 Qwen2.5-0.5B-Instruct）",
"Filter by task":"按任务筛选","Any task":"任意任务","Text generation":"文本生成","Vision (VLM)":"视觉（VLM）","Embedding":"嵌入",
"Sort by":"排序方式","Most downloads":"下载最多","Trending":"趋势","Most likes":"点赞最多","Recently updated":"最近更新","Search":"搜索",
"Downloads land in the server's --model-dir and appear under Models when finished.":"下载保存到服务器的 --model-dir，完成后出现在「模型」中。",
"Task":"任务","Downloads":"下载量","Likes":"点赞","popular models load here…":"正在加载热门模型…",
"Repo":"仓库","Progress":"进度","Size":"大小","no downloads yet":"暂无下载","Download jobs":"下载任务",
"Concurrency":"并发","Max tokens":"最大令牌","Mode":"模式","same prompt":"相同提示","different":"不同",
"Run benchmark":"运行基准测试","Single request":"单次请求",
"Cancel":"取消","running":"运行中","queued":"排队中","waiting for a slot":"等待空闲槽位","loading model":"加载模型中","correctness check":"正确性校验","benchmark cancelled":"基准测试已取消","benchmark failed":"基准测试失败","cancel requested":"已请求取消","cancel failed":"取消失败",
"Latency / E2E (ms)":"延迟 / E2E（ms）","Time to first token (ms)":"首令牌时间（ms）","Time per output token (ms)":"每输出令牌时间（ms）","Latency percentiles":"延迟百分位",
"Past runs — persisted across restarts":"历史运行 — 重启后保留","When":"时间","Req×Conc":"请求×并发","no past runs":"暂无历史运行",
"Runtime-editable":"运行时可编辑","Idle timeout (seconds)":"空闲超时（秒）","Save":"保存","0 disables auto-unload. Applies live to the TTL reaper.":"0 表示禁用自动卸载。实时应用于 TTL 回收器。",
"API key":"API 密钥","enter key — blank = disable auth":"输入密钥 — 留空 = 关闭鉴权","Apply":"应用","Sets or clears the single bearer key the gateway enforces. Current:":"设置或清除网关强制的单一密钥。当前：",
"KV cache — hot entries (Transformers tiered KV)":"KV 缓存 — 热条目（Transformers 分层 KV）","cold (SSD) dir — blank = ~/.infermesh/kv":"冷（SSD）目录 — 留空 = ~/.infermesh/kv","Hot RAM entries for the tiered KV cache (0 = off). Applies to models loaded after saving.":"分层 KV 缓存的热 RAM 条目（0 = 关闭）。应用于保存后加载的模型。",
"HuggingFace endpoint (mirror)":"HuggingFace 端点（镜像）","blank = huggingface.co · e.g. https://hf-mirror.com":"留空 = huggingface.co · 例如 https://hf-mirror.com","Search + download via a mirror (faster/accessible in some regions). Applies immediately.":"通过镜像搜索+下载（部分地区更快/可访问）。立即应用。",
"Generation defaults":"生成默认值","Sampling defaults — applied when a request omits the parameter":"采样默认值 — 当请求省略该参数时应用","Blank = no server default (the client's value or the built-in fallback applies). A request's own values always win.":"留空 = 无服务器默认值（应用客户端值或内置回退）。请求自带的值始终优先。",
"Startup":"启动","restart to apply":"重启后生效","Bind address, model dir & default backend — saved now, applied on restart":"绑定地址、模型目录和默认后端 — 立即保存，重启后生效","max memory e.g. 80%":"最大内存 例如 80%","model dir — blank = none":"模型目录 — 留空 = 无",
"Read once when the server boots. Changing host/port moves the server — you'll reconnect at the new address.":"仅在服务器启动时读取。更改 host/port 会迁移服务器 — 需在新地址重新连接。",
"restart required":"需要重启","Saved — restart to apply.":"已保存 — 重启后生效。","Restart server":"重启服务器","All settings":"全部设置",
"connecting":"连接中","healthy":"正常","unreachable":"无法连接",
"stats copied":"已复制统计","generation defaults saved":"已保存生成默认值","startup settings saved":"已保存启动设置","KV cache settings saved":"已保存 KV 缓存设置","HuggingFace endpoint saved":"已保存 HuggingFace 端点","Idle timeout saved":"已保存空闲超时",
"Max concurrent requests":"最大并发请求","queue bound (0 = unbounded)":"队列上限（0 = 无限）","Admission cap applied live. Queue bound > 0 returns 503 once that many requests are waiting.":"准入上限实时生效。队列上限 > 0 时，等待数达到该值即返回 503。","concurrency saved":"已保存并发设置",
"Per-model overrides":"按模型覆盖","override the global generation defaults for one model":"为单个模型覆盖全局生成默认值","Per-model values win over the global defaults; a request's own value still wins. max_context_window rejects over-long prompts (approximate).":"按模型的值优先于全局默认值；请求自带的值仍然最优先。max_context_window 会拒绝过长的 prompt（近似）。","model overrides saved":"已保存模型覆盖","model overrides cleared":"已清除模型覆盖",
"ModelScope (by model ID)":"ModelScope（按模型 ID）",
"Prefill (PP)":"预填充 (PP)","Decode (TG)":"解码 (TG)","Throughput":"吞吐","Output":"输出","Peak GPU mem":"峰值显存","Succeeded":"成功","Run context":"运行配置","Prefill — PP TPS":"预填充 — PP TPS","Decode — TG TPS":"解码 — TG TPS","Single-request latency / E2E (ms)":"单请求延迟 / E2E (ms)","Peak GPU memory":"峰值显存",
"max ctx (approx)":"最大上下文（近似）","overrides":"项覆盖","using global defaults":"使用全局默认值",
"Device":"设备","auto (current)":"自动（当前）","connected":"已连接","offline":"离线",
"Models loaded":"已加载模型","Committed memory":"已占用内存","Live used / ceiling":"实时使用 / 上限","Host RAM":"主机内存","loading":"加载中","loaded":"已加载","idle":"空闲","pinned":"已固定","Load":"加载","Unload":"卸载","Pin":"固定","Unpin":"取消固定","no models discovered":"未发现模型","single request":"单次请求","continuous batching":"连续批处理",
"Lines:":"行数：","Min display level":"最低显示级别","filters the view only — not the saved log file":"仅过滤此处显示 — 不影响日志文件的保存级别","Showing":"显示","lines":"行","no logs yet":"暂无日志",
"Metrics Reference":"指标说明","System":"系统","Raw command":"原始命令","Raw result (terminal)":"原始结果（终端）","Raw command & terminal output":"原始命令 & 终端输出","command":"命令","results":"结果","raw JSON":"原始 JSON","copied":"已复制",
"Explorer":"性能浏览器","Community":"社区基准","Share to library":"分享到库",
"Metric":"指标","show data points":"显示数据点","Chip":"芯片","Quant":"量化","Context":"上下文","+ Add comparison":"+ 添加对比","any quant":"任意量化","remove":"移除","Peak Mem":"峰值显存","Submitter":"提交者","Date":"日期",
"Visualize and compare model performance across context lengths — all data from the shared library.":"可视化并对比不同上下文长度下的模型性能 — 全部数据来自共享库。",
"No data yet — run a benchmark (auto-published) or pick a comparison above.":"暂无数据 — 运行一次基准测试（会自动发布），或在上方选择一个对比。",
"all chips":"全部芯片","all variants":"全部厂商","search model…":"搜索模型…","all quants":"全部量化","all contexts":"全部上下文","Min pp":"最小 pp","Min TG":"最小 TG","Highest pp":"pp 最高","Highest TG":"TG 最高","no benchmarks yet":"暂无基准测试记录",
"Shared library":"共享库","Display name — how your runs appear in the Community library":"显示名称 — 你的测试在社区库中如何显示","blank = hostname":"留空 = 主机名","Auto-publish benchmarks":"自动发布基准测试","Completed benchmarks are submitted to the shared library so colleagues can compare. Hub URL blank = this server is the hub.":"完成的基准测试会提交到共享库，方便同事对比。Hub URL 留空 = 本服务器即为 Hub。","hub URL — blank = this server is the hub":"Hub URL — 留空 = 本服务器即为 Hub","hub API key — blank = keep unchanged":"Hub API 密钥 — 留空 = 保持不变","community settings saved":"已保存共享库设置",
"chart data copied":"已复制图表数据","no data to copy":"暂无数据可复制","runs":"条记录","samples":"样本","Reset":"重置",
"Context length":"上下文长度","all":"全部","Raw command & results (terminal)":"原始命令 & 结果（终端）","benchmark command":"基准测试命令",
"No comparisons yet — click + Add comparison.":"暂无对比 — 点击「+ 添加对比」。",
"Pause":"暂停","Resume":"继续","Delete":"删除","paused":"已暂停","deleted":"已删除","resuming":"继续下载","delete model files from disk":"从磁盘删除模型文件","Delete this download and its files?":"删除此下载及其文件？","Delete this model and its files from disk?":"从磁盘删除此模型及其文件？"
};
let lang='en';
function T(s){ return (lang==='zh' && I18N[s]!=null) ? I18N[s] : s; }
function applyLang(l){
  lang=(l==='zh')?'zh':'en';
  try{ localStorage.setItem('infermesh-lang',lang); }catch(e){}
  document.documentElement.setAttribute('lang', lang==='zh'?'zh-CN':'en');
  document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent=T(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-ph]').forEach(function(el){ el.setAttribute('placeholder',T(el.getAttribute('data-i18n-ph'))); });
  document.querySelectorAll('[data-i18n-title]').forEach(function(el){ el.title=T(el.getAttribute('data-i18n-title')); });
  var lb=$('#langBtn'); if(lb) lb.textContent=(lang==='zh')?'EN':'中';
  var tl=$('#title'); if(tl && typeof active!=='undefined' && active) tl.textContent=T(TITLES[active]||'');
  try{ if(typeof tick==='function') tick(); }catch(e){}
  try{   // re-render the active section's dynamic content immediately in the new language
    if(active==='benchmark'){ loadBenchDevices(); renderBenchHistory(); }
    else if(active==='devices'){ refreshDevices(); }
    else if(active==='settings'){ loadSettings(); }
    else if(active==='models'){ refreshModelSettings(); }
    else if(active==='metrics'){ refreshStats(); refreshLive(); refreshPerModel(); }
    else if(active==='explorer'){ renderExSeries(); drawExChart(); }
    else if(active==='community'){ renderCommunity(); }
  }catch(e){}
}
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
function toast(m){const t=$('#toast');t.textContent=T(m);t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600);}
function setHealth(ok){const p=$('#sb-health');p.className='pill '+(ok?'ok':'bad');p.innerHTML='<span class="dot"></span> '+(ok?T('healthy'):T('unreachable'));}
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
  $('#title').textContent=T(TITLES[sec]);
  if(sec==='chat') loadChatModels();
  if(sec==='logs') refreshLogs();
  if(sec==='settings') loadSettings();
  if(sec==='metrics'){ refreshMetrics(); refreshStats(); }
  if(sec==='benchmark'){ loadBenchModels(); loadBenchDevices(); refreshBenchHistory(); }
  if(sec==='explorer') loadExplorer();
  if(sec==='analysis') loadAnalysis();
  if(sec==='compare') loadCompare();
  if(sec==='community') loadCommunity();
  if(sec==='devices') refreshDevices();
  if(sec==='download'){ refreshDownloads(); if(!dlLoaded){ dlLoaded=true; runHfSearch(); } }
  if(sec==='models'){ loadDevicePicker(); refreshModelSettings(); }
}

/* Models */
function renderModels(s){
  const pct=s.ceiling_mb?Math.min(100,Math.round(100*s.used_mb_live/s.ceiling_mb)):0;
  $('#cards').innerHTML=
    '<div class="card"><div class="k">'+T('Models loaded')+'</div><div class="v">'+s.loaded_count+'<small> / '+s.model_count+'</small></div></div>'+
    '<div class="card"><div class="k">'+T('Committed memory')+'</div><div class="v">'+fmt(s.current_model_memory_mb)+'<small> MB</small></div></div>'+
    '<div class="card"><div class="k">'+T('Live used / ceiling')+'</div><div class="v">'+fmt(s.used_mb_live)+'<small> / '+fmt(s.ceiling_mb)+' MB</small></div><div class="bar"><i style="width:'+pct+'%"></i></div></div>'+
    '<div class="card"><div class="k">'+T('Host RAM')+'</div><div class="v">'+fmt(s.total_mb)+'<small> MB</small></div></div>';
  $('#rows').innerHTML=(s.models||[]).map(m=>{
    const st=m.is_loading?'<span class="badge loading">'+T('loading')+'</span>':m.loaded?'<span class="badge loaded">'+T('loaded')+'</span>':'<span class="badge">'+T('idle')+'</span>';
    const pin=m.pinned?' <span class="badge pinned">'+T('pinned')+'</span>':'';
    const tps=m.stats?m.stats.generation_tps:null, mem=m.stats?m.stats.used_mem_mb:m.estimated_mb, id=esc(m.id);
    return '<tr><td><strong>'+id+'</strong></td><td class="muted">'+m.model_type+'</td><td class="muted mono">'+(m.backend||'—')+'</td>'+
      '<td>'+st+pin+'</td><td class="num">'+fmt(mem)+'</td><td class="num">'+(tps==null?'—':tps.toFixed(1))+'</td><td class="num">'+m.in_use+'</td>'+
      '<td class="rowact">'+
        '<button class="btn sm" data-id="'+id+'" data-act="load" '+(m.loaded?'disabled':'')+'>'+T('Load')+'</button>'+
        '<button class="btn sm" data-id="'+id+'" data-act="unload?force=true" '+(m.loaded?'':'disabled')+'>'+T('Unload')+'</button>'+
        '<button class="btn sm" data-id="'+id+'" data-act="'+(m.pinned?'unpin':'pin')+'">'+(m.pinned?T('Unpin'):T('Pin'))+'</button>'+
        '<button class="btn sm" data-id="'+id+'" data-act="delete" title="'+T('delete model files from disk')+'">'+T('Delete')+'</button>'+
      '</td></tr>';
  }).join('')||'<tr><td colspan="8" class="muted">'+T('no models discovered')+'</td></tr>';
}
$('#rows').addEventListener('click',async e=>{
  const b=e.target.closest('button[data-act]'); if(!b) return;
  let act=b.dataset.act;
  if(act==='delete'){
    if(!confirm(T('Delete this model and its files from disk?'))) return;
    try{ await api('/api/hf/download/delete','POST',{repo_id:b.dataset.id}); toast('deleted'); }
    catch(err){ $('#models-err').textContent=String(err); }
    tick(); return;
  }
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
  const lines=($('#logLines')&&$('#logLines').value)||300, lvl=($('#logLevel')&&$('#logLevel').value)||'';
  try{ const d=await api('/api/logs?limit='+lines+(lvl?('&level='+lvl):'')); const el=$('#logs');
    const atBottom=el.scrollHeight-el.scrollTop-el.clientHeight<40;
    el.innerHTML=(d.lines||[]).map(l=>'<div class="logline '+esc(l.level)+'">'+esc(l.line)+'</div>').join('')||'<div class="muted">'+T('no logs yet')+'</div>';
    if($('#logShowing')) $('#logShowing').textContent=T('Showing')+' '+(d.lines||[]).length+' / '+(d.total||0)+' '+T('lines')+(lvl?(' · ≥ '+lvl.toUpperCase()):'');
    if(atBottom) el.scrollTop=el.scrollHeight;
  }catch(e){}
}
$('#logLines')&&($('#logLines').onchange=refreshLogs);
$('#logLevel')&&($('#logLevel').onchange=refreshLogs);
$('#logRefresh')&&($('#logRefresh').onclick=refreshLogs);
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
    gv('#setHost',s.host); gv('#setPort',s.port); gv('#setBackend',s.backend); gv('#setMaxMem',s.max_process_memory); gv('#setModelDir',s.model_dir);
    gv('#setConc',s.max_concurrent_requests); gv('#setQueue',s.max_queued_requests);
    gv('#setSubmitter',s.submitter_label); gv('#setHubUrl',s.hub_url); if($('#setAutoPub')) $('#setAutoPub').checked=(s.auto_publish!==false);
    if($('#setHubKey')) $('#setHubKey').value='';                       // never echo the key back
    if($('#hubKeyState')) $('#hubKeyState').textContent=s.hub_key?'set':'unset';
    $('#keyState').textContent=s.api_key?'set':'unset';
    const order=['backend','model_dir','host','port','max_concurrent_requests','max_queued_requests','idle_timeout','max_process_memory','ttl_check_interval','sse_keepalive_interval','kv_hot_capacity','kv_cold_dir','hf_endpoint','gen_temperature','gen_top_p','gen_top_k','gen_max_tokens','api_key'];
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
async function saveStartup(){
  const v=el=>$(el).value.trim();
  try{ const r=await api('/api/settings','PUT',{host:v('#setHost'),port:(v('#setPort')===''?null:Number(v('#setPort'))),backend:v('#setBackend'),max_process_memory:v('#setMaxMem'),model_dir:v('#setModelDir')});
    toast('startup settings saved'); loadSettings();
    const rr=r.restart_required||[];
    if(rr.length){ $('#restartBar').style.display=''; $('#restartMsg').textContent='Saved '+rr.join(', ')+' — restart to apply.'; }
  }catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveStartup').onclick=saveStartup;
async function restartServer(){
  const btn=$('#restartBtn'); if(btn) btn.disabled=true; $('#restartMsg').textContent='restarting…';
  try{ await api('/api/restart','POST',{}); }catch(e){}   // connection may drop mid-restart — expected
  let tries=0;
  const probe=async()=>{ tries++;
    try{ const h=await fetch('/health',{cache:'no-store'}); if(h.ok){ $('#restartMsg').textContent='back online — reloading…'; setTimeout(()=>location.reload(),700); return; } }catch(_){}
    if(tries<40) setTimeout(probe,500); else { $('#restartMsg').textContent='still restarting… reload manually'; if(btn) btn.disabled=false; }
  };
  setTimeout(probe,1500);
}
$('#restartBtn').onclick=restartServer;
async function saveConc(){
  try{ const c=parseInt($('#setConc').value), q=parseInt($('#setQueue').value);
    await api('/api/settings','PUT',{max_concurrent_requests:isNaN(c)?null:c, max_queued_requests:isNaN(q)?null:q});
    toast('concurrency saved'); loadSettings();
  }catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveConc').onclick=saveConc;
/* Per-model generation overrides */
let msAll={};
async function refreshModelSettings(){
  try{ const ms=await api('/api/model-settings'); msAll=ms.settings||{};
    const d=await api('/v1/models'); const sel=$('#msModel'); const cur=sel.value;
    sel.innerHTML=(d.data||[]).map(m=>{ const has=msAll[m.id]&&Object.keys(msAll[m.id]).length; return '<option value="'+esc(m.id)+'">'+esc(m.id)+(has?' ●':'')+'</option>'; }).join('');
    if(cur) sel.value=cur;
    loadMsFields();
  }catch(e){}
}
function loadMsFields(){
  const o=msAll[$('#msModel').value]||{};
  const set=(el,v)=>{ if($(el)) $(el).value=(v==null?'':v); };
  set('#msTemp',o.temperature); set('#msTopP',o.top_p); set('#msTopK',o.top_k); set('#msMax',o.max_tokens); set('#msCtx',o.max_context_window);
  const n=Object.keys(o).length, has=$('#msHas');
  if(has) has.innerHTML=n?('<span class="chip gpu">'+n+' '+T('overrides')+'</span>'):('<span class="muted" style="font-size:11px">'+T('using global defaults')+'</span>');
}
function msBody(clear){
  const m=$('#msModel').value; const num=el=>{ const v=$(el).value.trim(); return (clear||v==='')?null:Number(v); };
  return {model:m,temperature:num('#msTemp'),top_p:num('#msTopP'),top_k:num('#msTopK'),max_tokens:num('#msMax'),max_context_window:num('#msCtx')};
}
async function saveMs(){ if(!$('#msModel').value) return;
  try{ await api('/api/model-settings','PUT',msBody(false)); toast('model overrides saved'); refreshModelSettings(); }
  catch(e){ $('#models-err').textContent=String(e); } }
async function clearMs(){ if(!$('#msModel').value) return;
  try{ await api('/api/model-settings','PUT',msBody(true)); toast('model overrides cleared'); refreshModelSettings(); }
  catch(e){ $('#models-err').textContent=String(e); } }
$('#msModel').onchange=loadMsFields; $('#msSave').onclick=saveMs; $('#msClear').onclick=clearMs;

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
function statCard(k,v){ return '<div class="card"><div class="k">'+T(k)+'</div><div class="v">'+v+'</div></div>'; }
function fmtUptime(sec){ sec=Math.floor(sec||0); const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60),s=sec%60; if(d) return d+'d '+h+'h'; if(h) return h+'h '+m+'m'; if(m) return m+'m '+s+'s'; return s+'s'; }
async function refreshStats(){
  try{ const sel=$('#stModel'); const model=sel?sel.value:'';
    const s=await api('/api/stats?scope='+statsScope+(model?'&model='+encodeURIComponent(model):'')); lastStats=s;
    if(sel){ const cur=sel.value; sel.innerHTML='<option value="">'+T('All models')+'</option>'+(s.models||[]).map(m=>'<option value="'+esc(m)+'">'+esc(m)+'</option>').join(''); sel.value=cur; }
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
    if($('#tokLeg')) $('#tokLeg').innerHTML=leg('var(--blue)',T('Prompt (new)'),pNew)+leg('var(--accent)',T('Cached'),cached)+leg('var(--warn)',T('Completion'),ct);
    const ce=+s.cache_efficiency||0;
    if($('#cacheV')) $('#cacheV').innerHTML=statN(s.cache_efficiency)+'<small> %</small>';
    if($('#cacheBar')) $('#cacheBar').style.width=Math.min(100,ce)+'%';
    if($('#cacheSub')) $('#cacheSub').textContent=statN(cached)+' / '+statN(pt)+' '+T('prompt tokens reused');
    const rj=s.rejections||{}; const rks=Object.keys(rj);
    if($('#statRej')) $('#statRej').innerHTML = rks.length? (T('rejected')+' — '+rks.map(k=>esc(k)+': '+rj[k]).join(' · ')) : T('none');
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
  $('#pmRows').innerHTML=rows.map(r=>'<tr><td><strong>'+esc(r.model)+'</strong></td><td class="num">'+statN(r.total_requests)+'</td><td class="num">'+statN(r.generation_tps)+'</td><td class="num">'+statN(r.total_tokens_served)+'</td><td class="num">'+statN(r.cache_efficiency)+'</td></tr>').join('')||'<tr><td colspan="5" class="muted">'+T('no per-model data yet')+'</td></tr>';
}
$('#mt-permodel').addEventListener('click',e=>{ const th=e.target.closest('th[data-sort]'); if(!th) return;
  const k=th.dataset.sort; pmSort.dir=(pmSort.key===k)?-pmSort.dir:-1; pmSort.key=k; renderPerModel(); });
/* Metrics: live bar + export/copy */
async function refreshLive(){
  try{ const s=await api('/api/status'); let bActive=0, bQueue=0, loaded=0;
    (s.models||[]).forEach(m=>{ if(m.loaded){ loaded++; if(m.stats){ bActive+=m.stats.active_requests||0; bQueue+=m.stats.queue_depth||0; } } });
    const adm=s.admission||{};                       // control-plane admission is authoritative
    const active=(adm.active!=null)?adm.active:bActive, queue=(adm.waiting!=null)?adm.waiting:bQueue, cap=adm.cap;
    let tps=0; try{ const ms=await api('/api/metrics'); const r=(ms.samples||[]).slice(-5); if(r.length) tps=r.reduce((a,x)=>a+(x.tps||0),0)/r.length; }catch(_){}
    if($('#liveBar')) $('#liveBar').innerHTML=
      statCard('Loaded models', statN(loaded))+
      statCard('Active requests', statN(active)+(cap?'<small> / '+statN(cap)+'</small>':''))+
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
      statCard('Requests', s.length)+
      statCard('Avg latency', avg(lat).toFixed(0)+'<small> ms</small>')+
      statCard('p95 latency', p95.toFixed(0)+'<small> ms</small>')+
      statCard('Avg throughput', avg(tps).toFixed(1)+'<small> tok/s</small>')+
      statCard('Peak throughput', peak.toFixed(1)+'<small> tok/s</small>')+
      statCard('Last latency', (s.length?Math.round(s[s.length-1].latency_ms):'—')+'<small> ms</small>');
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
async function loadBenchDevices(){
  const sel=$('#bmDevice'); if(!sel) return;
  try{
    const dv=await api('/api/devices'); const live=dv.devices||[]; const liveIds=new Set(live.map(d=>d.id));
    let past=[], seen={};
    try{ const h=await api('/api/history'); (h.benchmarks||[]).forEach(b=>{ const r=b.result||{}; if(r.device_name&&r.device&&!liveIds.has(r.device)&&!seen[r.device_name]){ seen[r.device_name]=1; past.push(r.device_name); } }); }catch(_){}
    const cur=sel.value;
    sel.innerHTML='<option value="">'+T('auto (current)')+'</option>'+
      live.map(d=>'<option value="'+esc(d.id)+'">✓ '+esc(d.name)+(d.vendor!=='cpu'?(' · '+T('connected')):'')+'</option>').join('')+
      past.map(nm=>'<option value="" disabled>'+esc(nm)+' · '+T('offline')+'</option>').join('');
    if(cur) sel.value=cur;
  }catch(e){}
}
let benchJobId=null;   // active benchmark job (null = idle)
function benchProgUI(on){
  $('#bmProg').style.display=on?'':'none'; $('#bmProgTxt').style.display=on?'':'none'; $('#bmCancel').style.display=on?'':'none';
  if(!on){ $('#bmProgBar').style.width='0%'; $('#bmProgTxt').textContent=''; }
}
const BENCH_PHASES={queued:'queued',waiting:'waiting for a slot',load:'loading model',running:'running',correctness:'correctness check'};
function benchPct(job){
  const pr=job.progress||{}, ph=(pr.phase||'').split(' ')[0];
  if(job.state==='done') return 100;
  if(ph==='correctness') return 96;
  if(job.state==='running'&&pr.total) return Math.max(8,Math.min(96,Math.round((pr.current||0)*100/pr.total)));
  if(ph==='load') return 8;
  return 3;   // queued / waiting for an admission slot
}
async function pollBenchJob(id){
  let misses=0;   // tolerate brief poll hiccups — the job keeps running server-side
  for(;;){
    let job=null;
    try{ job=await api('/api/bench/jobs/'+id); misses=0; }
    catch(e){ if(++misses>=5) throw e; }
    if(job){
      const pr=job.progress||{}, ph=(pr.phase||'').split(' ')[0];
      $('#bmProgBar').style.width=benchPct(job)+'%';
      const lbl=BENCH_PHASES[ph]?T(BENCH_PHASES[ph]):ph;
      $('#bmProgTxt').textContent=((job.state==='running'&&pr.total)?(pr.current||0)+'/'+pr.total+' · ':'')+lbl;
      if(job.state==='done'||job.state==='failed'||job.state==='cancelled') return job;
    }
    await new Promise(res=>setTimeout(res,500));
  }
}
async function runBenchmark(){
  const model=$('#bmModel').value;
  if(!model){ $('#bm-err').textContent='pick a model'; return; }
  const body={model:model, requests:(+$('#bmReq').value||20), concurrency:(+$('#bmConc').value||4), max_tokens:(+$('#bmTok').value||64), mode:($('#bmMode')?$('#bmMode').value:'same'), device:(($('#bmDevice')&&$('#bmDevice').value)||null), share:($('#bmShare')?$('#bmShare').checked:true)};
  $('#bm-err').textContent=''; $('#bmStatus').textContent=T('running')+' '+body.requests+'×'+body.concurrency+(body.device?(' on '+body.device):'')+'…';
  $('#bmRun').disabled=true; $('#bmSingle').disabled=true; benchProgUI(true);
  try{
    const j=await api('/api/bench/jobs','POST',body);
    benchJobId=j.job_id;
    const job=await pollBenchJob(j.job_id);
    if(job.state==='cancelled'){ $('#bmStatus').textContent=T('benchmark cancelled'); return; }
    if(job.state!=='done'||!job.result){
      $('#bm-err').textContent=job.error?String(job.error):T('benchmark failed'); $('#bmStatus').textContent=''; return; }
    const r=job.result;
    lastBench=r;
    $('#bmStatus').textContent='done · '+(r.model||'')+' on '+(r.device_name||r.device||'cpu')+' · '+r.wall_time_s+'s · mode '+(r.mode||'same');
    loadBenchDevices();
    const pk=(r.peak_mem_mb!=null)?(fmt(r.peak_mem_mb)+' MB'):'—';
    $('#bmCards').innerHTML=
      '<div class="card"><div class="k">'+T('Prefill (PP)')+'</div><div class="v">'+r.pp_tps.mean+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">'+T('Decode (TG)')+'</div><div class="v">'+r.tg_tps.mean+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">TPOT</div><div class="v">'+r.tpot_ms.mean+'<small> ms/tok</small></div></div>'+
      '<div class="card"><div class="k">TTFT p50</div><div class="v">'+r.ttft_ms.p50+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">E2E p50</div><div class="v">'+r.latency_ms.p50+'<small> ms</small></div></div>'+
      '<div class="card"><div class="k">'+T('Throughput')+'</div><div class="v">'+r.requests_per_sec+'<small> req/s</small></div></div>'+
      '<div class="card"><div class="k">'+T('Output')+'</div><div class="v">'+r.output_tokens_per_sec+'<small> tok/s</small></div></div>'+
      '<div class="card"><div class="k">'+T('Peak GPU mem')+'</div><div class="v">'+pk+'</div></div>'+
      '<div class="card"><div class="k">'+T('Succeeded')+'</div><div class="v">'+r.succeeded+'<small> / '+(r.succeeded+r.failed)+'</small></div></div>';
    const L=r.latency_ms, TT=r.ttft_ms, P=r.tpot_ms;
    $('#bmLatency').innerHTML=['mean','p50','p90','p99','min','max'].map(k=>'<dt>'+k+'</dt><dd>'+L[k]+'</dd>').join('');
    $('#bmTtft').innerHTML=['mean','p50','p90','p99'].map(k=>'<dt>'+k+'</dt><dd>'+TT[k]+'</dd>').join('');
    $('#bmTpot').innerHTML=['mean','p50','p90','p99'].map(k=>'<dt>'+k+'</dt><dd>'+P[k]+'</dd>').join('');
    $('#bmDetail').style.display='block';
    drawBars('bmChart', [['p50',L.p50],['p90',L.p90],['p99',L.p99],['max',L.max]]);
    refreshBenchHistory();
  }catch(e){ $('#bm-err').textContent=String(e); $('#bmStatus').textContent=''; }
  finally{ benchJobId=null; benchProgUI(false); $('#bmRun').disabled=false; $('#bmSingle').disabled=false; }
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
$('#bmCancel').onclick=async()=>{ if(!benchJobId) return; $('#bmCancel').disabled=true;
  try{ await api('/api/bench/jobs/'+benchJobId+'/cancel','POST'); toast('cancel requested'); }
  catch(e){ toast('cancel failed'); }
  finally{ $('#bmCancel').disabled=false; } };
$('#bmCopy').onclick=()=>{ if(!lastBench){ toast('run a benchmark first'); return; }
  const txt=JSON.stringify(lastBench,null,2);
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(()=>toast('results copied')).catch(()=>toast('copy failed')); }
  else { toast('clipboard unavailable in this context'); }
};

/* ===================== Explorer (box-plot compare) ===================== */
const EXCOLORS=['#3b82f6','#22c55e','#a855f7','#f59e0b','#ef4444','#14b8a6','#ec4899','#0ea5e9'];
let exFacets={chips:[],models:[],quants:[]}, exSel=[], exData=null, exTipData=[];
const METRIC_LABELS={pp_tps:'PP tok/s',tg_tps:'TG tok/s',ttft_ms:'TTFT (ms)',tpot_ms:'TPOT (ms/tok)',peak_mem_gb:'Peak Mem (GB)',e2e_latency_s:'E2E (s)',total_throughput:'Total tok/s'};
function metricLabel(m){ return METRIC_LABELS[m]||m; }
const QUANTS=['2bit','3bit','4bit','4M','5bit','6bit','7bit','8bit','bf16','fp16'];
function quantList(fq){ const s=QUANTS.slice(); (fq||[]).forEach(q=>{ if(q&&s.indexOf(q)<0) s.push(q); }); return s; }
function quantOptions(fq){ return quantList(fq).map(q=>'<option value="'+esc(q)+'">'+esc(q)+'</option>').join(''); }
function niceTicks(max){ if(!(max>0)) return [0,1]; const raw=max/4, mag=Math.pow(10,Math.floor(Math.log10(raw))), norm=raw/mag, step=(norm<1.5?1:norm<3?2:norm<7?5:10)*mag, top=Math.ceil(max/step)*step, t=[]; for(let v=0; v<=top+step*0.001; v+=step) t.push(Math.round(v*1e6)/1e6); return t; }
function tipRow(k,v){ return '<div class="ex-tip-row"><span>'+k+'</span><b>'+v+'</b></div>'; }
function ctxLabel(c){ c=+c; if(!c) return '—'; if(c>=1000000) return (Math.round(c/100000)/10)+'M'; if(c>=1000) return (Math.round(c/100)/10).toString().replace(/\.0$/,'')+'k'; return ''+c; }
function exNum(v){ if(v==null||v==='') return '—'; v=+v; if(isNaN(v)) return '—'; if(v>=1000) return Math.round(v).toLocaleString(); if(v>=100) return ''+Math.round(v); if(v>=10) return ''+(Math.round(v*10)/10); return ''+(Math.round(v*100)/100); }
async function exportCsv(qs){
  try{ const k=$('#apikey').value.trim();
    const r=await fetch('/api/community/export.csv'+(qs||''),{headers:k?{'Authorization':'Bearer '+k}:{}});
    if(!r.ok){ toast('export failed'); return; }
    const b=await r.blob(), u=URL.createObjectURL(b), a=document.createElement('a');
    a.href=u; a.download='infermesh-community.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(u);
  }catch(e){ toast('export failed'); }
}
async function loadExplorer(){
  try{ const d=await api('/api/community/runs?sort=recent&limit=200');
    exFacets=d.facets||{chips:[],models:[],quants:[]};
    if(exSel.length===0){
      const seen=new Set(), combos=[];
      (d.runs||[]).forEach(r=>{ const key=r.chip+'|'+r.model+'|'+r.quant; if(!seen.has(key)){ seen.add(key); combos.push({chip:r.chip,model:r.model,quant:r.quant}); } });
      if(combos.length){ const m=combos[0].model, pref=combos.filter(c=>c.model===m); exSel=(pref.length>1?pref:combos).slice(0,5); }
    }
  }catch(e){ exFacets={chips:[],models:[],quants:[]}; }
  renderExSeries(); refreshExplorer();
}
function exAddSeries(){
  const chip=(exFacets.chips&&exFacets.chips[0])||'', model=(exFacets.models&&exFacets.models[0])||'';
  exSel.push({chip:chip, model:model, quant:'*'});
  renderExSeries(); refreshExplorer();
}
function renderExSeries(){
  const el=$('#exSeries'); if(!el) return;
  const optsel=(arr,v)=>(arr||[]).map(o=>'<option'+(o===v?' selected':'')+'>'+esc(o)+'</option>').join('');
  const qsel=v=>'<option value="*"'+((v==='*'||!v)?' selected':'')+'>'+T('all')+'</option>'+quantList(exFacets.quants).map(q=>'<option'+(q===v?' selected':'')+'>'+esc(q)+'</option>').join('');
  el.innerHTML=exSel.length?exSel.map((s,i)=>
    '<div class="ex-card"><i class="ex-dot" style="background:'+EXCOLORS[i%EXCOLORS.length]+'"></i>'+
    '<div class="bm-field"><label>'+T('Chip')+'</label><select data-k="chip" data-i="'+i+'" style="min-width:150px">'+optsel(exFacets.chips,s.chip)+'</select></div>'+
    '<div class="bm-field"><label>'+T('Model')+'</label><select data-k="model" data-i="'+i+'" style="min-width:160px">'+optsel(exFacets.models,s.model)+'</select></div>'+
    '<div class="bm-field"><label>'+T('Quant')+'</label><select data-k="quant" data-i="'+i+'" style="min-width:104px">'+qsel(s.quant)+'</select></div>'+
    '<span class="spacer"></span>'+
    '<button class="ex-cardx" data-i="'+i+'" title="'+T('remove')+'" aria-label="remove">&times;</button></div>'
  ).join(''):'<div class="muted" style="font-size:12.5px;padding:6px 2px">'+T('No comparisons yet — click + Add comparison.')+'</div>';
  el.querySelectorAll('select').forEach(sel=>sel.onchange=()=>{ exSel[+sel.dataset.i][sel.dataset.k]=sel.value; refreshExplorer(); });
  el.querySelectorAll('.ex-cardx').forEach(b=>b.onclick=()=>{ exSel.splice(+b.dataset.i,1); renderExSeries(); refreshExplorer(); });
}
async function refreshExplorer(){
  const metric=($('#exMetric')&&$('#exMetric').value)||'pp_tps';
  if(!exSel.length){ exData=null; drawExChart(); return; }
  try{ exData=await api('/api/community/compare?metric='+encodeURIComponent(metric)+'&series='+encodeURIComponent(JSON.stringify(exSel))); }
  catch(e){ exData=null; }
  drawExChart();
}
function drawExChart(){
  const svg=$('#exChart'); if(!svg) return;
  const wrap=svg.parentElement, empty=$('#exEmpty'), leg=$('#exLegend'), tip=$('#exTip');
  if(tip) tip.style.display='none';
  const series=(exData&&exData.series)||[], contexts=(exData&&exData.contexts)||[];
  const metric=($('#exMetric')&&$('#exMetric').value)||'pp_tps';
  const hasData=series.some(s=>s.cells&&Object.keys(s.cells).length);
  if(empty) empty.style.display=hasData?'none':'block';
  if(leg) leg.innerHTML=hasData?series.map((s,i)=>'<span class="ex-leg"><i style="background:'+EXCOLORS[i%EXCOLORS.length]+'"></i>'+esc(s.key)+'</span>').join(''):'';
  if(!hasData){ svg.innerHTML=''; svg.removeAttribute('viewBox'); return; }
  const showPts=$('#exPoints')&&$('#exPoints').checked;
  const W=Math.max(560,((wrap&&wrap.clientWidth)||820)-36), H=460;
  const mL=68,mR=18,mT=14,mB=58, plotW=W-mL-mR, plotH=H-mT-mB;
  let yMax=0; series.forEach(s=>contexts.forEach(c=>{ const cell=s.cells[c]; if(!cell||!cell.n) return; if(cell.max!=null) yMax=Math.max(yMax,cell.max); if(showPts&&cell.points) cell.points.forEach(p=>yMax=Math.max(yMax,p)); }));
  const ticks=niceTicks(yMax||1); yMax=ticks[ticks.length-1]||1;
  const yOf=v=>mT+plotH-(v/yMax)*plotH, groups=Math.max(1,contexts.length), gW=plotW/groups, sN=Math.max(1,series.length), bW=Math.min(34,(gW*0.72)/sN);
  let out=''; exTipData=[];
  // horizontal gridlines — nice round ticks that rescale with the selected metric
  ticks.forEach(v=>{ const yy=yOf(v); out+='<line class="ex-grid" x1="'+mL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+yy.toFixed(1)+'"/>'; out+='<text class="ex-yl" x="'+(mL-8)+'" y="'+(yy+3.5).toFixed(1)+'">'+exNum(v)+'</text>'; });
  // vertical gridlines separating context columns
  for(let gi=0; gi<=groups; gi++){ const vx=(mL+gi*gW).toFixed(1); out+='<line class="ex-vgrid" x1="'+vx+'" y1="'+mT+'" x2="'+vx+'" y2="'+(mT+plotH).toFixed(1)+'"/>'; }
  // axes + axis titles (Y title changes with the metric; X is always context length)
  out+='<line class="ex-axis" x1="'+mL+'" y1="'+mT+'" x2="'+mL+'" y2="'+(mT+plotH).toFixed(1)+'"/>';
  out+='<line class="ex-axis" x1="'+mL+'" y1="'+(mT+plotH).toFixed(1)+'" x2="'+(W-mR)+'" y2="'+(mT+plotH).toFixed(1)+'"/>';
  out+='<text class="ex-axt" transform="translate(15,'+(mT+plotH/2).toFixed(1)+') rotate(-90)">'+esc(metricLabel(metric))+'</text>';
  out+='<text class="ex-axt" x="'+(mL+plotW/2).toFixed(1)+'" y="'+(H-10)+'">'+T('Context length')+'</text>';
  contexts.forEach((c,gi)=>{
    const gx=mL+gi*gW+gW/2;
    out+='<text class="ex-xl" x="'+gx.toFixed(1)+'" y="'+(mT+plotH+19)+'">'+ctxLabel(c)+'</text>';
    series.forEach((s,si)=>{
      const cell=s.cells[c]; if(!cell||!cell.n) return;
      const cx=gx-(sN*bW)/2+si*bW+bW/2, col=EXCOLORS[si%EXCOLORS.length], half=bW*0.40, ci=exTipData.length;
      exTipData.push('<div class="ex-tip-h"><i style="background:'+col+'"></i>'+esc(s.key)+'</div>'+
        tipRow(T('Context length'),ctxLabel(c))+tipRow('median',exNum(cell.median))+tipRow('q1',exNum(cell.q1))+
        tipRow('q3',exNum(cell.q3))+tipRow('mean',exNum(cell.mean))+tipRow('min',exNum(cell.min))+
        tipRow('max',exNum(cell.max))+tipRow(T('samples'),cell.n));
      let g='<g class="ex-box" data-ci="'+ci+'">';
      g+='<line x1="'+cx.toFixed(1)+'" y1="'+yOf(cell.min).toFixed(1)+'" x2="'+cx.toFixed(1)+'" y2="'+yOf(cell.max).toFixed(1)+'" stroke="'+col+'" stroke-width="1.3" opacity=".5"/>';
      if(cell.n===1){
        g+='<line x1="'+(cx-half).toFixed(1)+'" y1="'+yOf(cell.median).toFixed(1)+'" x2="'+(cx+half).toFixed(1)+'" y2="'+yOf(cell.median).toFixed(1)+'" stroke="'+col+'" stroke-width="2.6"/>';
      }else{
        const top=yOf(cell.q3), bot=yOf(cell.q1);
        g+='<rect x="'+(cx-half).toFixed(1)+'" y="'+top.toFixed(1)+'" width="'+(half*2).toFixed(1)+'" height="'+Math.max(1,bot-top).toFixed(1)+'" fill="'+col+'" fill-opacity=".20" stroke="'+col+'" stroke-width="1.3" rx="1.5"/>';
        g+='<line x1="'+(cx-half).toFixed(1)+'" y1="'+yOf(cell.median).toFixed(1)+'" x2="'+(cx+half).toFixed(1)+'" y2="'+yOf(cell.median).toFixed(1)+'" stroke="'+col+'" stroke-width="2.2"/>';
        g+='<line x1="'+(cx-half*0.55).toFixed(1)+'" y1="'+yOf(cell.max).toFixed(1)+'" x2="'+(cx+half*0.55).toFixed(1)+'" y2="'+yOf(cell.max).toFixed(1)+'" stroke="'+col+'" stroke-width="1.2" opacity=".5"/>';
        g+='<line x1="'+(cx-half*0.55).toFixed(1)+'" y1="'+yOf(cell.min).toFixed(1)+'" x2="'+(cx+half*0.55).toFixed(1)+'" y2="'+yOf(cell.min).toFixed(1)+'" stroke="'+col+'" stroke-width="1.2" opacity=".5"/>';
      }
      if(showPts&&cell.points) cell.points.forEach(p=>{ g+='<circle cx="'+cx.toFixed(1)+'" cy="'+yOf(p).toFixed(1)+'" r="2.1" fill="'+col+'" opacity=".5"/>'; });
      const hTop=yOf(cell.max)-5, hH=Math.max(12,(yOf(cell.min)-yOf(cell.max))+10);
      g+='<rect class="ex-hit" x="'+(cx-bW*0.55).toFixed(1)+'" y="'+hTop.toFixed(1)+'" width="'+(bW*1.1).toFixed(1)+'" height="'+hH.toFixed(1)+'" fill="transparent"/>';
      out+=g+'</g>';
    });
  });
  svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.setAttribute('height',H); svg.innerHTML=out;
}
$('#exMetric')&&($('#exMetric').onchange=refreshExplorer);
$('#exPoints')&&($('#exPoints').onchange=drawExChart);
$('#exAdd')&&($('#exAdd').onclick=exAddSeries);
$('#exExport')&&($('#exExport').onclick=()=>exportCsv(''));
$('#exCopy')&&($('#exCopy').onclick=()=>{ if(!exData||!(exData.series||[]).length){ toast('no data to copy'); return; } const txt=JSON.stringify(exData,null,2); if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(txt).then(()=>toast('chart data copied')).catch(()=>toast('copy failed')); } else toast('clipboard unavailable in this context'); });
window.addEventListener('resize',()=>{ if(active==='explorer') drawExChart(); });
(function(){ const svg=$('#exChart'), tip=$('#exTip'); if(!svg||!tip) return;
  svg.addEventListener('mousemove', function(e){ const g=e.target.closest('.ex-box'); if(!g){ tip.style.display='none'; return; }
    tip.innerHTML=exTipData[+g.dataset.ci]||''; tip.style.display='block';
    let x=e.clientX+16, y=e.clientY+14; if(x+184>window.innerWidth) x=e.clientX-180; if(y+160>window.innerHeight) y=window.innerHeight-160;
    tip.style.left=x+'px'; tip.style.top=Math.max(8,y)+'px'; });
  svg.addEventListener('mouseleave', function(){ tip.style.display='none'; });
})();

/* ===================== Community Benchmarks ===================== */
let cmFacets=null, cmRows=[], cmTimer=null;
function cmQuery(){
  const p=new URLSearchParams(), g=id=>{ const e=$(id); return e?e.value.trim():''; };
  if(g('#cmChip'))p.set('chip',g('#cmChip')); if(g('#cmVendor'))p.set('vendor',g('#cmVendor'));
  if(g('#cmModel'))p.set('model',g('#cmModel')); if(g('#cmQuant'))p.set('quant',g('#cmQuant'));
  if(g('#cmContext'))p.set('context',g('#cmContext'));
  if(g('#cmMinPp'))p.set('min_pp',g('#cmMinPp')); if(g('#cmMinTg'))p.set('min_tg',g('#cmMinTg'));
  if(g('#cmSort'))p.set('sort',g('#cmSort'));
  const s=p.toString(); return s?('?'+s):'';
}
async function loadCommunity(){ await refreshCommunity(true); }
async function refreshCommunity(reloadFacets){
  try{ const d=await api('/api/community/runs'+cmQuery());
    cmRows=d.runs||[];
    if(reloadFacets||!cmFacets){ cmFacets=d.facets; fillCmFilters(); }
    renderCommunity();
  }catch(e){ const tb=$('#cmRows'); if(tb) tb.innerHTML='<tr><td colspan="10" class="err">'+esc(String(e))+'</td></tr>'; }
}
function fillCmFilters(){
  if(!cmFacets) return;
  const fill=(id,vals,label)=>{ const el=$(id); if(!el) return; const cur=el.value; el.innerHTML='<option value="">'+T(label)+'</option>'+(vals||[]).map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join(''); el.value=cur; };
  fill('#cmChip',cmFacets.chips,'all chips');
  fill('#cmVendor',cmFacets.vendors,'all variants');
  const cq=$('#cmQuant'); if(cq){ const cur=cq.value; cq.innerHTML='<option value="">'+T('all quants')+'</option>'+quantOptions(cmFacets.quants); cq.value=cur; }
  fill('#cmContext',(cmFacets.contexts||[]).map(String),'all contexts');
}
function cmMem(g){ return g!=null?(exNum(g)+' GB'):'—'; }
function cmRow(r,i){
  let when=''; try{ when=new Date((r.created_at||0)*1000).toLocaleDateString(); }catch(_){}
  const gpu=r.vendor&&r.vendor!=='cpu';
  return '<tr><td><button class="btn sm cm-exp" data-i="'+i+'" aria-label="expand">&#9656;</button></td>'+
    '<td><span class="chip '+(gpu?'gpu':'cpu')+'">'+esc(r.chip||'—')+'</span></td>'+
    '<td><strong>'+esc(r.model||'—')+'</strong></td><td>'+esc(r.quant||'—')+'</td>'+
    '<td class="num">'+(r.context_length!=null?ctxLabel(r.context_length):'—')+'</td>'+
    '<td class="num">'+exNum(r.pp_tps)+'</td><td class="num">'+exNum(r.tg_tps)+'</td>'+
    '<td class="num">'+cmMem(r.peak_mem_gb)+'</td><td>'+esc(r.submitter||'—')+'</td>'+
    '<td class="muted">'+esc(when)+'</td></tr>';
}
function cmCmd(r){
  const dev=(r.vendor&&r.vendor!=='cpu')?(',"device":"'+(r.vendor)+':0"'):'';
  const body='{"model":"'+(r.model||'')+'","requests":20,"concurrency":'+(r.batch_size||1)+',"max_tokens":64'+dev+'}';
  return 'curl -sX POST http://localhost:8188/api/benchmark \\\n  -H \'Content-Type: application/json\' \\\n  -d \''+body+'\'';
}
function cmResults(r){
  const L=[['pp tok/s',exNum(r.pp_tps)],['TG tok/s',exNum(r.tg_tps)],['TTFT ms',exNum(r.ttft_ms)],['TPOT ms/tok',exNum(r.tpot_ms)],['E2E s',r.e2e_latency_s==null?'—':r.e2e_latency_s],['peak mem GB',exNum(r.peak_mem_gb)],['total tok/s',exNum(r.total_throughput)],['context',r.context_length==null?'—':r.context_length],['batch size',r.batch_size==null?'—':r.batch_size]];
  return L.map(p=>('  '+p[0]).padEnd(20)+': '+p[1]).join('\n');
}
function cmDetail(r,i){
  const rows=[['Backend',r.backend],['OS',r.os],['infermesh',r.infermesh_version],['Vendor',r.vendor],['Accel mem (GB)',r.accel_mem_gb],['Submitter',r.submitter]];
  const grid=rows.map(p=>'<div><span class="muted" style="font-size:11.5px">'+T(p[0])+'</span><br><span class="mono">'+(p[1]==null||p[1]===''?'—':esc(String(p[1])))+'</span></div>').join('');
  const term='<details class="bm-term" style="margin:0 16px 14px"><summary>'+T('Raw command & results (terminal)')+'</summary>'+
    '<pre class="term"><span class="muted"># '+T('benchmark command')+'</span>\n$ '+esc(cmCmd(r))+'\n\n<span class="muted"># '+T('results')+'</span>\n'+esc(cmResults(r))+'\n\n<span class="muted"># '+T('raw JSON')+'</span>\n'+esc(JSON.stringify(r,null,2))+'</pre></details>';
  return '<tr class="cm-det" id="cm-det-'+i+'" style="display:none"><td colspan="10"><div class="cm-detwrap">'+grid+'</div>'+term+'</td></tr>';
}
function renderCommunity(){
  const tb=$('#cmRows'); if(!tb) return;
  const open=new Set(); document.querySelectorAll('#cmRows tr.cm-det').forEach(tr=>{ if(tr.style.display!=='none') open.add(tr.id); });
  const cc=$('#cmCount'); if(cc) cc.textContent=cmRows.length+' '+T('runs');
  tb.innerHTML=cmRows.length?cmRows.map((r,i)=>cmRow(r,i)+cmDetail(r,i)).join(''):'<tr><td colspan="10" class="muted">'+T('no benchmarks yet')+'</td></tr>';
  tb.querySelectorAll('button.cm-exp').forEach(b=>b.onclick=()=>{ const tr=document.getElementById('cm-det-'+b.dataset.i); if(!tr) return; const sh=tr.style.display==='none'; tr.style.display=sh?'table-row':'none'; b.innerHTML=sh?'&#9662;':'&#9656;'; });
  open.forEach(id=>{ const tr=document.getElementById(id); if(tr){ tr.style.display='table-row'; const b=document.querySelector('#cmRows button.cm-exp[data-i="'+id.replace('cm-det-','')+'"]'); if(b) b.innerHTML='&#9662;'; } });
}
['#cmChip','#cmVendor','#cmQuant','#cmContext','#cmSort'].forEach(id=>{ const e=$(id); if(e) e.onchange=()=>refreshCommunity(false); });
['#cmModel','#cmMinPp','#cmMinTg'].forEach(id=>{ const e=$(id); if(e) e.oninput=()=>{ clearTimeout(cmTimer); cmTimer=setTimeout(()=>refreshCommunity(false),300); }; });
$('#cmExport')&&($('#cmExport').onclick=()=>exportCsv(cmQuery()));
async function saveCommunity(){
  try{ const cm={submitter_label:$('#setSubmitter').value, auto_publish:$('#setAutoPub').checked, hub_url:$('#setHubUrl').value};
    const hk=$('#setHubKey')?$('#setHubKey').value.trim():'';
    if(hk)cm.hub_key=hk;                                  // blank = keep the stored key
    await api('/api/settings','PUT',cm);
    toast('community settings saved'); loadSettings();
  }catch(e){ $('#settings-err').textContent=String(e); }
}
$('#saveCommunity')&&($('#saveCommunity').onclick=saveCommunity);

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
let bmHistRows=[];
async function refreshBenchHistory(){
  try{ const h=await api('/api/history'); bmHistRows=(h.benchmarks||[]).slice().reverse(); renderBenchHistory(); }catch(e){}
}
function renderBenchHistory(){
  // re-render from cache (instant, no fetch) and preserve which detail rows were expanded
  const open=new Set(); document.querySelectorAll('#bmHist tr.bm-det').forEach(tr=>{ if(tr.style.display!=='none') open.add(tr.id); });
  $('#bmHist').innerHTML=bmHistRows.map((x,i)=>bmSummaryRow(x,i)+bmDetailRow(x,i)).join('')||'<tr><td colspan="8" class="muted">'+T('no past runs')+'</td></tr>';
  open.forEach(id=>{ const tr=document.getElementById(id); if(tr){ tr.style.display='table-row'; const i=id.replace('bm-det-',''); const b=document.querySelector('#bmHist button.bm-exp[data-i="'+i+'"]'); if(b) b.innerHTML='&#9662;'; } });
}
function bmn(v){ return v!=null?v:'—'; }
function devChip(r){ const nm=r&&r.device_name, d=r&&r.device, v=r&&r.vendor; if(!d&&!v&&!nm) return ''; const gpu=!!(v&&v!=='cpu'); return '<span class="chip '+(gpu?'gpu':'cpu')+'" title="'+esc((v||'')+' '+(d||''))+'">'+(gpu?esc(nm||v):'CPU')+'</span>'; }
function bmKv(obj,keys){ return '<dl class="kv kv-sm">'+keys.map(k=>'<dt>'+k+'</dt><dd>'+bmn(obj&&obj[k])+'</dd>').join('')+'</dl>'; }
function bmRows(pairs){ return '<dl class="kv kv-sm">'+pairs.map(p=>'<dt>'+p[0]+'</dt><dd>'+bmn(p[1])+'</dd>').join('')+'</dl>'; }
function bmBlock(title,body){ return '<div class="bm-block"><div class="bm-bt">'+title+'</div>'+body+'</div>'; }
function bmSummaryRow(x,i){
  const r=x.result||{}, L=r.latency_ms||{}, p=x.params||{};
  let when=''; try{ when=new Date((x.t||0)*1000).toLocaleString(); }catch(_){ }
  return '<tr><td><button class="btn sm bm-exp" data-i="'+i+'" aria-label="expand">&#9656;</button></td>'+
    '<td class="muted">'+esc(when)+'</td><td><strong>'+esc(x.model||'')+'</strong> '+devChip(r)+' <span class="muted" style="font-size:11px">'+esc(r.mode||'')+'</span></td>'+
    '<td class="num">'+bmn(p.requests)+'&times;'+bmn(p.concurrency)+'</td>'+
    '<td class="num">'+bmn(r.requests_per_sec)+'</td><td class="num">'+bmn(r.output_tokens_per_sec)+'</td>'+
    '<td class="num">'+bmn(L.p50)+'</td><td class="num">'+bmn(L.p99)+'</td></tr>';
}
function bmDetailRow(x,i){
  return '<tr class="bm-det" id="bm-det-'+i+'" style="display:none"><td colspan="8" style="padding:0">'+bmDetail(x)+'</td></tr>';
}
function bmDetail(x){
  const r=x.result||{}, p=x.params||{}, sys=x.system||{};
  const L=r.latency_ms||{}, TT=r.ttft_ms||{}, P=r.tpot_ms||{}, pp=r.pp_tps||{}, tg=r.tg_tps||{};
  const single=(p.requests==1&&p.concurrency==1);
  const pk=r.peak_mem_mb!=null?(fmt(r.peak_mem_mb)+' MB'):'—';
  const succ=(r.succeeded!=null?r.succeeded+' / '+((r.succeeded||0)+(r.failed||0)):'—');
  const g0=(sys.gpus&&sys.gpus[0])||null, gpu=g0?(g0.name+(g0.mem_total_mb?(' · '+fmt(g0.mem_total_mb)+' MB'):'')):(r.device_name||'—');
  return '<div class="bm-grid">'+
    bmBlock(T('Run context'), bmRows([['model',esc(r.model||x.model||'')],['GPU',esc(r.device_name||'—')],['device',esc(r.device||'—')],['accelerator',esc(r.vendor||'—')],['mode',esc(r.mode||'—')],['type',single?T('single request'):T('continuous batching')],['requests',p.requests],['concurrency',p.concurrency],['max tokens',p.max_tokens],['wall time (s)',r.wall_time_s],['succeeded',succ]]))+
    bmBlock(T('Throughput'), bmRows([['requests / s',r.requests_per_sec],['output tok / s',r.output_tokens_per_sec]]))+
    bmBlock(T('Prefill — PP TPS'), bmRows([['mean',pp.mean],['max',pp.max],['prompt tokens',r.total_prompt_tokens]]))+
    bmBlock(T('Decode — TG TPS'), bmRows([['mean',tg.mean],['max',tg.max],['output tokens',r.total_output_tokens]]))+
    bmBlock(T('Single-request latency / E2E (ms)'), bmKv(L,['mean','p50','p90','p99','min','max']))+
    bmBlock(T('Time to first token (ms)'), bmKv(TT,['mean','p50','p90','p99','min','max']))+
    bmBlock(T('Time per output token (ms)'), bmKv(P,['mean','p50','p90','p99']))+
    bmBlock(T('Peak GPU memory'), bmRows([['peak',pk]]))+
    bmBlock(T('System'), bmRows([['os',esc(sys.os||'—')],['python',esc(sys.python||'—')],['infermesh',esc(sys.infermesh||'—')],['cpu',esc((sys.cpu||'—')+' · '+(sys.cpu_cores||'?')+' cores')],['ram',sys.ram_gb?(sys.ram_gb+' GB'):'—'],['gpu',esc(gpu)],['host',esc(sys.hostname||'—')]]))+
  '</div>'+bmTerminal(x);
}
function bmTermText(x){
  const r=x.result||{}, p=x.params||{}, s=x.system||{}, num=v=>(v==null?'—':v);
  const rows=[
    ['Model', x.model], ['Device', (r.device_name||r.device||'—')+(r.vendor?(' ('+r.vendor+')'):'')],
    ['Mode', r.mode], ['Requests x Conc', num(p.requests)+' x '+num(p.concurrency)], ['Max tokens', num(p.max_tokens)],
    null,
    ['TTFT p50 (ms)', num((r.ttft_ms||{}).p50)], ['TPOT mean (ms/tok)', num((r.tpot_ms||{}).mean)],
    ['pp TPS mean', num((r.pp_tps||{}).mean)], ['tg TPS mean', num((r.tg_tps||{}).mean)],
    ['E2E p50 (ms)', num((r.latency_ms||{}).p50)], ['Throughput (req/s)', num(r.requests_per_sec)],
    ['Output (tok/s)', num(r.output_tokens_per_sec)], ['Peak GPU mem (MB)', num(r.peak_mem_mb)],
    ['Succeeded', (r.succeeded||0)+' / '+((r.succeeded||0)+(r.failed||0))],
    null,
    ['OS', s.os||'—'], ['Python', s.python||'—'], ['infermesh', s.infermesh||'—'],
    ['CPU', (s.cpu||'—')+' · '+num(s.cpu_cores)+' cores'], ['RAM (GB)', num(s.ram_gb)],
  ];
  const w=Math.max.apply(null, rows.filter(Boolean).map(rw=>rw[0].length));
  return rows.map(rw=> rw? (rw[0].padEnd(w)+'  '+rw[1]) : '').join('\n');
}
function bmTerminal(x){
  const p=x.params||{};
  const body=JSON.stringify({model:x.model,requests:p.requests,concurrency:p.concurrency,max_tokens:p.max_tokens,mode:p.mode,device:p.device});
  const cmd="curl -s http://HOST:PORT/api/benchmark \\\n  -H 'content-type: application/json' \\\n  -d '"+body+"'";
  const raw=JSON.stringify({params:p,system:x.system||{},result:x.result||{}},null,2);
  return '<details class="bm-term"><summary>'+T('Raw command & terminal output')+'</summary>'+
    '<div class="term-top"><button class="btn sm primary" onclick="bmCopyTerm(this)">'+T('Copy')+'</button></div>'+
    '<div class="term-h">$ '+T('command')+'</div><pre class="term">'+esc(cmd)+'</pre>'+
    '<div class="term-h">'+T('results')+'</div><pre class="term">'+esc(bmTermText(x))+'</pre>'+
    '<details class="bm-raw"><summary>'+T('raw JSON')+'</summary><pre class="term">'+esc(raw)+'</pre></details></details>';
}
function bmCopyTerm(btn){
  const det=btn.closest('details.bm-term'); if(!det) return;
  const txt=Array.prototype.map.call(det.querySelectorAll('pre.term'),p=>p.textContent).join('\n\n');
  if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(()=>toast('copied')).catch(()=>toast('copy failed'));
  else toast('clipboard unavailable');
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
      const stat=j.status==='error'?'<span class="err">error</span>':(j.status==='paused'?T('paused'):esc(j.status));
      const act=(j.status==='downloading')
        ? '<button class="btn sm dl-pause" data-repo="'+esc(j.repo_id)+'">'+T('Pause')+'</button>'
        : (((j.status==='paused')||(j.status==='error')) ? '<button class="btn sm dl-resume" data-repo="'+esc(j.repo_id)+'" data-source="'+esc(j.source||'hf')+'">'+T('Resume')+'</button>' : '');
      return '<tr><td class="mono">'+esc(j.repo_id)+'</td><td>'+stat+(j.error?' <span class="muted">'+esc(j.error)+'</span>':'')+'</td><td>'+(j.status==='done'?'100%':bar+' '+pctn+'%')+'</td><td class="num">'+fmtBytes(j.total_bytes)+'</td><td class="rowact">'+act+'<button class="btn sm dl-del" data-repo="'+esc(j.repo_id)+'">'+T('Delete')+'</button></td></tr>';
    }).join('')||'<tr><td colspan="5" class="muted">'+T('no downloads yet')+'</td></tr>';
  }catch(e){}
}
$('#dlJobs').addEventListener('click',async e=>{
  const b=e.target.closest('button[data-repo]'); if(!b) return;
  const repo=b.dataset.repo;
  try{
    if(b.classList.contains('dl-pause')){ await api('/api/hf/download/pause','POST',{repo_id:repo}); toast('paused'); }
    else if(b.classList.contains('dl-resume')){ await api('/api/hf/download','POST',{repo_id:repo, source:b.dataset.source||'hf'}); toast('resuming'); }
    else if(b.classList.contains('dl-del')){ if(!confirm(T('Delete this download and its files?'))) return; await api('/api/hf/download/delete','POST',{repo_id:repo}); toast('deleted'); }
    refreshDownloads();
  }catch(err){ $('#dl-err').textContent=String(err); }
});
let dlLoaded=false;
$('#dlBtn').onclick=runHfSearch;
$('#dlSort').onchange=runHfSearch; $('#dlTask').onchange=runHfSearch;
$('#dlSearch').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); runHfSearch(); }});
async function msDownload(){
  const id=$('#msdlId').value.trim(); if(!id) return;
  try{ await api('/api/hf/download','POST',{repo_id:id, source:'modelscope'}); toast('downloading '+id); $('#msdlId').value=''; refreshDownloads(); }
  catch(e){ $('#dl-err').textContent=String(e); }
}
$('#msdlBtn').onclick=msDownload;
$('#msdlId').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); msDownload(); }});
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
/* ================= Hardware Analysis + Compare A/B (ported from docs/design/console-redesign-v2.html; data: /api/analysis/* + /api/compare) ================= */
function niceTicks(min,max,count){count=count||5;
  if(min===max){max=min+1;}
  const span=max-min, step0=span/count, mag=Math.pow(10,Math.floor(Math.log10(step0)));
  const norm=step0/mag; const step=(norm<1.5?1:norm<3?2:norm<7?5:10)*mag;
  const lo=Math.floor(min/step)*step, hi=Math.ceil(max/step)*step;
  const ticks=[]; for(let v=lo;v<=hi+step*0.5;v+=step) ticks.push(+v.toFixed(10));
  return {lo,hi,ticks};
}
const lg10=Math.log10;
function lgX(v,mn,mx,p0,p1){return p0+(lg10(v)-lg10(mn))/(lg10(mx)-lg10(mn))*(p1-p0);}
function showTT(html,e){const el=$('#tt'); if(!el)return; el.innerHTML=html; el.classList.add('show');
  const r=el.getBoundingClientRect();
  el.style.left=Math.min(e.clientX+14,window.innerWidth-r.width-8)+'px';
  el.style.top=Math.min(e.clientY+14,window.innerHeight-r.height-8)+'px';}
function hideTT(){const el=$('#tt'); if(el)el.classList.remove('show');}
function bindTTs(scope){
 (scope||document).querySelectorAll('[data-tt]').forEach(el=>{
   el.addEventListener('mousemove',e=>showTT(decodeURIComponent(el.dataset.tt),e));
   el.addEventListener('mouseleave',hideTT);
 });
}
function chipHexes(){const cs=getComputedStyle(document.documentElement);
  return ['--c1','--c2','--c3','--c4','--c5'].map(v=>cs.getPropertyValue(v).trim()||'#FFB224');}
function fmtN(v,d){return (v==null||isNaN(v))?'—':(+v).toFixed(d==null?1:d);}
function paramsFromModel(m){ if(!m)return null; const mm=String(m).match(/(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z0-9])/); return mm?parseFloat(mm[1])*1e9:null; }
const BPP_UI={fp16:2,bf16:2,int8:1,'8bit':1,int4:.5,'4bit':.5,fp32:4};

/* roofline: registry roofs + this chip's measured decode/prefill points */
function rooflineSVG(sel,ref){
 const W=920,H=430,L=70,R=26,PT=26,PB=52,mnx=.5,mxx=8192,mny=.5,mxy=512;
 const X=v=>lgX(Math.min(Math.max(v,mnx),mxx),mnx,mxx,L,W-R),
       Y=v=>H-PB-(lg10(Math.min(Math.max(v,mny),mxy))-lg10(mny))/(lg10(mxy)-lg10(mny))*(H-PT-PB);
 const roof=(bw,tf)=>{const ridge=tf*1000/bw;
   return 'M'+X(mnx)+' '+Y(bw*mnx/1000)+' L '+X(ridge)+' '+Y(tf)+' L '+X(mxx)+' '+Y(tf);};
 let g='';
 for(const e of [1,10,100]){for(let m=1;m<10;m++){const v=e*m;if(v<mny||v>mxy)continue;
   g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="${m===1?1:.4}" opacity="${m===1?.8:.35}"/>`;
   if(m===1)g+=`<text x="${L-8}" y="${Y(v)+4}" text-anchor="end" class="axis">${v}</text>`;}}
 for(const e of [1,10,100,1000]){for(let m=1;m<10;m++){const v=e*m;if(v<mnx||v>mxx)continue;
   g+=`<line y1="${PT}" y2="${H-PB}" x1="${X(v)}" x2="${X(v)}" stroke="var(--line)" stroke-width="${m===1?1:.4}" opacity="${m===1?.8:.35}"/>`;
   if(m===1)g+=`<text x="${X(v)}" y="${H-PB+18}" text-anchor="middle" class="axis">${v>=1000?(v/1000)+'k':v}</text>`;}}
 if(ref&&ref.spec)g+=`<path d="${roof(ref.spec.peak_bw_gbps,ref.spec.peak_tflops_fp16)}" fill="none" stroke="${ref.hex}" stroke-width="1.4" stroke-dasharray="5 5" opacity=".45"/>`;
 if(sel.spec)g+=`<path d="${roof(sel.spec.peak_bw_gbps,sel.spec.peak_tflops_fp16)}" fill="none" stroke="${sel.hex}" stroke-width="2.4"/>`;
 let pts='';
 const row=sel.row, params=sel.params;
 if(row&&params){
  const bpp=BPP_UI[String(row.quant||'fp16').toLowerCase()]||2;
  if(row.tg_tps!=null){
   const ix=2/bpp, perf=2*params*row.tg_tps/1e12;
   pts+=`<circle cx="${X(ix)}" cy="${Y(perf)}" r="7" fill="${sel.hex}" stroke="var(--bg)" stroke-width="2" data-tt="${encodeURIComponent(`<b>decode · ${esc(row.quant||'fp16')}</b><br>${perf.toFixed(3)} TFLOP/s @ ${ix} FLOP/B${row.mbu!=null?`<br>MBU ${(row.mbu*100).toFixed(1)}%`:''}`)}"/>`;
   pts+=`<text x="${X(ix)}" y="${Y(perf)-12}" text-anchor="middle" class="axis" fill="${sel.hex}">${esc(row.quant||'fp16')}</text>`;
  }
  if(row.pp_tps!=null){
   const ixp=2048*2/bpp, perfp=2*params*row.pp_tps/1e12;
   pts+=`<rect x="${X(ixp)-6.5}" y="${Y(perfp)-6.5}" width="13" height="13" rx="2.5" fill="${sel.hex}" stroke="var(--bg)" stroke-width="2" data-tt="${encodeURIComponent(`<b>prefill</b><br>${perfp.toFixed(2)} TFLOP/s${row.mfu!=null?`<br>MFU ${(row.mfu*100).toFixed(1)}%`:''}`)}"/>`;
   pts+=`<text x="${X(ixp)}" y="${Y(perfp)-13}" text-anchor="middle" class="axis" fill="${sel.hex}">prefill</text>`;
  }
 }
 return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">
  <text x="${L-46}" y="${PT-8}" class="axis">TFLOP/s</text>
  <text x="${W-R}" y="${H-8}" text-anchor="end" class="axis">FLOP/byte (log)</text>${g}${pts}</svg>`;
}

function frontierSVG(list,slo){
 const W=920,H=400,L=64,R=24,PT=24,PB=50;
 let mxThr=0; list.forEach(s=>(s.points||[]).forEach(p=>{if(p.throughput!=null)mxThr=Math.max(mxThr,p.throughput);}));
 if(!mxThr)mxThr=1;
 const mny=.08,mxy=60;
 const X=v=>L+v/(mxThr*1.08)*(W-L-R),
       Y=v=>H-PB-(lg10(Math.min(Math.max(v,mny),mxy))-lg10(mny))/(lg10(mxy)-lg10(mny))*(H-PT-PB);
 let g='';
 for(const v of [0.1,0.5,1,2,5,10,30]){g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width=".6" opacity=".5"/><text x="${L-8}" y="${Y(v)+4}" text-anchor="end" class="axis">${v}</text>`;}
 const xt=niceTicks(0,mxThr*1.08,6).ticks;
 for(const v of xt){if(!v)continue;g+=`<line y1="${PT}" y2="${H-PB}" x1="${X(v)}" x2="${X(v)}" stroke="var(--line)" stroke-width=".6" opacity=".5"/><text x="${X(v)}" y="${H-PB+18}" text-anchor="middle" class="axis">${v}</text>`;}
 g+=`<line x1="${L}" x2="${W-R}" y1="${Y(slo)}" y2="${Y(slo)}" stroke="var(--warn)" stroke-width="1.6" stroke-dasharray="7 5"/><text x="${W-R}" y="${Y(slo)-6}" text-anchor="end" class="axis" fill="var(--warn)">SLO p99 ≤ ${slo}s</text>`;
 for(const s of list){
  const F=(s.points||[]).filter(p=>p.p99_ttft_s!=null&&p.throughput!=null);
  if(!F.length)continue;
  g+=`<path d="M ${F.map(p=>X(p.throughput)+' '+Y(p.p99_ttft_s)).join(' L ')}" fill="none" stroke="${s.hex}" stroke-width="2.2" opacity=".9"/>`;
  for(const p of F){const knee=!!s.goodput&&p.concurrency===s.goodput_concurrency;
   g+=`<circle cx="${X(p.throughput)}" cy="${Y(p.p99_ttft_s)}" r="${knee?7:4.5}" fill="${knee?'var(--bg)':s.hex}" stroke="${s.hex}" stroke-width="${knee?3:0}" data-tt="${encodeURIComponent(`<b>${esc(s.chip)}</b> · c=${p.concurrency}<br>${fmtN(p.throughput,1)} tok/s · p99 TTFT ${fmtN(p.p99_ttft_s,2)}s${knee?'<br><b>goodput point</b>':''}`)}"/>`;}
 }
 return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">
  <text x="${L-40}" y="${PT-6}" class="axis">p99 TTFT s (log)</text>
  <text x="${W-R}" y="${H-6}" text-anchor="end" class="axis">tok/s</text>${g}</svg>`;
}

function scalingSVG(points,hex){
 const W=920,H=380,L=64,R=24,PT=24,PB=48;
 const usable=points.filter(p=>p.speedup!=null);
 const mx=Math.max(2,...points.map(p=>p.device_count));
 const mxsp=Math.max(2,...usable.map(p=>p.speedup),Math.min(mx,8));
 const X=v=>L+(v-1)/((mx-1)||1)*(W-L-R), Y=v=>H-PB-(v/(mxsp*1.05))*(H-PT-PB);
 let g=`<path d="M ${X(1)} ${Y(1)} L ${X(Math.min(mx,mxsp))} ${Y(Math.min(mx,mxsp))}" stroke="var(--dim)" stroke-width="1.4" stroke-dasharray="6 5" fill="none"/>`;
 for(const v of niceTicks(0,mxsp,5).ticks){ if(v<=0)continue;
  g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width=".6" opacity=".5"/><text x="${L-8}" y="${Y(v)+4}" text-anchor="end" class="axis">${v}×</text>`;}
 for(const p of points){ g+=`<text x="${X(p.device_count)}" y="${H-PB+18}" text-anchor="middle" class="axis">${p.device_count}</text>`;}
 if(usable.length){
  g+=`<path d="M ${usable.map(p=>X(p.device_count)+' '+Y(p.speedup)).join(' L ')}" fill="none" stroke="${hex}" stroke-width="2.2"/>`;
  for(const p of usable){ g+=`<circle cx="${X(p.device_count)}" cy="${Y(p.speedup)}" r="5" fill="${hex}" data-tt="${encodeURIComponent(`<b>${p.device_count}×</b><br>speedup ${p.speedup.toFixed(2)}× · efficiency ${(p.efficiency*100).toFixed(0)}%<br>n=${p.n_runs}`)}"/>`;
   if(p.device_count>1)g+=`<text x="${X(p.device_count)}" y="${Y(p.speedup)-11}" text-anchor="middle" class="axis" fill="${hex}">${(p.efficiency*100).toFixed(0)}%</text>`;}
 }
 return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">
  <text x="${L-40}" y="${PT-6}" class="axis">speedup</text>
  <text x="${W-R}" y="${H-6}" text-anchor="end" class="axis">devices</text>${g}</svg>`;
}

function timelineSVG(points,hex){
 const W=920,H=300,L=64,R=24,PT=26,PB=46;
 const vals=points.map(p=>p.median);
 const mn=Math.min(...vals)*0.9, mx=(Math.max(...vals)*1.08)||1;
 const X=i=>L+(points.length===1?((W-L-R)/2):i/(points.length-1)*(W-L-R)),
       Y=v=>H-PB-(v-mn)/((mx-mn)||1)*(H-PT-PB);
 let g='';
 for(const v of niceTicks(mn,mx,5).ticks){g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width=".6" opacity=".5"/><text x="${L-8}" y="${Y(v)+4}" text-anchor="end" class="axis">${v}</text>`;}
 g+=`<path d="M ${points.map((p,i)=>X(i)+' '+Y(p.median)).join(' L ')}" fill="none" stroke="${hex}" stroke-width="2.4"/>`;
 points.forEach((p,i)=>{
  g+=`<circle cx="${X(i)}" cy="${Y(p.median)}" r="${p.regression?7:5}" fill="${p.regression?'var(--err)':hex}" data-tt="${encodeURIComponent(`<b>${esc(p.driver_version)}</b><br>median ${fmtN(p.median,1)}${p.delta_pct!=null?`<br>Δ ${(p.delta_pct>=0?'+':'')+p.delta_pct.toFixed(1)}%`:''}${p.regression?'<br><b>regression</b>':''}`)}"/>`;
  g+=`<text x="${X(i)}" y="${H-PB+18}" text-anchor="middle" class="axis">${esc(p.driver_version)}</text>`;
  if(p.regression)g+=`<text x="${X(i)}" y="${Y(p.median)-13}" text-anchor="middle" class="axis" fill="var(--err)">▼ ${p.delta_pct.toFixed(1)}%</text>`;
 });
 return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">${g}</svg>`;
}

function pctBarsSVG(points,hex){
 const W=440,H=150,L=8,PB=20;
 const vals=[]; points.forEach(p=>{const q=(p.percentiles||{}).ttft||{}; if(q.p99!=null)vals.push(q.p99);});
 const mx=Math.max(1,...vals);
 const bw=(W-L-8)/Math.max(points.length,1);
 let g='';
 points.forEach((p,i)=>{const q=(p.percentiles||{}).ttft||{}; if(q.p50==null)return;
   const x=L+i*bw, h99=(q.p99||0)/mx*(H-PB-16), h50=(q.p50||0)/mx*(H-PB-16);
   g+=`<rect x="${x+3}" y="${H-PB-h99}" width="${Math.max(4,bw*0.5-6)}" height="${h99}" rx="2" fill="${hex}" opacity=".35" data-tt="${encodeURIComponent(`<b>c=${p.concurrency}</b><br>TTFT p99 ${fmtN(q.p99,1)} ms`)}"/>`;
   g+=`<rect x="${x+bw*0.5}" y="${H-PB-h50}" width="${Math.max(4,bw*0.45-6)}" height="${h50}" rx="2" fill="${hex}" data-tt="${encodeURIComponent(`<b>c=${p.concurrency}</b><br>TTFT p50 ${fmtN(q.p50,1)} ms`)}"/>`;
   g+=`<text x="${x+bw/2}" y="${H-6}" text-anchor="middle" class="axis">c=${p.concurrency}</text>`;});
 g+=`<text x="2" y="12" class="axis">${esc(T('TTFT p50 vs p99 (ms)'))}</text>`;
 return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">${g}</svg>`;
}

/* ---- analysis state + loaders ---- */
let AN={tab:'eff',chip:null,dist:null,slo:null,model:'',quant:''};
try{Object.assign(AN,JSON.parse(localStorage.getItem('infermesh-an')||'{}'));}catch(e){}
function anSave(){try{localStorage.setItem('infermesh-an',JSON.stringify({tab:AN.tab,slo:AN.slo,model:AN.model,quant:AN.quant}));}catch(e){}}
let anData=null;
async function loadAnalysis(){
  const root=$('#anRoot'); if(!root)return;
  root.innerHTML='<div class="hint">'+T('loading…')+'</div>';
  try{
    const both=await Promise.all([api('/api/analysis/efficiency'),api('/api/specs')]);
    let frontier=null,scaling=null;
    if(AN.tab==='cap'||AN.tab==='dist') frontier=await api('/api/analysis/frontier'+(AN.slo?('?slo='+AN.slo):''));
    if(AN.tab==='scale') scaling=await api('/api/analysis/scaling?model='+encodeURIComponent(AN.model||'')+'&quant='+encodeURIComponent(AN.quant||''));
    anData={eff:both[0].chips||[],specs:both[1].specs||{},frontier:frontier,scaling:scaling};
    renderAnalysis();
  }catch(e){root.innerHTML='<div class="hint">'+esc(String(e))+'</div>';}
}
function anChips(){const hex=chipHexes();return anData.eff.map((c,i)=>Object.assign({},c,{hex:hex[i%5]}));}
function chipPickRow(list,cur,attr){
  return `<div class="anrow">${list.map(c=>`<button class="fchip ${c.chip===cur?'on':''}" data-${attr}="${esc(c.chip)}"><span class="sw" style="background:${c.hex}"></span>${esc(c.chip)}</button>`).join('')}</div>`;
}
function renderAnalysis(){
  const root=$('#anRoot');
  const tabs=[['eff','Efficiency'],['cap','Capacity'],['scale','Scaling'],['dist','Distributions']];
  let body='';
  if(AN.tab==='eff')body=anEffT(); else if(AN.tab==='cap')body=anCapT(); else if(AN.tab==='scale')body=anScaleT(); else body=anDistT();
  root.innerHTML=`<div class="anrow"><div class="seg">${tabs.map(([k,lb])=>`<button class="seg-btn ${AN.tab===k?'active':''}" data-antab="${k}">${esc(T(lb))}</button>`).join('')}</div></div>`+body;
  root.querySelectorAll('[data-antab]').forEach(b=>b.onclick=()=>{AN.tab=b.dataset.antab;anSave();loadAnalysis();});
  root.querySelectorAll('[data-anchip]').forEach(b=>b.onclick=()=>{AN.chip=b.dataset.anchip;renderAnalysis();});
  root.querySelectorAll('[data-andist]').forEach(b=>b.onclick=()=>{AN.dist=b.dataset.andist;renderAnalysis();});
  root.querySelectorAll('[data-anslo]').forEach(b=>b.onclick=()=>{AN.slo=+b.dataset.anslo;anSave();loadAnalysis();});
  const mf=root.querySelector('#anModelF'), qf=root.querySelector('#anQuantF');
  if(mf)mf.onchange=()=>{AN.model=mf.value;anSave();loadAnalysis();};
  if(qf)qf.onchange=()=>{AN.quant=qf.value;anSave();loadAnalysis();};
  bindTTs(root);
}
function anEffT(){
  const list=anChips();
  if(!list.length)return `<div class="card"><div class="hint">${esc(T('no runs in the community store yet — run a benchmark first'))}</div></div>`;
  if(!AN.chip||!list.some(c=>c.chip===AN.chip))AN.chip=list[0].chip;
  const sel=list.find(c=>c.chip===AN.chip);
  const spec=sel.spec_key?anData.specs[sel.spec_key]:null;
  const refc=list.find(c=>c.chip!==sel.chip&&c.spec_key&&anData.specs[c.spec_key]);
  const params=paramsFromModel(sel.model);
  const kpi=(lbl,val,unit)=>`<div class="card kpi"><div class="k">${esc(T(lbl))}</div><div class="ro">${val}<small>${unit}</small></div></div>`;
  const rows=list.map(x=>`<tr><td><span class="antag" style="color:${x.hex}"><span class="sw" style="background:${x.hex}"></span>${esc(x.chip)}</span></td><td class="mono">${esc(x.quant||'—')}</td>
    <td class="num">${x.mbu!=null?(x.mbu*100).toFixed(1)+'%':'—'}</td><td class="num">${x.mfu!=null?(x.mfu*100).toFixed(1)+'%':'—'}</td>
    <td class="num">${x.tok_j!=null?x.tok_j.toFixed(3)+(x.tok_j_basis==='tdp'?' <span class="muted">(TDP)</span>':''):'—'}</td>
    <td class="num" style="color:${(x.soak_delta_pct!=null&&x.soak_delta_pct<=-5)?'var(--err)':'var(--muted)'}">${x.soak_delta_pct!=null?x.soak_delta_pct.toFixed(1)+'%':'—'}</td></tr>`).join('');
  return chipPickRow(list,AN.chip,'anchip')+
  `<div class="angrid">
    ${kpi('decode MBU',sel.mbu!=null?(sel.mbu*100).toFixed(1):'—','% · '+esc(sel.quant||''))}
    ${kpi('prefill MFU',sel.mfu!=null?(sel.mfu*100).toFixed(1):'—','%')}
    ${kpi('tokens per joule',sel.tok_j!=null?sel.tok_j.toFixed(3):'—',sel.tok_j_basis==='tdp'?'tok/J (TDP)':'tok/J')}
    ${kpi('runs recorded',sel.n_runs,'')}
  </div>
  <div class="panel" style="padding:16px;margin-bottom:14px">
    <div class="eyebrow">${esc(T('Roofline — where each workload sits'))} · ${esc(sel.chip)}${spec?` · ${spec.peak_bw_gbps} GB/s · ${spec.peak_tflops_fp16} TFLOPS fp16`:''}</div>
    ${(spec&&params)?`<div class="plotwrap">${rooflineSVG({spec:spec,hex:sel.hex,row:sel,params:params},refc?{spec:anData.specs[refc.spec_key],hex:refc.hex}:null)}</div>
    <div class="hint">${esc(T('Solid roof = selected chip. Dashed = reference. Circle = decode at its quant, square = prefill. Hover for MBU/MFU.'))}</div>`
    :`<div class="hint">${esc(T(spec?'model name carries no parameter count — MBU/MFU need it':'no spec for this chip — add peak BW / TFLOPS / TDP via the chip-spec registry'))}</div>`}
  </div>
  <div class="panel" style="padding:16px;margin-bottom:14px">
    <div class="eyebrow">${esc(T('Efficiency across chips'))}</div>
    <table><thead><tr><th>${esc(T('chip'))}</th><th>${esc(T('quant'))}</th><th>${esc(T('MBU decode'))}</th><th>${esc(T('MFU prefill'))}</th><th>tok/J</th><th>${esc(T('soak Δ'))}</th></tr></thead><tbody>${rows}</tbody></table>
  </div>
  <div class="hint">${esc(T('Spec-sheet denominators — edit per-chip peak BW / TFLOPS / TDP via the chip-spec registry; MBU & MFU derive from them plus measured throughput. No hardware counters required.'))}</div>`;
}
function anCapT(){
  const fr=(anData.frontier&&anData.frontier.series)||[];
  const slo=anData.frontier?anData.frontier.slo_p99_ttft_s:2;
  const hex=chipHexes();
  const list=fr.map((s,i)=>Object.assign({},s,{hex:hex[i%5]}));
  const segs=`<div class="seg">${[1,2,5,10].map(v=>`<button class="seg-btn ${slo===v?'active':''}" data-anslo="${v}">p99 ≤ ${v}s</button>`).join('')}</div>`;
  const head=`<div class="anrow"><span class="muted">${esc(T('SLO p99 TTFT'))}</span>${segs}</div>`;
  if(!list.length)return head+`<div class="card"><div class="hint">${esc(T('no sweep data yet — run a concurrency-sweep benchmark to draw the frontier'))}</div></div>`;
  const rows=list.map(s=>{
    const tag=`<span class="antag" style="color:${s.hex}"><span class="sw" style="background:${s.hex}"></span>${esc(s.chip)}</span>`;
    if(!s.goodput)return `<tr><td>${tag}</td><td class="num muted" colspan="3">${esc(T('does not meet SLO at any concurrency (prefill-bound)'))}</td></tr>`;
    const pt=s.points.find(p=>p.concurrency===s.goodput_concurrency)||{};
    return `<tr><td>${tag}</td><td class="num">${fmtN(s.goodput,1)}</td><td class="num">${s.goodput_concurrency}</td><td class="num">${fmtN(pt.p99_ttft_s,2)} s</td></tr>`;}).join('');
  return head+
  `<div class="panel" style="padding:16px;margin-bottom:14px">
    <div class="eyebrow">${esc(T('Throughput–latency frontier'))}</div>
    <div class="plotwrap">${frontierSVG(list,slo)}</div>
    <div class="hint">${esc(T('Ring = goodput point: highest throughput still meeting the SLO. Hover points for concurrency.'))}</div>
  </div>
  <div class="panel" style="padding:16px">
    <div class="eyebrow">${esc(T('Goodput @ SLO'))} · p99 TTFT ≤ ${slo}s</div>
    <table><thead><tr><th>${esc(T('chip'))}</th><th>goodput tok/s</th><th>${esc(T('max conc'))}</th><th>${esc(T('p99 at that point'))}</th></tr></thead><tbody>${rows}</tbody></table>
  </div>`;
}
function anScaleT(){
  const sc=anData.scaling||{points:[]};
  const hex=chipHexes()[0];
  const pts=sc.points||[];
  const filters=`<div class="anrow">
    <div class="bm-field"><label>${esc(T('model filter'))}</label><input id="anModelF" value="${esc(AN.model||'')}" placeholder="Qwen…" style="width:190px"/></div>
    <div class="bm-field"><label>${esc(T('quant filter'))}</label><input id="anQuantF" value="${esc(AN.quant||'')}" placeholder="fp16" style="width:100px"/></div>
  </div>`;
  if(!pts.length)return filters+`<div class="card"><div class="hint">${esc(T('no runs match — record 1-device and multi-device runs to see scaling'))}</div></div>`;
  const rows=pts.map(p=>`<tr><td class="num">${p.device_count}×</td><td class="num">${fmtN(p.median_throughput,1)}</td><td class="num">${p.speedup!=null?p.speedup.toFixed(2)+'×':'—'}</td><td class="num">${p.efficiency!=null?(p.efficiency*100).toFixed(0)+'%':'—'}</td><td class="num">${p.n_runs}</td></tr>`).join('');
  return filters+
  `<div class="panel" style="padding:16px;margin-bottom:14px">
    <div class="eyebrow">${esc(T('Multi-GPU scaling'))}${sc.model?` · ${esc(sc.model)}`:''}${sc.quant?` · ${esc(sc.quant)}`:''}</div>
    <div class="plotwrap">${scalingSVG(pts,hex)}</div>
    <div class="hint">${esc(T('Ideal = linear. Labels show parallel efficiency. Baseline: median of 1-device runs.'))}</div>
  </div>
  <div class="panel" style="padding:16px">
    <table><thead><tr><th>${esc(T('device count'))}</th><th>${esc(T('median throughput'))}</th><th>${esc(T('speedup'))}</th><th>${esc(T('efficiency'))}</th><th>${esc(T('runs'))}</th></tr></thead><tbody>${rows}</tbody></table>
  </div>`;
}
function anDistT(){
  const fr=(anData.frontier&&anData.frontier.series)||[];
  const hex=chipHexes();
  const list=fr.map((s,i)=>Object.assign({},s,{hex:hex[i%5]}));
  if(!list.length)return `<div class="card"><div class="hint">${esc(T('no sweep data yet — run a concurrency-sweep benchmark to draw the frontier'))}</div></div>`;
  if(!AN.dist||!list.some(c=>c.chip===AN.dist))AN.dist=list[0].chip;
  const sel=list.find(c=>c.chip===AN.dist);
  const row=p=>{const q=(p.percentiles||{}), tt=q.ttft||{}, it=q.itl||{};
    return `<tr><td class="num">c=${p.concurrency}</td>
    <td class="num">${fmtN(tt.p50,0)}</td><td class="num">${fmtN(tt.p90,0)}</td><td class="num">${fmtN(tt.p99,0)}</td><td class="num">${fmtN(tt.p999,0)}</td>
    <td class="num">${fmtN(it.p50,1)}</td><td class="num">${fmtN(it.p99,1)}</td>
    <td class="num">${p.cv_itl!=null?(p.cv_itl*100).toFixed(1)+'%':'—'}</td>
    <td class="num">${p.n_requests!=null?p.n_requests:'—'}</td></tr>`;};
  const last=sel.points[sel.points.length-1]||{};
  const lt=((last.percentiles||{}).ttft)||{};
  const tail=(lt.p99&&lt.p50)?(lt.p99/lt.p50):null;
  return chipPickRow(list,AN.dist,'andist')+
  `<div class="angrid2">
    <div class="panel" style="padding:16px">
      <div class="eyebrow">${esc(T('Latency distributions'))} · ${esc(sel.chip)}</div>
      <table><thead><tr><th></th><th>TTFT p50</th><th>p90</th><th>p99</th><th>p99.9</th><th>ITL p50</th><th>ITL p99</th><th>CV</th><th>n</th></tr></thead>
      <tbody>${sel.points.map(row).join('')}</tbody></table>
      <div class="hint">${esc(T('per level: TTFT / ITL percentiles (ms) from the latest sweep'))}</div>
    </div>
    <div class="panel" style="padding:16px">
      <div class="eyebrow">TTFT · ${esc(sel.chip)}</div>
      <div class="plotwrap" style="padding:10px 12px">${pctBarsSVG(sel.points,sel.hex)}</div>
      <div class="angrid" style="margin-top:12px;margin-bottom:0">
        <div class="card kpi"><div class="k">${esc(T('tail ratio p99/p50'))}</div><div class="ro">${tail?tail.toFixed(2):'—'}<small>×</small></div></div>
        <div class="card kpi"><div class="k">ITL CV</div><div class="ro">${last.cv_itl!=null?(last.cv_itl*100).toFixed(1):'—'}<small>%</small></div></div>
      </div>
    </div>
  </div>
  <div class="hint">${esc(T('Medians lie. Tail ratio and CV are the first fingerprints of scheduler stalls, allocator pauses and kernel-launch gaps.'))}</div>`;
}

/* ---- compare A/B ---- */
let CP={a:null,sel:[],runs:[]};
const CP_MAX=6;   // comparison-column cap — keeps the delta table readable
async function loadCompare(){
  const root=$('#cpRoot'); if(!root)return;
  root.innerHTML='<div class="hint">'+T('loading…')+'</div>';
  try{
    const d=await api('/api/community/runs?sort=recent&limit=100');
    CP.runs=d.runs||[];
    if(!CP.runs.length){root.innerHTML='<div class="card"><div class="hint">'+esc(T('no runs in the community store yet — run a benchmark first'))+'</div></div>';return;}
    const ids=new Set(CP.runs.map(r=>r.id));
    if(!CP.a||!ids.has(CP.a))CP.a=CP.runs[Math.min(1,CP.runs.length-1)].id;
    CP.sel=(CP.sel||[]).filter(id=>ids.has(id)&&id!==CP.a).slice(0,CP_MAX);
    if(!CP.sel.length){const first=CP.runs.find(r=>r.id!==CP.a)||CP.runs[0];CP.sel=[first.id];}
    const cmps=await Promise.all(CP.sel.map(id=>api('/api/compare?a='+encodeURIComponent(CP.a)+'&b='+encodeURIComponent(id))));
    let tl=null;
    try{ const chip=cmps[0]&&cmps[0].a?cmps[0].a.chip:null;
      if(chip){const t2=await api('/api/analysis/timeline?chip='+encodeURIComponent(chip)+'&metric=tg'); if(t2.points&&t2.points.length>1)tl=t2;} }catch(e){}
    renderCompare(cmps,tl);
  }catch(e){root.innerHTML='<div class="hint">'+esc(String(e))+'</div>';}
}
function runLabel(r){const d=new Date((r.created_at||0)*1000);
  return (r.chip||'—')+' · '+(r.model||'—')+' · '+(r.quant||'—')+' · c'+(r.batch_size||'—')+' · '+d.toISOString().slice(0,16).replace('T',' ');}
function renderCompare(cmps,tl){
  const root=$('#cpRoot');
  const base=cmps[0].a;
  const selHtml=(side,cur)=>`<select class="mono" style="max-width:100%" data-cpsel="${side}">${CP.runs.map(r=>`<option value="${esc(r.id)}" ${r.id===cur?'selected':''}>${esc(runLabel(r))}</option>`).join('')}</select>`;
  const ORDER=[['tg_tps','tg (decode)','tok/s',1],['pp_tps','pp (prefill)','tok/s',0],['total_throughput','total throughput','tok/s',1],['ttft_ms','TTFT p50','ms',0],['tpot_ms','TPOT','ms',1],['e2e_latency_s','E2E p50','s',2],['peak_mem_gb','peak mem','GB',2],['power_avg_w','power','W',0],['energy_j','energy','J',0],['cv_itl','ITL CV','',3]];
  const counts=cmps.map(c=>{let reg=0,imp=0;ORDER.forEach(p=>{const e=c.deltas[p[0]];if(!e)return;if(e.verdict==='worse')reg++;if(e.verdict==='better')imp++;});return {reg:reg,imp:imp};});
  const cnt=i=>{const c=counts[i];
    if(!c.reg&&!c.imp)return `<span style="color:var(--muted);font-weight:400">${esc(T('within noise'))}</span>`;
    return (c.reg?`<span style="color:var(--err)">${c.reg}↓</span>`:'')+((c.reg&&c.imp)?' ':'')+(c.imp?`<span style="color:var(--ok)">${c.imp}↑</span>`:'');};
  const rows=ORDER.map(pair=>{
    const k=pair[0],lb=pair[1],un=pair[2],dd=pair[3];
    const es=cmps.map(c=>c.deltas[k]);
    if(es.every(e=>!e||(e.a==null&&e.b==null)))return '';
    const aE=es.find(e=>e&&e.a!=null);
    const cells=es.map(e=>{
      if(!e||e.b==null)return '<td class="num">—</td><td class="num">—</td>';
      const col=e.verdict==='worse'?'var(--err)':e.verdict==='better'?'var(--ok)':'var(--muted)';
      return `<td class="num">${(+e.b).toFixed(dd)}</td><td class="num" style="color:${col};font-weight:650">${e.delta_pct==null?'—':(e.delta_pct>=0?'+':'')+e.delta_pct.toFixed(1)+'%'}</td>`;
    }).join('');
    return `<tr><td>${esc(T(lb))}</td><td class="mono muted">${un}</td><td class="num">${aE&&aE.a!=null?(+aE.a).toFixed(dd):'—'}</td>${cells}</tr>`;}).join('');
  const heads=cmps.map((c,i)=>`<th>B${cmps.length>1?i+1:''} · ${esc(c.b.chip||'')} ${esc(c.b.driver_version||'')} ${cnt(i)}</th><th>Δ%</th>`).join('');
  const corr=r=>{if(!r||!r.correctness||r.correctness.greedy_match==null)return '';
    const c=r.correctness, col=c.grade==='pass'?'var(--ok)':c.grade==='warn'?'var(--warn)':'var(--err)';
    return `<tr><td>${esc(r.chip||'')}</td><td class="mono">${esc(r.quant||'')}</td><td class="num">${(c.greedy_match*100).toFixed(1)}%</td><td class="num">${c.mean_kl!=null?c.mean_kl.toFixed(4):'—'}</td><td><span class="antag" style="color:${col}">${esc(String(c.grade||'—').toUpperCase())}</span></td></tr>`;};
  const corrRows=corr(base)+cmps.map(c=>corr(c.b)).join('');
  const hexes=chipHexes();
  const selList=CP.sel.map((id,i)=>`<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><span class="mono muted" style="font-size:11px">B${i+1}</span><div style="flex:1">${selHtml(String(i),id)}</div><button class="btn sm" data-cprm="${i}" title="${esc(T('remove'))}" ${CP.sel.length<=1?'disabled':''}>✕</button></div>`).join('');
  root.innerHTML=`
  <div class="angrid2">
   <div class="panel" style="padding:14px"><div class="eyebrow">${esc(T('Baseline'))} A</div>${selHtml('a',CP.a)}</div>
   <div class="panel" style="padding:14px"><div class="eyebrow">${esc(T('Comparisons'))}</div>${selList}
    <button class="btn sm" data-cpadd ${CP.sel.length>=CP_MAX?'disabled':''}>${esc(T('+ Add comparison'))}</button></div>
  </div>
  <div class="panel" style="padding:16px;margin-bottom:14px">
   <div class="eyebrow">${esc(T('metric'))} · ${esc(T('vs baseline A'))}</div>
   <div style="overflow-x:auto"><table><thead><tr><th>${esc(T('metric'))}</th><th></th><th>A · ${esc(base.chip||'')} ${esc(base.driver_version||'')}</th>${heads}</tr></thead><tbody>${rows}</tbody></table></div>
   <div class="hint">↓ ${esc(T('regressions'))} · ↑ ${esc(T('improvements'))} · |Δ| > ${cmps[0].threshold_pct}% ${esc(T('is colored; smaller moves are treated as run-to-run noise. The threshold is configurable in Settings.'))}</div>
  </div>
  ${tl?`<div class="panel" style="padding:16px;margin-bottom:14px">
   <div class="eyebrow">${esc(T('Driver / SDK timeline'))} · ${esc(base.chip||'')}</div>
   <div class="plotwrap">${timelineSVG(tl.points,hexes[0])}</div>
   <div class="hint">${esc(T('Red = regression vs previous version. This is why driver fingerprints belong in the benchmark schema.'))}</div>
  </div>`:''}
  ${corrRows?`<div class="panel" style="padding:16px">
   <div class="eyebrow">${esc(T('Numerical correctness vs fp16 reference'))}</div>
   <table><thead><tr><th>${esc(T('chip'))}</th><th>${esc(T('quant'))}</th><th>${esc(T('greedy match'))}</th><th>${esc(T('mean logit KL'))}</th><th>${esc(T('status'))}</th></tr></thead><tbody>${corrRows}</tbody></table>
  </div>`:''}`;
  root.querySelectorAll('[data-cpsel]').forEach(s=>s.onchange=()=>{const k=s.dataset.cpsel; if(k==='a'){CP.a=s.value;}else{CP.sel[+k]=s.value;} loadCompare();});
  root.querySelectorAll('[data-cprm]').forEach(b=>b.onclick=()=>{CP.sel.splice(+b.dataset.cprm,1);loadCompare();});
  const add=root.querySelector('[data-cpadd]');
  if(add)add.onclick=()=>{const used=new Set([CP.a].concat(CP.sel));const nxt=CP.runs.find(r=>!used.has(r.id));CP.sel.push((nxt||CP.runs[0]).id);loadCompare();};
  bindTTs(root);
}

/* v2 i18n additions (analysis + compare); nav-level keys live in the main dict */
Object.assign(I18N,{
"Efficiency":"效率","Capacity":"容量","Scaling":"扩展","Distributions":"分布",
"decode MBU":"decode 带宽利用率 MBU","prefill MFU":"prefill 算力利用率 MFU",
"tokens per joule":"每焦耳 token 数","runs recorded":"已记录运行数",
"Roofline — where each workload sits":"Roofline — 每个负载卡在哪里",
"Solid roof = selected chip. Dashed = reference. Circle = decode at its quant, square = prefill. Hover for MBU/MFU.":"实线屋顶 = 当前芯片，虚线 = 参照。圆点 = 该量化档 decode，方块 = prefill。悬停查看 MBU/MFU。",
"model name carries no parameter count — MBU/MFU need it":"模型名中没有参数量（如 7B）—— MBU/MFU 需要它才能推导",
"no spec for this chip — add peak BW / TFLOPS / TDP via the chip-spec registry":"该芯片没有规格登记 —— 请在芯片规格注册表中补充峰值带宽 / TFLOPS / TDP",
"Efficiency across chips":"各芯片效率对比","chip":"芯片","quant":"量化",
"MBU decode":"MBU · decode","MFU prefill":"MFU · prefill","soak Δ":"持续负载 Δ",
"Spec-sheet denominators — edit per-chip peak BW / TFLOPS / TDP via the chip-spec registry; MBU & MFU derive from them plus measured throughput. No hardware counters required.":"分母来自规格登记 —— 各芯片峰值带宽 / TFLOPS / TDP 可在芯片规格注册表中修改；MBU 与 MFU 由它们加实测吞吐推导，第一版无需任何硬件计数器。",
"SLO p99 TTFT":"SLO p99 TTFT",
"no sweep data yet — run a concurrency-sweep benchmark to draw the frontier":"暂无扫描数据 —— 先运行一次并发扫描基准即可绘制前沿",
"does not meet SLO at any concurrency (prefill-bound)":"任何并发下均无法满足该 SLO（受限于 prefill）",
"Throughput–latency frontier":"吞吐–延迟前沿",
"Ring = goodput point: highest throughput still meeting the SLO. Hover points for concurrency.":"圆环 = goodput 点：满足 SLO 的最高吞吐。悬停各点查看并发数。",
"Goodput @ SLO":"SLO 下的 goodput","max conc":"最大并发","p99 at that point":"该点 p99",
"Multi-GPU scaling":"多卡扩展",
"Ideal = linear. Labels show parallel efficiency. Baseline: median of 1-device runs.":"虚线为理想线性，标签为并行效率。基线：单卡运行的中位数。",
"model filter":"模型筛选","quant filter":"量化筛选",
"no runs match — record 1-device and multi-device runs to see scaling":"没有匹配的运行 —— 记录单卡与多卡运行后即可查看扩展效率",
"device count":"卡数","median throughput":"中位吞吐","speedup":"加速比","efficiency":"并行效率","runs":"运行数",
"Latency distributions":"延迟分布","metric":"指标",
"per level: TTFT / ITL percentiles (ms) from the latest sweep":"每个并发级：最近一次扫描的 TTFT / ITL 百分位（ms）",
"tail ratio p99/p50":"尾部比 p99/p50",
"TTFT p50 vs p99 (ms)":"TTFT p50 与 p99（ms）",
"Medians lie. Tail ratio and CV are the first fingerprints of scheduler stalls, allocator pauses and kernel-launch gaps.":"中位数会骗人。尾部比与 CV 是调度停顿、分配器暂停和 kernel 启动间隙最早的指纹。",
"Run A":"运行 A","Run B":"运行 B",
"Baseline":"基线","Comparisons":"对比对象","vs baseline A":"对比基线 A",
"tg (decode)":"tg（decode）","pp (prefill)":"pp（prefill）","total throughput":"总吞吐",
"TTFT p50":"TTFT p50","TPOT":"TPOT","E2E p50":"E2E p50","peak mem":"峰值显存","power":"功耗","energy":"能耗","ITL CV":"ITL CV",
"regressions":"项回归","improvements":"项改善","within noise":"噪声范围内",
"is colored; smaller moves are treated as run-to-run noise. The threshold is configurable in Settings.":"以上才着色，更小的波动视为运行间噪声。阈值可在设置中调整。",
"Driver / SDK timeline":"驱动 / SDK 时间线",
"Red = regression vs previous version. This is why driver fingerprints belong in the benchmark schema.":"红点 = 相对上一版本的回归。这正是基准 schema 需要驱动指纹字段的原因。",
"Numerical correctness vs fp16 reference":"数值正确性（对照 fp16 参考实现）",
"greedy match":"贪心一致率","mean logit KL":"平均 logit KL","status":"状态",
"no runs in the community store yet — run a benchmark first":"社区库还没有运行记录 —— 先跑一次基准测试",
});

applyLang((function(){try{return localStorage.getItem('infermesh-lang');}catch(e){return null;}})()||'en');
$('#langBtn').onclick=function(){applyLang(lang==='zh'?'en':'zh');};
</script>
<div class="tooltip" id="tt" role="tooltip" aria-hidden="true"></div>
</body>
</html>
"""
