"""Oversight dashboard (single self-contained page)."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Social Bridge</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#16181d;--mute:#6b7280;--line:#e3e6ea;--acc:#2563eb;--ok:#16a34a;--bad:#dc2626;--warn:#d97706;--in:#eef4ff;--out:#effaf3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaee;--mute:#9aa1ad;--line:#272b35;--acc:#60a5fa;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--in:#152033;--out:#13261b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
h1{font-size:16px;margin:0 auto 0 0}h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:18px 0 8px}
main{max-width:860px;margin:0 auto;padding:0 16px 40px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}button.ok{background:var(--ok);border-color:var(--ok);color:#fff}button.bad{color:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px}
.meta{font-size:12px;color:var(--mute);display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tag{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:99px;background:var(--line);color:var(--fg)}
textarea{width:100%;min-height:80px;font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;margin:8px 0;resize:vertical}
.row{display:flex;gap:8px;flex-wrap:wrap}.ctx{font-size:13px;border-left:3px solid var(--line);padding-left:8px;margin-top:6px;color:var(--mute);white-space:pre-wrap}
.ev{padding:8px 10px;border-radius:10px;margin-bottom:6px;white-space:pre-wrap;word-break:break-word}
.ev.incoming{background:var(--in)}.ev.sent{background:var(--out)}.ev.failed{border:1px solid var(--bad)}.ev.rejected{opacity:.6}
.plats{display:flex;flex-wrap:wrap;gap:6px}.plat{font-size:13px;padding:4px 10px;border-radius:99px;border:1px solid var(--line);background:var(--card)}
.plat.err{border-color:var(--bad)}.empty{color:var(--mute);font-size:14px}a{color:var(--acc)}
#tok{display:none}
</style></head><body>
<header><h1>Social Bridge</h1>
<span class="meta">Mode</span><button id="m-review">Review</button><button id="m-auto">Auto</button>
<button id="pause">Pause</button><button id="poll">Poll now</button></header>
<main>
<div id="tok" class="card">API token: <input id="tokin" type="password"> <button id="toksave">Save</button></div>
<h2>Platforms</h2><div id="plats" class="plats"></div>
<h2>Waiting for approval <span id="pc"></span></h2><div id="pending"></div>
<h2>Live feed</h2><div id="feed"></div>
</main>
<script>
const $=s=>document.querySelector(s);let tok='';try{tok=localStorage.getItem('sb_token')||''}catch(e){}
const H=()=>tok?{'Authorization':'Bearer '+tok,'Content-Type':'application/json'}:{'Content-Type':'application/json'};
async function api(p,body){const r=await fetch(p,{method:body?'POST':'GET',headers:H(),body:body?JSON.stringify(body):undefined});
 if(r.status===401){$('#tok').style.display='block';throw new Error('unauthorized')}return r.json()}
$('#toksave').onclick=()=>{tok=$('#tokin').value;try{localStorage.setItem('sb_token',tok)}catch(e){};$('#tok').style.display='none';load()};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const t=ts=>new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const editing=new Set();let last=null;
function pend(a){const c=a.context?`<div class="ctx">↪ ${esc(a.context.author)}: ${esc(a.context.text)}</div>`:'';
 return `<div class="card" data-id="${a.id}"><div class="meta"><span class="tag">${esc(a.platform)}</span><b>${esc(a.action)}</b>
 ${a.target?'→ '+esc(a.target):''}${a.opts&&a.opts.title?' · title: '+esc(a.opts.title):''}<span>· ${esc(a.source)} · ${t(a.created)}</span></div>${c}
 <textarea>${esc(a.text)}</textarea><div class="row"><button class="ok" data-do="approve">Send</button><button class="bad" data-do="reject">Reject</button></div></div>`}
function ev(e){if(e.kind==='incoming'){const i=e.item;return `<div class="ev incoming"><div class="meta"><span class="tag">${esc(i.platform)}</span>📥 ${esc(i.kind)} · <b>${esc(i.author)}</b> · ${t(e.ts)} · #${i.seq}${i.url?` · <a href="${esc(i.url)}" target="_blank" rel="noopener">open</a>`:''}</div>${esc(i.text)}</div>`}
 if(['sent','failed','rejected','queued'].includes(e.kind)){const a=e.action;const icon={sent:'📤',failed:'⚠️',rejected:'🗑️',queued:'📝'}[e.kind];
  const link=a.result&&a.result.url?` · <a href="${esc(a.result.url)}" target="_blank" rel="noopener">open</a>`:'';
  return `<div class="ev ${e.kind}"><div class="meta"><span class="tag">${esc(a.platform)}</span>${icon} ${e.kind} ${esc(a.action)} ${a.target?'→ '+esc(a.target):''} · ${t(e.ts)}${link}</div>${esc(a.text)}${a.error?`<div class="ctx">${esc(a.error)}</div>`:''}</div>`}
 return `<div class="ev"><div class="meta">${esc(e.kind)} ${esc(e.mode||e.error||'')} · ${t(e.ts)}</div></div>`}
async function load(){let s;try{s=await api('/v1/state?feed=150')}catch(e){return}
 $('#m-review').className=s.mode==='review'?'on':'';$('#m-auto').className=s.mode==='auto'?'on':'';
 $('#pause').textContent=s.paused?'Resume':'Pause';$('#pause').className=s.paused?'on':'';
 $('#plats').innerHTML=Object.entries(s.platforms).map(([n,p])=>`<span class="plat ${p.error?'err':''}" title="${esc(p.error||'')}">${esc(p.label||n)}${p.account?' · '+esc(p.account):''} <small>(${p.actions.join(', ')})</small></span>`).join('')||'<span class="empty">No platforms enabled. Edit social_bridge.json.</span>';
 $('#pc').textContent=s.pending.length?`(${s.pending.length})`:'';
 const box=$('#pending');const ids=s.pending.map(a=>a.id).join();
 if(ids!==last){[...box.children].forEach(c=>{if(!s.pending.find(a=>a.id===c.dataset.id))c.remove()});
  s.pending.forEach(a=>{if(!box.querySelector(`[data-id="${a.id}"]`))box.insertAdjacentHTML('beforeend',pend(a))});last=ids}
 if(!s.pending.length)box.innerHTML='<div class="empty">Nothing waiting.</div>';
 $('#feed').innerHTML=s.feed.slice().reverse().filter(e=>e.kind!=='queued').map(ev).join('')||'<div class="empty">No activity yet.</div>'}
$('#pending').onclick=async e=>{const b=e.target.closest('button');if(!b)return;const card=b.closest('.card');const id=card.dataset.id;b.disabled=true;
 if(b.dataset.do==='approve')await api(`/v1/actions/${id}/approve`,{text:card.querySelector('textarea').value});
 else await api(`/v1/actions/${id}/reject`,{});card.remove();last=null;load()};
$('#m-review').onclick=()=>api('/v1/mode',{mode:'review'}).then(load);$('#m-auto').onclick=()=>api('/v1/mode',{mode:'auto'}).then(load);
$('#pause').onclick=()=>api('/v1/pause',{paused:$('#pause').textContent==='Pause'}).then(load);
$('#poll').onclick=()=>api('/v1/poll',{}).then(load);
load();setInterval(load,2500);
</script></body></html>
"""
