const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'web/index.html'),'utf8'),elements=new Map();
function element(){return{value:'',checked:false,disabled:false,hidden:false,style:{},dataset:{},handlers:{},parentElement:{hidden:false},classList:{toggle(){}},addEventListener(t,f){this.handlers[t]=f},showModal(){this.open=true},close(){this.open=false}};}
for(const m of html.matchAll(/id="([^"]+)"/g))elements.set(m[1],element());
elements.set('model-service1',element());elements.get('model-service1').value='local-model';
const requests=[],ring=element();let installed=true,cleared=false,confirmed=false;
const app={id:'app1',name:'Example',identifier:'org.example.app',path:'/Applications/Example.app',blocked:'',icon:'data:image/png;base64,iVBORw0KGgo='};
const rows=[{id:'r1',explain_id:'er1',name:'org.example.app',path:'/fixture/Library/Caches/org.example.app',bytes:100,deletable:true,kind:'缓存',impact:'重新下载',basis:'完整匹配标识',risk:'caution'},{id:null,explain_id:'er2',name:'Shared',path:'/fixture/Library/Group Containers/Shared',bytes:100,deletable:false,kind:'共享目录',blocked:'共享数据',risk:'protected'}];
rows.push({id:'r3',explain_id:'er3',name:'Example',path:'/fixture/Library/Application Support/Example',bytes:200,deletable:true,kind:'应用支持数据',impact:'本地资料与设置会删除',basis:'完整软件名匹配',risk:'caution',needs_ownership_confirmation:true});
const context=vm.createContext({document:{getElementById(id){assert.ok(elements.has(id),'Missing '+id);return elements.get(id)},querySelectorAll(){return[]},querySelector(){return ring},addEventListener(){}},location:{hash:'#fixture',pathname:'/'},history:{replaceState(){}},sessionStorage:{getItem(){return null},setItem(){}},setInterval(){return 1},clearInterval(){},setTimeout(){return 1},clearTimeout(){},console,fetch:async(url,options)=>{
 const body=options.body?JSON.parse(options.body):null;requests.push({url,body});let data={};
 if(url==='/api/status')data={home:'/fixture',scan:{running:false,done:true,finished:1,errors:0},disk:{free:1,total:10,used:9},roots:[]};
 else if(url.startsWith('/api/items'))data={items:[]};
 else if(url==='/api/apps')data={items:installed?[app]:[],warnings:[]};
 else if(url==='/api/apps/preview')data={ticket:'uninstall-ticket',app,bytes:100,items:[{path:app.path,bytes:100}],impact:'卸载后自动检索残留'};
 else if(url==='/api/apps/uninstall'){installed=false;data={moved:[{path:app.path}],failed:[],target:{id:'target1'}};}
 else if(url==='/api/apps/orphans')data={items:[{id:'old1',name:'旧应用',identifier:'org.old.app',needs_confirmation:true}],warnings:[]};
 else if(url==='/api/apps/leftovers'){if(body.confirm_absent)confirmed=true;data={target:{id:body.id,name:'Example',identifier:'org.example.app',needs_confirmation:body.id==='old1'&&!confirmed},items:cleared?[]:rows,notice:'人工核对',warnings:[]};}
 else if(url==='/api/apps/residual-preview'){const selected=rows.filter(x=>body.ids.includes(x.id));data={ticket:'residual-ticket',items:selected,bytes:300,needs_ownership_confirmation:selected.some(x=>x.needs_ownership_confirmation),ownership_paths:selected.filter(x=>x.needs_ownership_confirmation).map(x=>x.path)};}
 else if(url==='/api/apps/residual-trash'){assert.equal(body.ownership_ack,true);cleared=true;data={moved:[{path:rows[0].path},{path:rows[2].path}],failed:[]};}
 else if(url==='/api/ai/discover')data={clients:[{name:'ChatGPT',installed:true,local_engine:false,notice:'未提供客户端调用接口'}],services:[{id:'service1',provider:'ollama',name:'Ollama',endpoint:'http://127.0.0.1:11434',available:true,models:[{name:'local-model'}],message:'可关联'}],notice:'仅本地服务'};
 else if(url==='/api/ai/connect')data={provider:'ollama',endpoint:'http://127.0.0.1:11434',model:'local-model'};
 return{ok:true,json:async()=>data};}});
