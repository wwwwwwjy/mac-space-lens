const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
function element(){return{value:'',checked:false,disabled:false,hidden:false,style:{},dataset:{},parentElement:{hidden:false},classList:{toggle(){}},handlers:{},addEventListener(k,v){this.handlers[k]=v},showModal(){this.open=true},close(){this.open=false}};}
const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(x=>[x[1],element()])),requests=[],ring=element();
const context=vm.createContext({document:{getElementById(id){assert.ok(elements.has(id),'Missing '+id);return elements.get(id)},querySelectorAll(){return[]},querySelector(){return ring},addEventListener(){}},location:{hash:'#fixture',pathname:'/'},history:{replaceState(){}},sessionStorage:{getItem(){return null},setItem(){}},setInterval(){return 1},clearInterval(){},setTimeout(){return 1},clearTimeout(){},console,fetch:async(url,options)=>{requests.push(url);return{ok:true,json:async()=>url==='/api/status'?{home:'/fixture',scan:{running:false,done:false,errors:0},disk:{free:1,used:1,total:2},roots:[]}:{items:[]}}}});
const run=code=>vm.runInContext(code,context);
(async()=>{
    run(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));await new Promise(r=>setImmediate(r));
    for(const id of ['coffee-alipay','coffee-wechat']){
        assert.equal(elements.get(id).src,undefined,'No receipt requested at startup');
        const tag=html.match(new RegExp('<img[^>]*id="'+id+'"[^>]*>'))[0];
        assert.doesNotMatch(tag,/\ssrc=/,'No eager image source');
    }
    const before=requests.length;
    await run("view('settings')");
    assert.equal(elements.get('settings-section').hidden,false);
    assert.equal(elements.get('files-section').hidden,true);
    assert.equal(elements.get('scan').hidden,true);
    assert.equal(requests.length,before,'Entering settings does not scan or discover services');
    assert.equal(elements.get('coffee-dialog').open,undefined);
    elements.get('coffee-open').onclick();
    assert.equal(elements.get('coffee-dialog').open,true);
    assert.equal(elements.get('coffee-alipay').src,'/assets/author-alipay.png');
    assert.equal(elements.get('coffee-wechat').src,'/assets/author-wechat.png');
    assert.equal(requests.length,before,'Opening receipts performs no API mutation');
    const panel=html.match(/<dialog id="coffee-dialog"[\s\S]*?<\/dialog>/)[0];
    assert.doesNotMatch(panel,/<input|<select|<textarea|contenteditable=/);
    assert.match(panel,/支付宝/);assert.match(panel,/微信/);
    elements.get('coffee-close').onclick();
    assert.equal(elements.get('coffee-dialog').open,false);
    assert.equal(run('state.view'),'settings');
    await run("view('overview')");assert.equal(elements.get('settings-section').hidden,true);assert.equal(elements.get('scan').hidden,false);
    console.log('PASS: settings waits, receipts load only on click, fixed QR resources, no editable payment settings, closing preserves current page.');
})().catch(e=>{console.error(e);process.exitCode=1});
