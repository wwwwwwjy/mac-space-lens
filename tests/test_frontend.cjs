// Headless code-level interaction tests (not a replacement for visual browser QA).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
function element() {
  return {value:'', checked:false, disabled:false, hidden:false, style:{}, dataset:{}, handlers:{},
    parentElement:{hidden:false}, classList:{toggle(){}},
    addEventListener(type, fn){this.handlers[type]=fn;},
    showModal(){this.open=true;},close(){this.open=false;}};
}
const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1], element()]));
const buttons = Array.from({length:4},element);
const ring = element(), requests = [];
const originalItems = [
  {id:'a',explain_id:'explain-a',path:'/fixture/a',name:'a',bytes:1024,logical:1024,deletable:true,risk:'recommended'},
  {id:'b',path:'/fixture/b',name:'b',bytes:2048,logical:2048,deletable:true,risk:'review'},
  {id:null,path:'/fixture/protected',name:'protected',bytes:4096,logical:4096,deletable:false,risk:'protected'},
];
let items=[...originalItems];
const context = vm.createContext({
  document:{
    getElementById(id){assert.ok(elements.has(id),'Missing element: '+id);return elements.get(id);},
    querySelectorAll(selector){return selector==='[data-operation]'?buttons:[];},
    querySelector(){return ring;},addEventListener(){}
  },
  location:{hash:'#fixture-token',pathname:'/'},
  history:{replaceState(){}},sessionStorage:{getItem(){return null;},setItem(){}},
  setTimeout(){return 1;},clearTimeout(){},setInterval(){return 1;},clearInterval(){},
  console,
  fetch:async(url, options)=>{
    const body=options.body?JSON.parse(options.body):null;
    requests.push({url,body});
    let data={};
    if(url==='/api/status')data={home:'/fixture',scan:{done:true,running:false,finished:1,errors:0},disk:{free:1,total:10,used:9},roots:[]};
    else if(url.startsWith('/api/items'))data={items};
    else if(url.startsWith('/api/browse'))data={items,total:items.length};
    else if(url==='/api/preview')data={ticket:'ticket',items:items.filter(i=>body.ids.includes(i.id)),bytes:3072,operation:body.operation,caution:false};
    else if(url==='/api/delete'){items=items.filter(x=>!['a','b'].includes(x.id));data={deleted:[{path:'/fixture/a'},{path:'/fixture/b'}],failed:[]};}
    else if(url==='/api/trash'){items=items.filter(x=>x.id!=='a');data={moved:[{path:'/fixture/a'}],failed:[]};}
    else if(url==='/api/history')data={items:[]};
    else if(url==='/api/ai/settings')data={endpoint:'http://127.0.0.1:11434',model:'fixture:small'};
    else if(url==='/api/ai/models')data={models:[{name:'fixture:small',size:20000000}]};
    else if(url==='/api/ai/explain')data={text:'<script>untrusted model output</script>',model:'fixture:small',notice:'仅供核对'};
    return {ok:true,json:async()=>data};
  }
});
const evaluate = code=>vm.runInContext(code,context);
(async()=>{
  vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.get('select-all').disabled,false);
  await elements.get('ai-settings-open').onclick();
  assert.equal(elements.get('ai-settings-dialog').open,true);
  await elements.get('ai-detect').onclick();
  assert.match(elements.get('ai-model').innerHTML,/fixture:small/);
  elements.get('ai-settings-close').onclick();
  await evaluate("explainWithAI('explain-a')");
  assert.equal(elements.get('ai-result-text').textContent,'<script>untrusted model output</script>','Render model output as text');
  assert.equal(evaluate("state.items[0].risk"),'recommended','AI must not change deletion classifications');
  assert.equal(requests.filter(r=>['/api/delete','/api/trash','/api/preview'].includes(r.url)).length,0,'Explaining a file must never start an action');
  elements.get('ai-result-close').onclick();
  elements.get('select-all').checked=true;
  elements.get('select-all').onchange();
  assert.equal(evaluate('state.selection.size'),2,'Select all must skip protected items');
  assert.equal(elements.get('select-all').indeterminate,false);
  elements.get('rows').handlers.change({target:{matches:()=>true,dataset:{select:'/fixture/a'},checked:false}});
  assert.equal(elements.get('select-all').indeterminate,true);
  elements.get('select-all').checked=false;
  elements.get('select-all').onchange();
  assert.equal(evaluate('state.selection.size'),0);
  elements.get('select-all').checked=true;
  elements.get('select-all').onchange();
  await evaluate("previewAction('delete')");
  assert.equal(elements.get('confirm-dialog').open,true);
  assert.equal(elements.get('commit').disabled,true,'Permanent delete must require typed confirmation');
  elements.get('delete-confirm-text').value='删除';
  elements.get('delete-confirm-text').oninput();
  assert.equal(elements.get('commit').disabled,true);
  elements.get('delete-confirm-text').value='永久删除';
  elements.get('delete-confirm-text').oninput();
  assert.equal(elements.get('commit').disabled,false);
  elements.get('search').value='keep-search';
  await elements.get('commit').onclick();
  assert.equal(requests.find(r=>r.url==='/api/delete').body.confirm_text,'永久删除');
  assert.equal(evaluate('state.selection.size'),0);
  assert.equal(evaluate('state.view'),'overview','Deletion must not navigate to history');
  assert.equal(elements.get('search').value,'keep-search','Keep the search in place');
  assert.equal(evaluate('state.items.length'),1,'Refresh the list after deleting');
  assert.equal(elements.get('result-title').textContent,'删除完成');
  assert.equal(requests.filter(r=>r.url==='/api/history').length,0);
  items=[originalItems[0], originalItems[2]];
  await evaluate("view('browse','/fixture')");
  elements.get('select-all').checked=true;
  elements.get('select-all').onchange();
  await evaluate("previewAction('trash')");
  assert.equal(elements.get('delete-confirm-wrap').hidden,true);
  assert.equal(elements.get('commit').disabled,false);
  assert.equal(elements.get('commit').textContent,'确认移到废纸篓');
  elements.get('cancel-confirm').onclick();
  assert.equal(elements.get('confirm-dialog').open,false);
  assert.equal(requests.filter(r=>r.url==='/api/trash').length,0,'Cancel must not move any files');
  await evaluate("previewAction('trash')");
  await elements.get('commit').onclick();
  assert.equal(evaluate('state.view'),'browse','Trash must not navigate away from the current folder');
  assert.equal(evaluate('state.path'),'/fixture');
  assert.equal(elements.get('result-title').textContent,'已移入废纸篓');
  assert.equal(requests.filter(r=>r.url==='/api/history').length,0);
  console.log('PASS: selection, confirmations, cancellation, inline success, list refresh and staying on the current view.');
})().catch(e=>{console.error(e);process.exitCode=1;});
