const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
let data,cells=[],history=[],ready=false,currentId='',stage='pending',queues={pending:[],confirmed:[]};
const sessionEdits=new Map();
let loadVersion=0,confirming=false;
const api=path=>path+'?stage='+stage+'&id='+encodeURIComponent(currentId);
const message=text=>$('status').textContent=text;
function inside(b,p){return p[0]>=b[0]&&p[0]<b[2]&&p[1]>=b[1]&&p[1]<b[3];}
function contains(a,b){return b[0]>=a[0]&&b[1]>=a[1]&&b[2]<=a[2]&&b[3]<=a[3];}
function shift(b,x,y){return [b[0]+x,b[1]+y,b[2]+x,b[3]+y];}
function center(b){return [(b[0]+b[2])/2,(b[1]+b[3])/2];}
function mapping(a){for(const layer of data.strip.layers)for(const source of layer.aliases||[{image:layer.image,source:layer.source}])
  if(source.image===a.image&&contains(source.source,a.box))return {layer,source};return null;}
function stripBox(a){const m=mapping(a);return m?shift(a.box,m.layer.destination[0]-m.source.source[0],m.layer.destination[1]-m.source.source[1]):null;}
function canonical(a){const m=mapping(a);if(!m)return null;const b=stripBox(a),layer=m.layer;
  return {image:layer.image,box:shift(b,layer.source[0]-layer.destination[0],layer.source[1]-layer.destination[1]).map(Math.round)};
}
function same(a,b){const x=stripBox(a),y=stripBox(b);if(!x||!y)return false;const p=center(x),q=center(y);return Math.abs(p[0]-q[0])<25&&Math.abs(p[1]-q[1])<25;}
function projected(a){const view=$('view').value;if(view==='strip')return stripBox(a);if(a.image===view)return a.box;
  const m=mapping(a);if(!m)return null;const source=(m.layer.aliases||[]).find(s=>s.image===view);if(!source)return null;
  const b=stripBox(a);return shift(b,source.source[0]-m.layer.destination[0],source.source[1]-m.layer.destination[1]);
}
function documentAnswers(){const yes={},no={};for(const c of cells)((c.yes?yes:no)[c.image]??=[]).push(c.box);return {正确:{[data.topic]:yes},反例:{[data.topic]:no}};}
function signature(){return JSON.stringify(documentAnswers());}
function element(tag,attrs){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e;}
function toggle(index){if(!ready||stage!=='pending')return;history.push(cells.map(c=>c.yes));cells[index].yes=!cells[index].yes;sessionEdits.set(currentId,documentAnswers());render();message('尚未完成 · 确认后自动下一项');}
function render(){if(!ready)return;const svg=$('overlay');svg.replaceChildren();
  cells.forEach((c,i)=>{const b=projected(c);if(!b)return;const g=element('g',{class:(c.yes?'cell yes':'cell no')+(stage==='confirmed'?' readonly':''),role:'button',tabindex:stage==='confirmed'?-1:0,'aria-disabled':String(stage==='confirmed'),'aria-label':`物品 ${i+1}：${c.yes?'是':'否'}`,'aria-pressed':String(c.yes),'data-cell':i});
    g.append(element('rect',{x:b[0],y:b[1],width:b[2]-b[0],height:b[3]-b[1],rx:6}));
    g.append(element('rect',{x:b[2]-31,y:b[1]+3,width:28,height:25,rx:4,class:'state-badge'}));
    const t=element('text',{x:b[2]-17,y:b[1]+21,'text-anchor':'middle'});t.textContent=c.yes?'是':'否';g.append(t);
    g.onclick=()=>toggle(i);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(i);}};svg.append(g);
  });$('count').textContent=cells.filter(c=>c.yes).length;$('undo').disabled=!history.length;
}
function switchView(){const view=$('view').value,size=view==='strip'?data.strip.size:data.images.find(i=>i.name===view).size;
  $('overlay').style.visibility='hidden';$('picture').onload=()=>{render();$('overlay').style.visibility='visible';};
  $('overlay').setAttribute('viewBox',`0 0 ${size[0]} ${size[1]}`);$('picture').src=view==='strip'?api('/api/strip'):api('/api/image')+'&name='+encodeURIComponent(view);
  $('title').textContent=view==='strip'?'整轮长图 · 点击物品切换是／否':view;$('source').textContent='坐标以原图为准';render();
}
$('undo').onclick=()=>{if(stage==='pending'&&history.length){const previous=history.pop();cells.forEach((c,i)=>c.yes=previous[i]);sessionEdits.set(currentId,documentAnswers());render();message('尚未完成');}};
$('view').onchange=switchView;$('zoom').oninput=()=>{$('stage').style.width=$('zoom').value+'px';};
function empty(messageText){loadVersion++;ready=false;data=null;currentId='';$('heading').textContent=messageText;$('overlay').replaceChildren();$('picture').removeAttribute('src');$('save').disabled=true;$('undo').disabled=true;$('count').textContent='0';message(messageText);}
function paintQueue(){
  $('pending-count').textContent=queues.pending.length;$('confirmed-count').textContent=queues.confirmed.length;
  $('pending').classList.toggle('chosen',stage==='pending');$('confirmed').classList.toggle('chosen',stage==='confirmed');
  const list=$('archive-list');list.replaceChildren();
  if(stage==='confirmed')for(const item of queues.confirmed){const b=document.createElement('button');b.textContent=item.topic+' · '+item.name;b.className='archive-item';b.onclick=()=>load(item.id);list.append(b);}
}
async function refresh(preferred=''){
  const response=await fetch('/api/queue');if(!response.ok)throw Error('队列读取失败');queues=await response.json();paintQueue();
  const list=queues[stage],next=list.find(i=>i.id===preferred)||list[0];
  if(next)await load(next.id);else empty(stage==='pending'?'未完成队列已清空':'暂无已完成数据');
}
async function load(identity){
  const version=++loadVersion,requestedStage=stage;
  currentId=identity;ready=false;$('overlay').style.visibility='hidden';$('save').disabled=true;message('正在加载…');
  try{const response=await fetch(api('/api/item'));const result=await response.json();if(!response.ok)throw Error(result.error);
    if(version!==loadVersion||requestedStage!==stage)return;
    data=result;cells=[];history=[];$('heading').textContent=data.topic+' · '+(stage==='pending'?'待确认':'已完成');
    $('view').replaceChildren();const first=document.createElement('option');first.value='strip';first.textContent='整轮长图 · 去重';$('view').append(first);
    for(const image of data.images){const o=document.createElement('option');o.value=image.name;o.textContent=image.name+' · 原图';$('view').append(o);}
    for(const a of data.cells){const c=canonical(a);if(c&&!cells.some(b=>same(c,b)))cells.push({...c,yes:false});}
    const initial=stage==='pending'?(sessionEdits.get(identity)||data.initial):data.initial;
    if(data.annotatable)for(const [image,boxes] of Object.entries(initial.正确[data.topic]||{}))for(const box of boxes){const a={image,box},cell=cells.find(c=>same(c,a));if(cell)cell.yes=true;else throw Error('已选位置没有对应完整物品格');}
    $('progress').textContent=`${stage==='pending'?'待确认剩余':'归档共'} ${queues[stage].length} 项 · ${data.images.length} 张原图`;
    const hasSuggestions=Object.values(data.suggestions.正确[data.topic]||{}).some(b=>b.length);
    $('advice').textContent=stage==='confirmed'?'已完成归档只读。AI 消费并删除队列文件后，此项会从列表消失。':hasSuggestions?'AI 已预选部分物品为“是”，点击物品反转。':'本项暂无 AI 建议，请点击正确物品置为“是”。';
    ready=true;switchView();$('save').hidden=stage==='confirmed';$('skip').hidden=stage==='confirmed';$('save').disabled=stage!=='pending'||!data.annotatable;
    message(data.limitation||(stage==='pending'?'确认后自动下一项 · 不修改正式真值':'已完成归档 · 可被独立消费或删除'));
  }catch(error){if(version===loadVersion&&requestedStage===stage){empty('加载失败：'+error.message);currentId=identity;}}
}
async function confirmCurrent(){
  if(!ready||stage!=='pending'||!data.annotatable)return;const identity=currentId,body=signature();
  let archived=false;
  confirming=true;
  $('save').disabled=true;$('pending').disabled=true;$('confirmed').disabled=true;ready=false;message('正在确认…');
  try{const response=await fetch(api('/api/confirm'),{method:'POST',headers:{'Content-Type':'application/json','X-Annotation-Token':data.token},body});const result=await response.json();if(!response.ok)throw Error(result.error);
    archived=true;sessionEdits.delete(identity);await refresh();
  }catch(error){if(archived){ready=false;$('save').disabled=true;message('已完成，下一项加载失败，请刷新队列。');}
    else{ready=!!data;$('save').disabled=false;message('确认失败：'+error.message+'。当前项保留。');}}
  finally{confirming=false;$('pending').disabled=false;$('confirmed').disabled=false;}
}
$('save').onclick=confirmCurrent;
for(const name of ['pending','confirmed'])$(name).onclick=async()=>{stage=name;try{await refresh();}catch(error){message(error.message);}};
$('refresh').onclick=async()=>{try{await refresh(currentId);}catch(error){message(error.message);}};
$('skip').onclick=async()=>{if(confirming||stage!=='pending')return;const index=queues.pending.findIndex(i=>i.id===currentId);
  if(queues.pending.length>1)await load(queues.pending[(index+1)%queues.pending.length].id);else message('当前项仍待确认，暂无其它项');};
// Poll only the file-backed lists; external deletion must invalidate the display.
setInterval(async()=>{if(confirming)return;try{const response=await fetch('/api/queue');if(!response.ok)return;const next=await response.json();
  if(JSON.stringify(next)!==JSON.stringify(queues)){queues=next;paintQueue();if(!queues[stage].some(i=>i.id===currentId))await refresh();}
}catch{}},3000);
refresh().catch(error=>empty(error.message));