const run=code=>vm.runInContext(code,context);
(async()=>{
 run(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));run(fs.readFileSync(path.join(root,'web/applications.js'),'utf8'));await new Promise(r=>setImmediate(r));
 assert.equal(requests.some(x=>x.url==='/api/scan'||x.url==='/api/apps'),false,'Startup is idle');
 await run("view('applications')");assert.equal(elements.get('files-section').hidden,true);assert.equal(elements.get('apps-section').hidden,false);
 assert.equal(requests.some(x=>x.url==='/api/apps'),false,'Entering software page waits for click');
 assert.equal(elements.get('scan').textContent,'开始扫描');
 await elements.get('scan').onclick();
 assert.equal(requests.filter(x=>x.url==='/api/apps').length,1);
 assert.equal(requests.some(x=>x.url==='/api/scan'||x.url==='/api/apps/orphans'),false,'Software scan must not trigger full scan or residue search');
 assert.match(elements.get('app-list').innerHTML,/img class="app-icon"/);
 assert.match(elements.get('app-list').innerHTML,/Example图标/);
 await run("view('overview')");await run("view('applications')");
 assert.equal(requests.filter(x=>x.url==='/api/apps').length,1,'Switching tabs uses cached app list');
 await run("prepareUninstall('app1')");assert.equal(elements.get('app-confirm-dialog').open,true);assert.equal(elements.get('app-confirm-commit').disabled,true);
 elements.get('app-confirm-ack').checked=true;elements.get('app-confirm-ack').onchange();assert.equal(elements.get('app-confirm-commit').disabled,true,'App name still required');
 elements.get('app-confirm-name').value='Example';elements.get('app-confirm-name').oninput();assert.equal(elements.get('app-confirm-commit').disabled,false);
 elements.get('app-confirm-cancel').onclick();assert.equal(requests.filter(x=>x.url==='/api/apps/uninstall').length,0,'Cancel must not uninstall');
 await run("prepareUninstall('app1')");elements.get('app-confirm-name').value='Example';elements.get('app-confirm-ack').checked=true;elements.get('app-confirm-ack').onchange();await elements.get('app-confirm-commit').onclick();
 assert.equal(requests.find(x=>x.url==='/api/apps/uninstall').body.confirm_name,'Example');assert.equal(run('appState.selected.size'),0,'Residuals default unchecked');
 assert.equal(requests.filter(x=>x.url==='/api/apps/residual-trash').length,0,'No automatic residual deletion');assert.equal(run('state.view'),'applications');assert.equal(elements.get('residual-panel').hidden,false);
 elements.get('residual-all').checked=true;elements.get('residual-all').onchange();assert.equal(run('appState.selected.size'),2,'Named row selectable; shared row cannot be selected');
 await run('prepareResiduals()');assert.equal(elements.get('app-confirm-commit').disabled,true,'Separate confirmation for residues');
 elements.get('app-confirm-ack').checked=true;elements.get('app-confirm-ack').onchange();assert.equal(elements.get('app-confirm-commit').disabled,true,'Ownership confirmation still required');assert.equal(elements.get('app-ownership-wrap').hidden,false);await elements.get('app-confirm-commit').onclick();assert.equal(requests.some(x=>x.url==='/api/apps/residual-trash'),false,'Cannot skip ownership confirmation');elements.get('app-ownership-ack').checked=true;elements.get('app-ownership-ack').onchange();assert.equal(elements.get('app-confirm-commit').disabled,false);await elements.get('app-confirm-commit').onclick();assert.equal(run('state.view'),'applications');assert.equal(elements.get('result-title').textContent,'已移入废纸篓');
 await run("view('orphans')");await run("loadLeftovers('old1')");assert.equal(elements.get('residual-absent').hidden,false);assert.equal(elements.get('residual-confirm-absent').disabled,true);
 elements.get('residual-absent-ack').checked=true;elements.get('residual-absent-ack').onchange();await elements.get('residual-confirm-absent').onclick();assert.equal(elements.get('residual-absent').hidden,true);assert.equal(requests.at(-1).body.confirm_absent,true);
 await run('discoverAI()');assert.match(elements.get('ai-clients').innerHTML,/已发现客户端/);assert.doesNotMatch(elements.get('ai-clients').innerHTML,/data-ai-connect/);await run("connectDiscoveredAI('service1')");assert.equal(requests.at(-1).body.model,'local-model');
 assert.equal(requests.filter(x=>x.url==='/api/history').length,0,'No redirect to recovery history');
 console.log('PASS: uninstall identity confirmation, cancel, automatic discovery without deletion, residue selection, separate confirmation, inline results, AI service connection.');
})().catch(e=>{console.error(e);process.exitCode=1});
