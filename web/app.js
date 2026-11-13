'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = location.hash.slice(1) || sessionStorage.getItem('space-lens-token') || '';
if(token){sessionStorage.setItem('space-lens-token',token);history.replaceState(null,'',location.pathname);}
const labels={recommended:'建议清理',review:'确认后可清理',caution:'慎重清理',protected:'仅查看'};
let state={view:'overview',risk:'recommended',path:'',home:'',offset:0,total:0,items:[],selection:new Map(),running:false,done:false,ticket:null,operation:'trash',caution:false,busy:false,loading:false};
let toastTimer,searchTimer,loadSequence=0;
function bytes(n){if(!Number.isFinite(n))return '—';const units=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return n.toLocaleString('zh-CN',{maximumFractionDigits:i>1?2:0})+' '+units[i];}
function toast(s){$('toast').textContent=s;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,16000);}
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'X-Local-Token':token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'操作失败');return d;}
function selectedRoots(){const all=[...state.selection.values()].sort((a,b)=>a.path.length-b.path.length),out=[];for(const x of all)if(!out.some(p=>x.path===p.path||x.path.startsWith(p.path+'/')))out.push(x);return out;}
function selectionBar(){
  const items=selectedRoots();$('selection-bar').hidden=!items.length;$('selected-count').textContent='已选 '+items.length+' 项';$('selected-size').textContent=bytes(items.reduce((s,x)=>s+x.bytes,0));
  document.querySelectorAll('[data-operation]').forEach(b=>b.disabled=!items.length||state.running||state.busy||state.loading);
  const eligible=state.items.filter(x=>x.id&&x.deletable),count=eligible.filter(x=>state.selection.has(x.path)).length;
  $('select-all').checked=eligible.length>0&&count===eligible.length;$('select-all').indeterminate=count>0&&count<eligible.length;
  $('select-all').disabled=!eligible.length||state.running||state.busy||state.loading;
  $('select-scope').textContent='当前页可选 '+eligible.length+' 项，已选 '+count+' 项 · 不含其他页';
}
function renderRows(){
  $('empty').hidden=state.items.length>0;
  $('empty').textContent=!state.done&&!state.running?'尚未扫描。点击右上角“开始扫描”，或前往“软件卸载”仅扫描软件。':'这个分类下没有找到大于 20 MiB 的项目。可以切换分类或逐层浏览文件夹。';
  $('rows').innerHTML=state.items.map(x=>'<tr><td><input type="checkbox" aria-label="选择 '+esc(x.name)+'" data-select="'+esc(x.path)+'" '+(!x.id||!x.deletable||state.running||state.busy||state.loading?'disabled':'')+' '+(state.selection.has(x.path)?'checked':'')+'></td><td>'+
    (x.dir?'<button class="file-name folder-link" data-folder="'+esc(x.path)+'">▱ '+esc(x.name)+' ↗</button>':'<span class="file-name">▧ '+esc(x.name)+'</span>')+
    '<div class="file-path">'+esc(x.path)+'</div><div class="file-tags"><span class="file-kind">'+esc(x.kind)+'</span>'+(x.owner?'<span class="file-owner">'+esc(x.owner)+'</span>':'')+'</div>'+
    '<div class="file-explanation"><p><b>这里是什么</b><span>'+esc(x.content||x.note)+'</span></p><p><b>能不能删</b><span>'+esc(x.advice||x.note)+'</span></p><p class="impact"><b>删后影响</b><span>'+esc(x.impact||'用途还不能确定，先核对内容和备份。')+'</span></p></div>'+
    (x.children&&x.children.length?'<details class="contents-preview"><summary>里面较大的项目 · 上次扫描</summary>'+x.children.map(c=>'<div>'+(c.dir?'<button data-folder="'+esc(c.path)+'">'+esc(c.name)+' ↗</button>':'<span>'+esc(c.name)+'</span>')+'<small>'+bytes(c.bytes)+'</small></div>').join('')+'</details>':'')+
    '<div class="file-basis">'+esc(x.basis||'根据路径和类型判断，需核对实际用途')+(x.incomplete?' · 未完整扫描，不可整项清理。':'')+
    '</div>'+(x.explain_id?'<button class="ai-explain" data-ai="'+esc(x.explain_id)+'">✧ 本地 AI 解释</button>':'')+'</td><td><div class="size">'+bytes(x.bytes)+'</div><div class="logical-size">文件大小<br>'+bytes(x.logical)+'</div></td><td><span class="badge '+esc(x.risk)+'">'+esc(labels[x.risk])+
    '</span></td><td><button class="reveal" title="在 Finder 中显示" aria-label="在 Finder 中显示 '+esc(x.name)+'" data-reveal="'+esc(x.id)+'" '+(!x.id?'disabled':'')+'>↗</button></td></tr>').join('');
  selectionBar();
}
async function loadItems(){
  const seq=++loadSequence;
  if(state.view==='settings')return;
  if(state.view==='history')return loadHistory();
  if(['applications','orphans'].includes(state.view))return loadApplications();
  state.loading=true;selectionBar();
  try{
  let result;
  if(state.view==='browse'){
    result=await api('browse?path='+encodeURIComponent(state.path)+'&offset='+state.offset);if(seq!==loadSequence)return;
    if(state.offset>0&&state.offset>=result.total){state.offset=Math.max(0,Math.floor((result.total-1)/150)*150);return await loadItems();}
    state.total=result.total;$('current-path').textContent=state.path;
    $('page-info').textContent=Math.min(state.offset+1,state.total)+'–'+Math.min(state.offset+150,state.total)+' / '+state.total+' 项';
    $('pager').hidden=state.total<=150;$('prev-page').disabled=state.offset===0;$('next-page').disabled=state.offset+150>=state.total;
  }else{result=await api('items?risk='+state.risk+'&q='+encodeURIComponent($('search').value));if(seq!==loadSequence)return;$('pager').hidden=true;}
  state.items=result.items;
  for(const x of state.items)if(state.selection.has(x.path)){if(x.id&&x.deletable)state.selection.set(x.path,x);else state.selection.delete(x.path);}
  }finally{if(seq===loadSequence){state.loading=false;renderRows();}}
}
async function loadHistory(){
  const d=await api('history');
  $('history').innerHTML=d.items.length?d.items.map(x=>'<div class="history-item"><div class="path">'+esc(x.source)+'<small>'+new Date(x.time*1000).toLocaleString('zh-CN')+' · '+bytes(x.bytes)+' · '+
    ({trashed:'已移到废纸篓',restored:'已撤回',failed:'未移动',pending:'待核对，可尝试撤回',deleted:'已永久删除 · 不可撤回',deleting:'直接删除未完成 · 可能已删除部分内容，不可撤回',delete_failed:'删除未完全成功 · 部分内容可能已删除，不可撤回'}[x.status]||esc(x.status))+'</small></div>'+
    (['trashed','pending'].includes(x.status)?'<button data-undo="'+esc(x.id)+'">↶ 撤回</button>':'')+'</div>').join(''):
    '<div class="empty">还没有清理记录。你可以先浏览，所有文件都保持原样。</div>';
}
async function view(name,path){
  if(['applications','orphans','settings'].includes(name))state.selection.clear();
  state.view=name;state.offset=0;if(path)state.path=path;if(!state.path)state.path=state.home;
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===name));
  $('page-title').textContent={overview:'先看清，再清理。',browse:'每个文件，都心中有数。',history:'每次清理，都留有退路。',applications:'卸载软件，数据分开核对。',orphans:'找回遗漏的卸载残留。',settings:'按你的习惯，安心使用。'}[name];
  $('summary').hidden=name!=='overview';$('overview-chart').hidden=name!=='overview';$('files-section').hidden=!['overview','browse'].includes(name);$('apps-section').hidden=!['applications','orphans'].includes(name);$('history-section').hidden=name!=='history';
  $('settings-section').hidden=name!=='settings';
  $('tabs').hidden=name!=='overview';$('breadcrumb').hidden=name!=='browse';$('search').parentElement.hidden=name!=='overview';
  $('list-title').textContent=name==='browse'?'文件与文件夹':'清理建议';
  $('list-subtitle').textContent=name==='browse'?'点击文件夹继续查看；说明按路径和类型判断，不能代替备份。':'看懂用途、删除条件和影响，再决定是否清理。';
  $('list-message').textContent=state.running?'扫描期间只可查看，完成后才能清理。':'';
  await loadItems();updateScanControl();
}
function updateScanControl(){
  $('scan').hidden=state.view==='settings';
  const scoped=['applications','orphans'].includes(state.view)&&typeof appState!=='undefined';
  const scanning=scoped?appState.scanning:state.running;
  const done=scoped?Boolean(appState.cache[state.view]):state.done;
  $('scan').textContent=scanning?'正在扫描…':done?'↻ 重新扫描':'开始扫描';
  $('scan').disabled=state.running||state.busy||(scoped&&(appState.scanning||appState.busy));
  $('scan-status').hidden=state.view==='settings'||(scoped&&!state.running);
}
async function status(){
  const d=await api('status');state.home=d.home;const wasRunning=state.running;state.running=d.scan.running;state.done=d.scan.done;
  $('free').textContent=bytes(d.disk.free);const pct=Math.round(100*d.disk.used/d.disk.total);$('used-percent').textContent=pct+'%';$('usage-bar').style.width=pct+'%';
  document.querySelector('.disk-ring').style.background='conic-gradient(#b69158 0% '+pct+'%, #e7eee7 '+pct+'% 100%)';
  $('capacity').textContent='已用 '+bytes(d.disk.used)+' / 总计 '+bytes(d.disk.total);
  $('quit').disabled=false;updateScanControl();
  $('scan-status').classList.toggle('running',state.running);
  $('scan-status').textContent=state.running?'● 正在扫描 · 已检查 '+d.scan.files.toLocaleString()+' 个文件、'+d.scan.dirs.toLocaleString()+' 个文件夹 · '+d.scan.errors+' 处不可读取\n'+d.scan.current:
    d.scan.error?'扫描中断：'+d.scan.error:d.scan.done?'✓ 扫描完成 · '+new Date(d.scan.finished*1000).toLocaleString('zh-CN')+' · '+d.scan.errors+' 处不可读取'+(d.scan.needs_rescan?' · 文件列表已更新，文件夹大小仍是上次扫描结果。':''):'尚未扫描。点击“开始扫描”后，才会读取文件占用。';
  const names={[state.home]:'你的用户文件','/Applications':'已安装应用','/Library':'共享应用数据','/private/var':'系统运行数据','/Users/Shared':'共享文件'};
  $('roots').innerHTML=d.roots.map(x=>'<button class="root-card" data-folder="'+esc(x.path)+'"><div class="root-icon">▱</div><span class="root-name">'+esc(names[x.path]||x.name)+'</span><strong>'+
    bytes(x.bytes)+'</strong><div class="root-bar"><i data-width="'+Math.min(100,x.bytes/d.disk.used*100)+'"></i></div></button>').join('');
  document.querySelectorAll('[data-width]').forEach(x=>x.style.width=x.dataset.width+'%');
  if(wasRunning&&!state.running){await loadItems();toast('扫描完成，可以查看清理建议了。');}
  selectionBar();if(typeof updateAppControls==='function')updateAppControls();
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  try{
    if(b.dataset.operation)await previewAction(b.dataset.operation);
    if(b.dataset.ai)await explainWithAI(b.dataset.ai);
    if(b.dataset.view)await view(b.dataset.view);
    if(b.dataset.folder)await view('browse',b.dataset.folder);
    if(b.dataset.risk){state.risk=b.dataset.risk;document.querySelectorAll('[data-risk]').forEach(x=>x.classList.toggle('selected',x===b));await loadItems();}
    if(b.dataset.reveal)await api('reveal',{id:b.dataset.reveal});
    if(b.dataset.undo){b.disabled=true;await api('undo',{id:b.dataset.undo});toast('已恢复到原位置。重新扫描后占用统计会更新。');await loadHistory();await status();}
  }catch(err){toast(err.message);b.disabled=false;}
});
$('rows').addEventListener('change',e=>{if(!e.target.matches('[data-select]'))return;const x=state.items.find(x=>x.path===e.target.dataset.select);if(e.target.checked)state.selection.set(x.path,x);else state.selection.delete(x.path);if(selectedRoots().length>200){state.selection.delete(x.path);e.target.checked=false;toast('一次最多处理 200 项，请分批清理。');}selectionBar();});
$('select-all').onchange=()=>{
  if(state.running||state.busy||state.loading)return;
  const eligible=state.items.filter(x=>x.id&&x.deletable),before=new Map(state.selection);
  if($('select-all').checked)for(const x of eligible)state.selection.set(x.path,x);
  else for(const x of eligible)state.selection.delete(x.path);
  if(selectedRoots().length>200){state.selection=before;toast('全选后将超过 200 项，请先处理已选项目或分批选择。');}
  renderRows();
};
$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadItems().catch(e=>toast(e.message)),300);});
$('clear-selection').onclick=()=>{state.selection.clear();renderRows();};
$('up').onclick=()=>{const p=state.path.slice(0,state.path.lastIndexOf('/'));if(p===state.home||p.startsWith(state.home+'/')||['/Applications','/Library','/private/var','/Users/Shared'].some(r=>p===r||p.startsWith(r+'/')))view('browse',p).catch(e=>toast(e.message));else view('overview').catch(e=>toast(e.message));};
$('prev-page').onclick=()=>{state.offset=Math.max(0,state.offset-150);loadItems().catch(e=>toast(e.message));};
$('next-page').onclick=()=>{state.offset+=150;loadItems().catch(e=>toast(e.message));};
$('refresh-history').onclick=()=>loadHistory().catch(e=>toast(e.message));
$('scan').onclick=async()=>{try{if(['applications','orphans'].includes(state.view)){await loadApplications(true);return;}await api('scan',{});state.selection.clear();await status();renderRows();}catch(e){toast(e.message);}};
function updateConfirm(){
  $('commit').disabled=state.busy||(state.caution&&!$('caution-ack').checked)||(state.operation==='delete'&&$('delete-confirm-text').value!=='永久删除');
}
async function previewAction(operation){
  if(state.busy||state.loading||state.running||!selectedRoots().length)return;
  state.busy=true;selectionBar();
  try{
    const d=await api('preview',{ids:selectedRoots().map(x=>x.id),operation});state.ticket=d.ticket;state.operation=d.operation;state.caution=d.caution;
    const permanent=d.operation==='delete';
    $('confirm-title').textContent=permanent?'直接永久删除这些文件？':'将这些文件移到废纸篓？';
    $('confirm-eyebrow').textContent=permanent?'不可撤回的操作':'可撤回的操作';
    $('confirm-warning').textContent=permanent?'这些文件将直接永久删除，不经过废纸篓，无法从本工具撤回。请先退出相关应用，确认文件不再需要或已有备份。':'请先退出相关应用。移到废纸篓后仍占空间，可在清理记录中撤回。素材移走后可能导致剪辑工程离线。';
    $('confirm-warning').classList.toggle('permanent',permanent);$('confirm-dialog').classList.toggle('permanent',permanent);
    $('commit').className=permanent?'danger':'primary';$('commit').textContent=permanent?'确认永久删除':'确认移到废纸篓';
    $('delete-confirm-wrap').hidden=!permanent;$('delete-confirm-text').value='';
    $('confirm-summary').textContent='共 '+d.items.length+' 项，统计占用 '+bytes(d.bytes)+'。父子目录已去重。';
    $('confirm-list').innerHTML=d.items.map(x=>'<div class="confirm-item">'+esc(x.path.split('/').pop())+'<b>'+bytes(x.bytes)+'</b><small>'+esc(x.path)+'</small><p class="confirm-impact">删除后：'+esc(state.selection.get(x.path)?.impact||'请确认不再需要，并且已保留必要备份。')+'</p></div>').join('');
    $('ack-wrap').hidden=!d.caution;$('caution-ack').checked=false;$('confirm-dialog').showModal();
  }catch(e){toast(e.message);}finally{state.busy=false;selectionBar();updateConfirm();}
}
$('caution-ack').onchange=updateConfirm;
$('delete-confirm-text').oninput=updateConfirm;
$('confirm-dialog').addEventListener('cancel',e=>{if(state.busy)e.preventDefault();});
$('cancel-confirm').onclick=()=>$('confirm-dialog').close();
$('dismiss-result').onclick=()=>$('operation-result').hidden=true;
function showResult(result,permanent){
  const completed=permanent?result.deleted:result.moved, failures=result.failed||[];
  $('operation-result').hidden=false;$('operation-result').classList.toggle('partial',failures.length>0);
  $('result-title').textContent=failures.length?(completed.length?'部分完成':'未完成清理'):(permanent?'删除完成':'已移入废纸篓');
  $('result-message').textContent=(permanent?'已永久删除 ':'已移入废纸篓 ')+completed.length+' 项'+(failures.length?'，'+failures.length+' 项未完全完成。':'。')+
    (permanent?'永久删除不可撤回。':'可在清理记录中撤回；移入废纸篓不会立即释放空间。')+' 当前列表已刷新，重新扫描可更新文件夹大小。'+(result.refresh_warning||'');
  $('result-errors').hidden=!failures.length;
  $('result-error-list').innerHTML=failures.map(x=>'<li><b>'+esc(x.path)+'</b><p>'+esc(x.error)+'</p></li>').join('');
  toast($('result-title').textContent+' · '+completed.length+' 项'+(failures.length?'，请查看未完成项。':''));
}
$('commit').onclick=async()=>{
  if(state.busy)return;
  const b=$('commit'),permanent=state.operation==='delete';state.busy=true;selectionBar();b.disabled=true;b.textContent=permanent?'正在永久删除…':'正在移动…';$('cancel-confirm').disabled=true;
  try{
    const d=await api(state.operation,{ticket:state.ticket,caution_ack:$('caution-ack').checked,confirm_text:$('delete-confirm-text').value});$('confirm-dialog').close();state.selection.clear();
    const completed=permanent?d.deleted:d.moved;
    // Keep the current category, search and page. If the current folder itself
    // was removed, show its parent instead of sending the user to history.
    if(state.view==='browse')for(const x of completed)if(state.path===x.path||state.path.startsWith(x.path+'/'))state.path=x.path.slice(0,x.path.lastIndexOf('/'));
    showResult(d,permanent);
    const scrollBefore=typeof window!=='undefined'?window.scrollY:0;
    try{await loadItems();await status();}catch(refreshError){$('result-message').textContent+=' 列表刷新未完成，请重新扫描。';}
    if(typeof window!=='undefined')window.scrollTo({top:scrollBefore,behavior:'instant'});
  }catch(e){toast(e.message);}finally{state.busy=false;$('cancel-confirm').disabled=false;b.textContent=permanent?'确认永久删除':'确认移到废纸篓';updateConfirm();renderRows();$('scan').disabled=state.running;$('quit').disabled=state.running;}
};
$('quit').onclick=async()=>{if(typeof window!=='undefined'&&window.webkit?.messageHandlers?.spaceLens){window.webkit.messageHandlers.spaceLens.postMessage('quit');return;}try{await api('quit',{});clearInterval(poll);toast('本地服务已退出，可以关闭此页面。');document.querySelectorAll('button').forEach(b=>b.disabled=true);}catch(e){toast(e.message);}};
let aiSequence=0;
$('ai-settings-open').onclick=async()=>{try{const settings=await api('ai/settings');$('ai-provider').value=settings.provider||'ollama';$('ai-endpoint').value=settings.endpoint;$('ai-model').innerHTML='<option value="'+esc(settings.model)+'">'+esc(settings.model||'先检测本机模型')+'</option>';$('ai-settings-status').textContent='';$('ai-settings-dialog').showModal();if(typeof discoverAI==='function')await discoverAI();}catch(e){toast(e.message);}};
$('ai-settings-close').onclick=()=>$('ai-settings-dialog').close();
$('ai-detect').onclick=async()=>{const b=$('ai-detect');b.disabled=true;$('ai-settings-status').textContent='正在检测…';try{const d=await api('ai/models',{endpoint:$('ai-endpoint').value,provider:$('ai-provider').value});$('ai-model').innerHTML=d.models.map(m=>'<option value="'+esc(m.name)+'">'+esc(m.name)+' · '+bytes(m.size)+'</option>').join('')||'<option value="">未找到本地模型</option>';$('ai-settings-status').textContent=d.models.length?'找到 '+d.models.length+' 个本地模型。':'未找到已下载的本地模型。可先在 Ollama 下载对话模型；扫描和清理不受影响。';}catch(e){$('ai-settings-status').textContent=e.message;}finally{b.disabled=false;}};
$('ai-save').onclick=async()=>{try{await api('ai/settings',{endpoint:$('ai-endpoint').value,model:$('ai-model').value,provider:$('ai-provider').value});$('ai-settings-dialog').close();toast('本地 AI 设置已保存。');}catch(e){$('ai-settings-status').textContent=e.message;}};
$('ai-result-close').onclick=()=>{++aiSequence;$('ai-result-dialog').close();};
$('settings-ai-open').onclick=()=>$('ai-settings-open').onclick();
$('settings-permission-open').onclick=()=>{if(typeof window!=='undefined'&&window.webkit?.messageHandlers?.spaceLens){window.webkit.messageHandlers.spaceLens.postMessage('permissions');}else{toast('请在系统设置 → 隐私与安全性 → 完全磁盘访问权限中，添加并开启空间磁盘管家；源码模式请授权使用的终端。');}};
$('settings-project-open').onclick=()=>{if(typeof window==='undefined')return;if(window.webkit?.messageHandlers?.spaceLens){window.webkit.messageHandlers.spaceLens.postMessage('project');}else{window.open('https://github.com/wwwwwwjy/mac-space-lens','_blank','noopener,noreferrer');}};
$('coffee-open').onclick=()=>{$('coffee-alipay').src='/assets/author-alipay.png';$('coffee-wechat').src='/assets/author-wechat.png';$('coffee-dialog').showModal();};
$('coffee-close').onclick=()=>$('coffee-dialog').close();
$('ai-result-dialog').addEventListener('cancel',()=>++aiSequence);
async function explainWithAI(id){const item=state.items.find(x=>x.explain_id===id)||(typeof appState!=='undefined'?appState.rows.find(x=>x.explain_id===id):null);if(!item)return;const sequence=++aiSequence;$('ai-result-name').textContent=item.name;$('ai-result-notice').textContent='根据路径推测，没有读取文件正文，也没有检查工程引用。';$('ai-result-text').textContent='本地模型正在生成解释，首次加载可能较慢…';$('ai-result-dialog').showModal();try{const d=await api('ai/explain',{id});if(sequence!==aiSequence)return;$('ai-result-text').textContent=d.text;$('ai-result-notice').textContent=d.model+' · '+d.notice;}catch(e){if(sequence===aiSequence)$('ai-result-text').textContent=e.message+'\n\n可在左侧“本地 AI”中配置。';}}
let poll=setInterval(()=>status().catch(()=>{}),4000);
(async()=>{try{await status();await loadItems();}catch(e){toast(e.message);$('scan-status').textContent='无法连接本地服务。请退出后重新打开空间磁盘管家；源码模式请重新运行 server.py。';}})();
