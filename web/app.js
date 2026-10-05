import { initializeAuth, logout } from './auth.js';

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
  return `<details class="citation"><summary class="citation-row"><h3>${link(w.url,w.title)}</h3><div class="citation-meta"><span>${esc(e.detected_at.slice(0,10))}</span>${e.is_baseline?'':'<span class="new-badge">新增</span>'}</div><div class="source-links">${sourceLink(w.openalex_id,'OpenAlex','openalex')}${sourceLink(w.doi,'DOI','doi')}</div></summary><div class="authors">${authorLines}</div></details>`;
}
function counts() {
  const institutions=Object.create(null), authors=Object.create(null);
  for (const w of Object.values(data.works)) for (const a of w.authors || []) {
    if (a.name) (authors[a.name] ??= new Set()).add(w.id);
    for (const i of a.institutions || []) if(i.name) (institutions[i.name] ??= new Set()).add(w.id);
  }
  return {institutions,authors};
}
const PAGE_SIZE=10;
const rankingPages = {institutions: 1, authors: 1, citations: 1, papers: 1};
function paginate(kind, count, elementId, label) {
  const size=PAGE_SIZE;
  const pages=Math.max(1,Math.ceil(count/size));
  const page=rankingPages[kind]=Math.max(1,Math.min(rankingPages[kind],pages));
  $(elementId).innerHTML=Array.from({length:pages},(_,i)=>`<button data-pagination="${kind}" data-page="${i+1}" aria-label="${label}第 ${i+1} 页" ${page===i+1?'class="current" aria-current="page"':''}>${i+1}</button>`).join('');
  return (page-1)*size;
}
let rankingMaps;
function ranking(map, id, kind) {
  const rows=Object.entries(map).map(([name,works])=>[name,works.size]).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
  const max=rows[0]?.[1]||1;
  const start=paginate(kind,rows.length,kind==='institutions'?'institution-pagination':'author-pagination',kind==='institutions'?'单位':'作者');
  $(id).innerHTML=rows.slice(start,start+PAGE_SIZE).map(([name,n],index)=>{
    let heading=`<span>${esc(name)}</span><strong>${n}</strong>`, expanded='';
    if(kind==='authors') {
      const works=[...map[name]].map(workId=>data.works[workId]).filter(Boolean);
      const unit=works.flatMap(w=>(w.authors||[]).filter(a=>a.name===name)).map(a=>(a.institutions||[])[0]?.name || (a.raw_affiliations||[])[0]).find(Boolean);
      const listId=`author-works-${start+index}`;
      heading=`<span>${esc(name)}${unit?` <span class="rank-affiliation">(${esc(unit)})</span>`:''}</span><button class="rank-count" data-author-toggle aria-expanded="false" aria-controls="${listId}" aria-label="展开 ${esc(name)} 的 ${n} 篇论文">${n}</button>`;
      expanded=`<div id="${listId}" class="rank-works" hidden>${works.map(w=>`<div>${link(w.url||w.doi||w.openalex_id,w.title)}</div>`).join('')}</div>`;
    }
    return `<div class="rank-row"><div class="rank-heading">${heading}</div><div class="rank-bar"><i style="width:${100*n/max}%"></i></div>${expanded}</div>`;
  }).join('') || empty('暂无记录');
}
document.addEventListener('click',event=>{
  const toggle=event.target.closest('button[data-author-toggle]');
  if(toggle) {
    const list=toggle.closest('.rank-row').querySelector('.rank-works');
    list.hidden=!list.hidden;toggle.setAttribute('aria-expanded',String(!list.hidden));toggle.setAttribute('aria-label',toggle.getAttribute('aria-label').replace(/^(展开|收起)/,list.hidden?'展开':'收起'));return;
  }
  const button=event.target.closest('button[data-pagination]');if(!button)return;
  const kind=button.dataset.pagination;
  rankingPages[kind]=Number(button.dataset.page);
  if(kind==='citations') renderCitations();
  else if(kind==='papers') renderPapers();
  else ranking(rankingMaps[kind],kind==='institutions'?'institution-list':'author-list',kind);
});
function renderCitations() {
  const target=$('target').value;
  const filtered=items.filter(x=>x.edge.target_id===target);
  $('result-count').textContent=`${filtered.length} 篇引用`;
  const start=paginate('citations',filtered.length,'citation-pagination','引用');
  $('citation-list').innerHTML=filtered.slice(start,start+PAGE_SIZE).map(card).join('') || empty('暂无引用');
}
function renderPapers() {
  const current=Object.values(data.papers).filter(p=>p.in_current_profile);
  const start=paginate('papers',current.length,'paper-pagination','论文');
  const cutoff=new Date(data.last_update.slice(0,10)+'T00:00:00Z');
  cutoff.setUTCDate(cutoff.getUTCDate()-15);
  const cutoffDate=cutoff.toISOString().slice(0,10);
  $('paper-rows').innerHTML=current.slice(start,start+PAGE_SIZE).map(p=>{
    const points=data.history.filter(h=>Object.hasOwn(h.papers,p.id)).map(h=>({date:h.date,value:h.papers[p.id]}));
    const baseline=points.filter(point=>point.date<=cutoffDate).at(-1) || points[0];
    const change=baseline?Number(p.citations)-Number(baseline.value):null;
    const changeText=change===null?'—':`${change>0?'+':''}${change}`;
    return `<details class="paper-trend"><summary class="paper-grid"><span class="paper-title">${link(p.url,p.title)}</span><span class="paper-value"><span class="metric-label">引用</span>${p.citations}</span><span class="paper-value ${change>0?'up':''}"><span class="metric-label">近15日变化</span>${changeText}</span></summary><div class="paper-chart">${graph(points,p.title+' 引用趋势')}</div></details>`;
  }).join('') || empty('暂无论文');
}
function render() {
  const current=Object.values(data.papers).filter(p=>p.in_current_profile);
  items=Object.values(data.edges).filter(e=>data.works[e.work_id]&&data.papers[e.target_id]).map(edge=>({edge,work:data.works[edge.work_id]})).sort((a,b)=>b.edge.detected_at.localeCompare(a.edge.detected_at)||a.work.title.localeCompare(b.work.title));
  const maps=counts();
  $('profile').textContent=data.profile.name || 'Citation';
  $('update').textContent=data.last_update?`更新于 ${dateText(data.last_update)}`:'';
  $('total').textContent=data.profile.metrics?.citations ?? '—';
  $('papers-count').textContent=current.length;
  const weekDate=new Date(data.last_update.slice(0,10)+'T00:00:00Z');
  weekDate.setUTCDate(weekDate.getUTCDate()-7);
  const weekBaseline=data.history.filter(h=>h.date<=weekDate.toISOString().slice(0,10)).at(-1) || data.history[0];
  const weekDelta=weekBaseline?Number(data.profile.metrics?.citations||0)-Number(weekBaseline.total):null;
  $('events').textContent=weekDelta===null?'—':`${weekDelta>0?'+':''}${weekDelta}`;
  $('inst-count').textContent=Object.keys(maps.institutions).length;
  if(safeURL(data.profile.url)){$('scholar').href=safeURL(data.profile.url);$('scholar').hidden=false;}
  $('chart').innerHTML=graph(data.history.map(h=>({date:h.date,value:h.total})),'总引用数趋势');
  $('recent').innerHTML=items.filter(x=>!x.edge.is_baseline).slice(0,5).map(card).join('') || empty('暂无新增引用');
  const selected=$('target').value;
  $('target').innerHTML=current.map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  if(current.some(p=>p.id===selected)) $('target').value=selected;
  renderPapers();
  rankingMaps=maps;ranking(maps.institutions,'institution-list','institutions'); ranking(maps.authors,'author-list','authors');renderCitations();
}
$('nav').addEventListener('click',e=>{
  const button=e.target.closest('button[data-tab]');if(!button)return;
  for(const b of $('nav').querySelectorAll('button')){b.classList.toggle('active',b===button);if(b===button)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
  for(const tab of document.querySelectorAll('.tab'))tab.hidden=tab.id!==button.dataset.tab;
});
$('target').addEventListener('change',()=>{rankingPages.citations=1;renderCitations();});
$('logout').addEventListener('click',logout);
$('export').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([window.citationCSV || ''],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='citations.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
initializeAuth(async payload=>{data=payload.data;window.citationCSV=payload.csv;render();});
