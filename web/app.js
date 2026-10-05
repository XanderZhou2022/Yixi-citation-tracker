import { initializeAuth, loadSnapshot, logout } from './auth.js';

const $ = id => document.getElementById(id);
let data, items = [];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  chevron: '<svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
  openalex: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c6 6 6 12 0 18-6-6-6-12 0-18Z"/></svg>',
  doi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(1 1)"/></svg>'
};
function safeURL(value) {
  try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; }
}
function link(url, text, cls = '') {
  const safe = safeURL(url);
  return safe ? `<a class="${cls}" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : esc(text);
}
function sourceLink(url, name, icon) {
  const safe = safeURL(url);
  return safe ? `<a class="source-link" href="${esc(safe)}" target="_blank" rel="noopener noreferrer" aria-label="${name}" title="${name}">${icons[icon]}<span>${name}</span></a>` : '';
}
const empty = text => `<div class="empty">${esc(text)}</div>`;
const dateText = value => (value || '').replace('T', ' ').slice(0, 16);
function graph(points, label) {
  if (!points.length) return empty('暂无记录');
  const W=900, H=220, L=42, R=20, T=26, B=34;
  const values = points.map(p => Number(p.value));
  const lo = Math.max(0, Math.min(...values) - 1), hi = Math.max(...values) + 1;
  const first = Date.parse(points[0].date), last = Date.parse(points.at(-1).date);
  const xy = points.map((p,i) => [points.length === 1 ? (W+L-R)/2 : L+(Date.parse(p.date)-first)/(last-first||1)*(W-L-R), H-B-(values[i]-lo)/(hi-lo)*(H-T-B)]);
  const ticks = [...new Set([Math.ceil(lo), Math.round((lo+hi)/2), Math.floor(hi)])];
  const grid = ticks.map(v => {const y=H-B-(v-lo)/(hi-lo)*(H-T-B);return `<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#edf0f6"/><text x="${L-12}" y="${y+4}" text-anchor="end">${v}</text>`;}).join('');
  const xlabels = points.length === 1 ? `<text x="${xy[0][0]}" y="${H-9}" text-anchor="middle">${esc(points[0].date)}</text>` : `<text x="${L}" y="${H-9}">${esc(points[0].date)}</text><text x="${W-R}" y="${H-9}" text-anchor="end">${esc(points.at(-1).date)}</text>`;
  return `<svg class="chart" role="img" aria-label="${esc(label)}" viewBox="0 0 ${W} ${H}">${grid}<polyline points="${xy.map(p=>p.join(',')).join(' ')}" fill="none" stroke="#245fb4" stroke-width="2.5" stroke-linejoin="round"/>${xy.map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="4.5" fill="#245fb4"><title>${esc(points[i].date)} · ${values[i]}</title></circle>`).join('')}${xlabels}</svg>`;
}
function card({work:w, edge:e}) {
  const authorLines = (w.authors || []).map(a => {
    const units = (a.institutions || []).map(i=>i.name).join(' · ') || (a.raw_affiliations || []).join(' · ');
    return `<div class="author"><span class="author-name">${esc(a.name)}</span><span class="author-unit">${esc(units || '—')}</span></div>`;
  }).join('') || `<div class="author-raw">${esc(w.authors_text || '—')}</div>`;
  const n = w.authors?.length;
  return `<article class="citation"><div class="citation-heading"><h3>${link(w.url,w.title)}</h3><div class="source-links">${sourceLink(w.openalex_id,'OpenAlex','openalex')}${sourceLink(w.doi,'DOI','doi')}</div></div><div class="citation-meta"><span>${esc(w.year || '—')}</span><span>${esc(e.detected_at.slice(0,10))}</span>${e.is_baseline?'':'<span class="new-badge">新增</span>'}</div><details class="author-details"><summary>${icons.chevron} 作者与单位${n?` <span>(${n})</span>`:''}</summary><div class="authors">${authorLines}</div></details></article>`;
}
function counts() {
  const institutions=Object.create(null), authors=Object.create(null);
  for (const w of Object.values(data.works)) for (const a of w.authors || []) {
    if (a.name) (authors[a.name] ??= new Set()).add(w.id);
    for (const i of a.institutions || []) if(i.name) (institutions[i.name] ??= new Set()).add(w.id);
  }
  return {institutions,authors};
}
function ranking(map,id) {
  const rows=Object.entries(map).map(([name,works])=>[name,works.size]).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  const max=rows[0]?.[1]||1;
  $(id).innerHTML=rows.map(([name,n])=>`<div class="rank-row"><div class="rank-heading"><span>${esc(name)}</span><strong>${n}</strong></div><div class="rank-bar"><i style="width:${100*n/max}%"></i></div></div>`).join('') || empty('暂无记录');
}
function renderCitations() {
  const target=$('target').value;
  const filtered=items.filter(x=>x.edge.target_id===target);
  $('result-count').textContent=`${filtered.length} 篇引用`;
  $('citation-list').innerHTML=filtered.map(card).join('') || empty('暂无引用');
}
function render() {
  const current=Object.values(data.papers).filter(p=>p.in_current_profile);
  items=Object.values(data.edges).filter(e=>data.works[e.work_id]&&data.papers[e.target_id]).map(edge=>({edge,work:data.works[edge.work_id]})).sort((a,b)=>b.edge.detected_at.localeCompare(a.edge.detected_at)||a.work.title.localeCompare(b.work.title));
  const maps=counts();
  $('profile').textContent=data.profile.name || 'Citation';
  $('update').textContent=data.last_update?`更新于 ${dateText(data.last_update)}`:'';
  $('total').textContent=data.profile.metrics?.citations ?? '—';
  $('papers-count').textContent=current.length;
  $('events').textContent=items.filter(x=>!x.edge.is_baseline).length;
  $('inst-count').textContent=Object.keys(maps.institutions).length;
  const prior=data.history.filter(h=>h.date<data.last_update.slice(0,10)).at(-1);
  const delta=prior?Number(data.profile.metrics?.citations||0)-Number(prior.total):null;
  $('net').textContent=delta===null?'—':`${delta>0?'+':''}${delta}`;
  if(safeURL(data.profile.url)){$('scholar').href=safeURL(data.profile.url);$('scholar').hidden=false;}
  $('chart').innerHTML=graph(data.history.map(h=>({date:h.date,value:h.total})),'总引用数趋势');
  $('recent').innerHTML=items.filter(x=>!x.edge.is_baseline).slice(0,5).map(card).join('') || empty('暂无新增引用');
  const selected=$('target').value;
  $('target').innerHTML=current.map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  if(current.some(p=>p.id===selected)) $('target').value=selected;
  $('paper-rows').innerHTML=current.map(p=>{
    const points=data.history.filter(h=>Object.hasOwn(h.papers,p.id)).map(h=>({date:h.date,value:h.papers[p.id]}));
    const date=points.at(-1)?.date || '';
    return `<details class="paper-trend"><summary class="paper-grid"><span class="paper-title">${link(p.url,p.title)}</span><span class="paper-value"><span class="metric-label">引用</span>${p.citations}</span><span class="paper-value ${p.delta>0?'up':''}"><span class="metric-label">变化</span>${p.delta>0?'+':''}${p.delta||0}</span><span class="paper-date"><span class="metric-label">更新时间</span>${esc(date)}</span>${icons.chevron}</summary><div class="paper-chart">${graph(points,p.title+' 引用趋势')}</div></details>`;
  }).join('') || empty('暂无论文');
  ranking(maps.institutions,'institution-list'); ranking(maps.authors,'author-list');renderCitations();
}
async function refresh() {
  try { const payload=await loadSnapshot(); data=payload.data; window.citationCSV=payload.csv;render();$('error').hidden=true; }
  catch { $('error').textContent='暂时无法读取数据，请稍后重试。';$('error').hidden=false; }
}
$('nav').addEventListener('click',e=>{
  const button=e.target.closest('button[data-tab]');if(!button)return;
  for(const b of $('nav').querySelectorAll('button')){b.classList.toggle('active',b===button);if(b===button)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
  for(const tab of document.querySelectorAll('.tab'))tab.hidden=tab.id!==button.dataset.tab;
});
$('target').addEventListener('change',renderCitations);
$('reload').addEventListener('click',refresh);
$('logout').addEventListener('click',logout);
$('export').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([window.citationCSV || ''],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='citations.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
initializeAuth(async payload=>{data=payload.data;window.citationCSV=payload.csv;render();});
