'use strict';
const appState={view:'',entries:[],rows:[],target:null,selected:new Map(),busy:false,scanning:false,cache:{},sequence:0,plan:null,mode:'uninstall'};
function appBusy(){return state.running||state.busy||appState.busy||appState.scanning;}
function updateAppControls(){
  document.querySelectorAll('[data-uninstall],[data-leftovers]').forEach(b=>b.disabled=appBusy()||b.dataset.blocked==='true');
  const eligible=appState.rows.filter(x=>x.id&&x.deletable), chosen=eligible.filter(x=>appState.selected.has(x.id));
  $('residual-all').disabled=appBusy()||!eligible.length;$('residual-all').checked=!!eligible.length&&chosen.length===eligible.length;$('residual-all').indeterminate=chosen.length>0&&chosen.length<eligible.length;
  const ownership=chosen.filter(x=>x.needs_ownership_confirmation).length;
  $('residual-count').textContent='已选 '+chosen.length+' / '+eligible.length+' 项可清理残留'+(ownership?' · '+ownership+' 项需确认归属':'');
  $('residual-preview').disabled=appBusy()||!chosen.length;
  $('residual-confirm-absent').disabled=appBusy()||!$('residual-absent-ack').checked;
  $('residual-refresh').disabled=appBusy();$('apps-refresh').disabled=appState.busy||appState.scanning;
  $('apps-refresh').textContent=appState.scanning?'正在扫描…':(appState.cache[state.view]?'重新扫描':'开始扫描');
  document.querySelectorAll('[data-residual-select]').forEach(b=>{b.disabled=appBusy()||!appState.rows.some(x=>x.id===b.dataset.residualSelect&&x.deletable);});
  $('app-confirm-commit').disabled=appBusy()||!$('app-confirm-ack').checked||(appState.mode==='uninstall'&&$('app-confirm-name').value!==appState.plan?.app?.name)||(appState.mode==='residual'&&appState.plan?.needs_ownership_confirmation&&!$('app-ownership-ack').checked);
  $('app-confirm-cancel').disabled=appState.busy;
  updateScanControl();
}
async function loadApplications(scan=false){
  const mode=state.view;if(!['applications','orphans'].includes(mode))return;
  if(scan&&appState.scanning)return;
  const sequence=scan?++appState.sequence:appState.sequence;
  if(appState.view!==mode){appState.view=mode;appState.rows=[];appState.target=null;appState.selected.clear();$('residual-panel').hidden=true;$('apps-search').value='';}
  $('apps-title').textContent=mode==='applications'?'已安装的软件':'已卸载软件的残留候选';
  $('apps-subtitle').textContent=mode==='applications'?'只读取应用目录，显示真实图标与名称。':'点击开始扫描，再查找以前卸载软件的残留。';
  $('apps-guide').textContent=mode==='applications'?'点击“开始扫描”，只查找 /Applications 和当前用户 Applications 中的软件。选择卸载后才检索该软件的残留。涉及驱动、系统扩展或厂商后台服务的软件，请优先使用官方卸载器。':'先查看应用标识和来源。未发现应用可能是因为它装在其他位置；确认已卸载后，才开放归属明确的数据清理。';
  if(!scan){
    const cached=appState.cache[mode];appState.entries=cached?.items||[];renderApplications();
    $('apps-status').textContent=cached?(cached.items.length+' 项 · '+(cached.warnings||[]).join(' ')):'尚未扫描，点击“开始扫描”后读取'+(mode==='applications'?'软件列表。':'残留候选。');
    updateAppControls();return;
  }
  appState.scanning=true;updateAppControls();$('apps-status').textContent=mode==='applications'?'正在读取软件名称和图标…':'正在查找残留候选…';
  try{
    const d=await api(mode==='applications'?'apps':'apps/orphans');appState.cache[mode]=d;
    if(sequence!==appState.sequence||state.view!==mode)return;
    appState.entries=d.items;renderApplications();$('apps-status').textContent=d.items.length+' 项'+((d.warnings||[]).length?' · '+d.warnings.join(' '):'');
  }catch(e){if(sequence===appState.sequence)$('apps-status').textContent=e.message;}
  finally{appState.scanning=false;updateAppControls();}
}
function appIcon(app){
  const icon=typeof app.icon==='string'&&app.icon.startsWith('data:image/png;base64,')?app.icon:null;
  return icon?'<img class="app-icon" src="'+esc(icon)+'" width="48" height="48" loading="lazy" decoding="async" alt="'+esc(app.name)+'图标">':'<span class="app-symbol" title="未能读取应用图标" aria-label="通用应用图标">▣</span>';
}
function renderApplications(){
  const q=$('apps-search').value.trim().toLowerCase(),rows=appState.entries.filter(x=>(x.name+' '+x.identifier+' '+(x.path||'')).toLowerCase().includes(q));
  $('app-list').innerHTML=rows.map(x=>'<article class="app-card">'+appIcon(x)+'<div class="app-card-info"><b>'+esc(x.name)+'</b><span class="app-id">'+esc(x.identifier)+'</span><small>'+esc(x.path||({uninstalled:'本工具卸载记录',confirmed:'你已确认卸载',observed:'以前检测到的软件',unknown:'仅根据目录标识发现，尚未确认归属'}[x.source]||'待核对'))+'</small>'+(x.blocked?'<p>'+esc(x.blocked)+'</p>':'')+'</div><button '+(state.view==='applications'?'data-uninstall':'data-leftovers')+'="'+esc(x.id)+'" data-blocked="'+Boolean(x.blocked)+'">'+(state.view==='applications'?'核对卸载':x.needs_confirmation?'核对候选':'检索残留')+'</button></article>').join('')||'<div class="empty">'+(appState.cache[state.view]?'没有匹配的软件。可以调整搜索词或重新扫描。':'点击“开始扫描”后显示列表。')+'</div>';
  updateAppControls();
}
async function prepareUninstall(id){
  if(appBusy())return;appState.busy=true;updateAppControls();
  $('app-ownership-wrap').hidden=true;$('app-ownership-ack').checked=false;
  try{const p=await api('apps/preview',{id});appState.plan=p;appState.mode='uninstall';$('app-confirm-title').textContent='卸载 '+p.app.name+'？';$('app-confirm-summary').textContent=p.impact;$('app-confirm-list').innerHTML='<div class="confirm-item"><b>'+bytes(p.bytes)+(p.size_partial?'（部分统计）':'')+'</b>'+esc(p.app.name)+'<small>'+esc(p.app.path)+'</small><p class="confirm-impact">应用标识：'+esc(p.app.identifier)+'<br>涉及系统扩展、驱动或后台服务时，移除本体不能替代官方卸载器。</p></div>';$('app-name-wrap').hidden=false;$('app-confirm-name').value='';$('app-confirm-name').placeholder=p.app.name;$('app-confirm-ack').checked=false;$('app-confirm-dialog').showModal();}
  catch(e){toast(e.message);}finally{appState.busy=false;updateAppControls();}
}
async function loadLeftovers(id,confirmed=false){
  if(appBusy()){toast('请等待当前扫描或文件操作完成。');return;}
  appState.busy=true;updateAppControls();$('residual-notice').textContent='正在核对应用归属和残留…';$('residual-panel').hidden=false;
  try{const d=await api('apps/leftovers',{id,confirm_absent:confirmed});appState.target=d.target;appState.rows=d.items;appState.selected.clear();$('residual-title').textContent=d.target.name+' · 残留核对';$('residual-identity').textContent=d.target.identifier;$('residual-absent').hidden=!d.target.needs_confirmation;$('residual-absent-ack').checked=false;$('residual-notice').textContent=(d.warnings||[]).join(' ')+' '+d.notice;renderResiduals();if(typeof $('residual-panel').scrollIntoView==='function')$('residual-panel').scrollIntoView({behavior:'smooth',block:'start'});}
  catch(e){appState.rows=[];appState.selected.clear();$('residual-list').innerHTML='';$('residual-notice').textContent=e.message;}
  finally{appState.busy=false;updateAppControls();}
}
function renderResiduals(){
  $('residual-list').innerHTML=appState.rows.map(x=>'<article class="residual-card"><input type="checkbox" aria-label="选择 '+esc(x.name)+'" data-residual-select="'+esc(x.id||'')+'" '+(appState.selected.has(x.id)?'checked':'')+' '+(!x.id?'disabled':'')+'><div><div class="residual-heading"><b>'+esc(x.kind)+'</b><span>'+bytes(x.bytes)+(x.size_partial?'（部分统计）':'')+'</span><span class="badge '+esc(x.risk)+'">'+(x.blocked?'需其他方式处理':x.needs_ownership_confirmation?'需确认归属':'可清理')+'</span></div><div class="file-path">'+esc(x.path)+'</div><div class="file-explanation"><p><b>归属依据</b><span>'+esc(x.basis)+'</span></p><p><b>能不能删</b><span>'+esc(x.advice)+'</span></p><p><b>删后影响</b><span>'+esc(x.impact)+'</span></p>'+(x.size_note?'<p><b>占用说明</b><span>'+esc(x.size_note)+'</span></p>':'')+'</div><div class="residual-buttons"><button data-app-reveal="'+esc(x.explain_id)+'">在 Finder 中查看</button><button class="ai-explain" data-ai="'+esc(x.explain_id)+'">✧ AI 核对与检索建议</button></div></div></article>').join('')||'<div class="empty">在本次可读取范围内未发现匹配残留。自定义目录、共享组件或无权限位置仍可能有数据。</div>';
  updateAppControls();
}
async function prepareResiduals(){
  if(appBusy()||!appState.selected.size)return;appState.busy=true;updateAppControls();
  try{const p=await api('apps/residual-preview',{ids:[...appState.selected.keys()]});appState.plan=p;appState.mode='residual';$('app-confirm-title').textContent='清理所选残留？';$('app-confirm-summary').textContent='共 '+p.items.length+' 项，'+bytes(p.bytes)+(appState.rows.some(x=>appState.selected.has(x.id)&&x.size_partial)?'（部分统计）':'')+'。将所选目录及其中全部内容移入废纸篓。';$('app-confirm-list').innerHTML=p.items.map(x=>'<div class="confirm-item">'+esc(x.path.split('/').pop())+'<b>'+bytes(x.bytes)+'</b><small>'+esc(x.path)+'</small><p class="confirm-impact">'+(p.ownership_paths?.includes(x.path)?'需确认归属：':'')+esc(appState.selected.get(x.id)?.impact||appState.rows.find(r=>r.path===x.path)?.impact||'请先核对内容与备份。')+'</p></div>').join('');$('app-name-wrap').hidden=true;$('app-confirm-ack').checked=false;$('app-ownership-wrap').hidden=!p.needs_ownership_confirmation;$('app-ownership-ack').checked=false;$('app-confirm-dialog').showModal();}
  catch(e){toast(e.message);}finally{appState.busy=false;updateAppControls();}
}
$('app-confirm-commit').onclick=async()=>{
  if($('app-confirm-commit').disabled||appBusy())return;
  const isApp=appState.mode==='uninstall';appState.busy=true;state.busy=true;updateAppControls();$('app-confirm-commit').textContent='正在处理…';
  let next=null;
  try{const d=await api(isApp?'apps/uninstall':'apps/residual-trash',isApp?{ticket:appState.plan.ticket,confirm_name:$('app-confirm-name').value}:{ticket:appState.plan.ticket,caution_ack:$('app-confirm-ack').checked,ownership_ack:$('app-ownership-ack').checked});$('app-confirm-dialog').close();showResult(d,false);if(isApp&&d.target){$('result-title').textContent='软件本体已移入废纸篓';$('result-message').textContent='正在自动检索残留。残留不会自动删除，请在下方逐项核对。可在清理记录撤回应用本体。';next=d.target.id;}else if(!isApp){appState.selected.clear();next=appState.target?.id;}await loadApplications(true);}
  catch(e){toast(e.message);}finally{appState.busy=false;state.busy=false;$('app-confirm-commit').textContent='确认移入废纸篓';updateAppControls();selectionBar();}
  if(next)await loadLeftovers(next);
};
$('app-confirm-cancel').onclick=()=>$('app-confirm-dialog').close();
$('app-confirm-dialog').addEventListener('cancel',e=>{if(appState.busy)e.preventDefault();});
$('app-confirm-name').oninput=updateAppControls;$('app-confirm-ack').onchange=updateAppControls;
$('app-ownership-ack').onchange=updateAppControls;
$('apps-refresh').onclick=()=>loadApplications(true);$('apps-search').oninput=renderApplications;
$('residual-refresh').onclick=()=>appState.target&&loadLeftovers(appState.target.id);
$('residual-absent-ack').onchange=updateAppControls;
$('residual-confirm-absent').onclick=()=>appState.target&&$('residual-absent-ack').checked&&loadLeftovers(appState.target.id,true);
$('residual-preview').onclick=prepareResiduals;
$('residual-all').onchange=()=>{if(appBusy())return;appState.selected.clear();if($('residual-all').checked)for(const x of appState.rows.filter(x=>x.id&&x.deletable).slice(0,200))appState.selected.set(x.id,x);renderResiduals();};
$('residual-list').addEventListener('change',e=>{if(appBusy()||!e.target.matches('[data-residual-select]'))return;const row=appState.rows.find(x=>x.id===e.target.dataset.residualSelect);if(!row||!row.deletable)return;if(e.target.checked&&appState.selected.size<200)appState.selected.set(row.id,row);else{appState.selected.delete(row.id);e.target.checked=false;}updateAppControls();});
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.dataset.uninstall)await prepareUninstall(b.dataset.uninstall);if(b.dataset.leftovers)await loadLeftovers(b.dataset.leftovers);if(b.dataset.appReveal)await api('apps/reveal',{id:b.dataset.appReveal});if(b.dataset.aiConnect)await connectDiscoveredAI(b.dataset.aiConnect);}catch(err){toast(err.message);}});
let discoveredServices=[];
async function discoverAI(){
  $('ai-discover').disabled=true;$('ai-discovery-status').textContent='正在检查应用列表和本机服务…';
  try{const d=await api('ai/discover',{});discoveredServices=d.services;$('ai-clients').innerHTML=d.clients.map(x=>'<div class="ai-client '+(x.installed?'found':'')+'"><b>'+esc(x.name)+'</b><span>'+(!x.installed?'未在应用目录发现':x.local_engine?'已安装 · 检测服务':'已发现客户端')+'</span>'+(x.installed?'<small>'+esc(x.local_engine?'检测下方服务后可关联。':'客户端，暂不可直接关联。')+'</small>':'')+'</div>').join('');$('ai-services').innerHTML=d.services.map(s=>'<div class="ai-service"><b>'+esc(s.name)+'</b><small>'+esc(s.endpoint)+'</small><p>'+esc(s.message)+'</p>'+(s.available?'<select aria-label="'+esc(s.name)+' 模型" id="model-'+esc(s.id)+'">'+s.models.map(m=>'<option value="'+esc(m.name)+'">'+esc(m.name)+'</option>').join('')+'</select><button class="primary" data-ai-connect="'+esc(s.id)+'">一键关联</button>':'')+'</div>').join('');$('ai-discovery-status').textContent=d.notice;}
  catch(e){$('ai-discovery-status').textContent=e.message;}finally{$('ai-discover').disabled=false;}
}
async function connectDiscoveredAI(id){
  const service=discoveredServices.find(x=>x.id===id);if(!service)return;
  const model=$('model-'+id).value;const result=await api('ai/connect',{id,model});$('ai-provider').value=result.provider;$('ai-endpoint').value=result.endpoint;$('ai-model').innerHTML='<option value="'+esc(result.model)+'">'+esc(result.model)+'</option>';$('ai-settings-status').textContent='已关联 '+service.name+' · '+result.model+'。';$('ai-discovery-status').textContent='已保存关联：'+service.name+' / '+result.model+'。现在可点击文件或残留旁的 AI 解释。';toast('本地模型已关联。');
}
$('ai-discover').onclick=discoverAI;
$('ai-provider').onchange=()=>{$('ai-endpoint').value=$('ai-provider').value==='lmstudio'?'http://127.0.0.1:1234':'http://127.0.0.1:11434';$('ai-model').innerHTML='<option value="">先检测本机模型</option>';};
