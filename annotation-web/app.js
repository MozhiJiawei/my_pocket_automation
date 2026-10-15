const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
let data,cells=[],history=[],ready=false,currentId='',stage='pending',queues={pending:[],confirmed:[]};
const sessionEdits=new Map();
let loadVersion=0,queueVersion=0,confirming=false;
let category='';
const categoryKey=item=>[item.task,item.kind,item.topic].join('/');
const categoryItems=()=>queues[stage].filter(item=>categoryKey(item)===category);
const api=path=>path+'?stage='+stage+'&id='+encodeURIComponent(currentId);
const message=text=>$('status').textContent=text;
const isPuzzle=()=>data?.kind==='拼图'&&data.annotatable;
const puzzle=new PuzzleEditor({api,message,beforeChange:()=>history.push(editorSnapshot()),onChange:()=>{
  sessionEdits.set(currentId,editorSnapshot());updateControls();
}});
function editorSnapshot(){return isPuzzle()?puzzle.snapshot():cells.map(c=>c.yes);}
function updateControls(){
  $('count').textContent=isPuzzle()?puzzle.count:cells.filter(c=>c.yes).length;
  $('undo').disabled=!ready||stage!=='pending'||!history.length;
  $('save').disabled=!ready||stage!=='pending'||!data?.annotatable||(isPuzzle()&&!puzzle.complete);
}
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
function documentAnswers(){if(isPuzzle())return puzzle.answers();const yes={},no={};for(const c of cells)((c.yes?yes:no)[c.image]??=[]).push(c.box);return {正确:{[data.topic]:yes},反例:{[data.topic]:no}};}
function signature(){return JSON.stringify(documentAnswers());}
function showReferences(){
  const catalog=data.references||{说明:'暂无图标参考。',图标:[]};$('reference-note').textContent=catalog.说明;
  const list=$('reference-icons');list.replaceChildren();
  for(const icon of catalog.图标){const figure=document.createElement('figure'),img=document.createElement('img'),caption=document.createElement('figcaption'),link=document.createElement('a');
    img.src=api('/api/reference')+'&name='+encodeURIComponent(icon.图片);img.alt=icon.名称;
    caption.textContent=icon.名称;link.textContent='来源';link.href=icon.来源;link.target='_blank';link.rel='noopener noreferrer';
    figure.append(img,caption);
    for(const [key,value] of Object.entries(icon))if(!['名称','图片','来源','图片来源'].includes(key)&&['string','number','boolean'].includes(typeof value)){
      const detail=document.createElement('small');detail.textContent=key+'：'+value;figure.append(detail);}
    figure.append(link);list.append(figure);}
  $('proposal-note').textContent=data.proposal_note||'';
}
function showCaptureHeight(){
  $('capture-height').hidden=false;
  $('capture-height').textContent=`采集高度：${data.height} / ${data.minimum}像素（${data.height>=data.minimum?'高度达标':'高度不足'}）`;
}
function element(tag,attrs){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e;}
function toggle(index){if(!ready||stage!=='pending')return;history.push(editorSnapshot());cells[index].yes=!cells[index].yes;sessionEdits.set(currentId,editorSnapshot());render();message('尚未完成 · 确认后自动下一项');}
function render(){if(!ready)return;const svg=$('overlay');svg.replaceChildren();
  if(isPuzzle()){puzzle.render();updateControls();return;}
  cells.forEach((c,i)=>{const b=projected(c);if(!b)return;const g=element('g',{class:(c.yes?'cell yes':'cell no')+(stage==='confirmed'?' readonly':''),role:'button',tabindex:stage==='confirmed'?-1:0,'aria-disabled':String(stage==='confirmed'),'aria-label':`物品 ${i+1}：${c.yes?'是':'否'}`,'aria-pressed':String(c.yes),'data-cell':i});
    g.append(element('rect',{x:b[0],y:b[1],width:b[2]-b[0],height:b[3]-b[1],rx:6}));
    g.append(element('rect',{x:b[2]-57,y:b[1]+4,width:52,height:32,rx:4,class:'state-badge'}));
    const t=element('text',{x:b[2]-31,y:b[1]+28,'text-anchor':'middle'});t.textContent=c.yes?'✓ 是':'否';g.append(t);
    g.onclick=()=>toggle(i);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(i);}};svg.append(g);
  });updateControls();
}
function switchView(){if(!ready)return;const view=$('view').value;
  if(isPuzzle()){puzzle.setImage(view);$('title').textContent=view+' · 拖动还原';$('source').textContent='图块来自原图，位置按行排列';render();return;}
  const size=view==='strip'?data.strip.size:data.images.find(i=>i.name===view).size,version=loadVersion;
  $('overlay').style.visibility='hidden';
  $('picture').onload=()=>{if(version!==loadVersion||!ready||isPuzzle())return;render();$('overlay').style.visibility='visible';};
  $('overlay').setAttribute('viewBox',`0 0 ${size[0]} ${size[1]}`);$('picture').src=view==='strip'?api('/api/strip'):api('/api/image')+'&name='+encodeURIComponent(view);
  $('title').textContent=view==='strip'?'整轮长图 · 点击物品切换是／否':view;$('source').textContent='坐标以原图为准';render();
}
$('undo').onclick=()=>{if(ready&&stage==='pending'&&history.length){const previous=history.pop();if(isPuzzle())puzzle.restore(previous);else cells.forEach((c,i)=>c.yes=previous[i]);sessionEdits.set(currentId,editorSnapshot());render();message('已撤销上一步 · 尚未确认');}};
$('view').onchange=switchView;$('zoom').oninput=()=>{$(isPuzzle()?'puzzle-board':'stage').style.width=$('zoom').value+'px';};
function empty(messageText){loadVersion++;ready=false;puzzle.clear();data=null;currentId='';$('capture-height').hidden=true;$('puzzle-workspace').hidden=true;$('stage').hidden=false;$('puzzle-reset').hidden=true;$('heading').textContent=messageText;$('overlay').replaceChildren();$('picture').removeAttribute('src');$('reference-icons').replaceChildren();$('reference-note').textContent='';$('proposal-note').textContent='';$('save').disabled=true;$('undo').disabled=true;$('count').textContent='0';message(messageText);}
function paintQueue(){
  $('pending-count').textContent=queues.pending.length;$('confirmed-count').textContent=queues.confirmed.length;
  $('pending').classList.toggle('chosen',stage==='pending');$('confirmed').classList.toggle('chosen',stage==='confirmed');
  if(!category)category=queues[stage][0]?categoryKey(queues[stage][0]):'';
  const keys=[...new Set([...queues.pending,...queues.confirmed].map(categoryKey))];
  if(category&&!keys.includes(category))keys.push(category);
  $('category').replaceChildren();
  for(const key of keys){const option=document.createElement('option');option.value=key;
    option.textContent=key+'（'+queues[stage].filter(item=>categoryKey(item)===key).length+' 项）';$('category').append(option);}
  $('category').value=category;
  $('round').replaceChildren();
  for(const item of categoryItems()){const option=document.createElement('option');option.value=item.id;
    option.textContent=item.name;$('round').append(option);}
  $('round').disabled=!categoryItems().length||confirming;
  if(categoryItems().some(item=>item.id===currentId))$('round').value=currentId;
}
async function refresh(preferred='',afterConfirmation=false){
  if(confirming&&!afterConfirmation)return;
  const version=++queueVersion,selection=loadVersion,requestedStage=stage,requestedCategory=category;
  const response=await fetch('/api/queue');if(!response.ok)throw Error('队列读取失败');const result=await response.json();
  if(version!==queueVersion||selection!==loadVersion||requestedStage!==stage||requestedCategory!==category||(confirming&&!afterConfirmation))return;
  queues=result;paintQueue();
  const list=categoryItems(),next=list.find(i=>i.id===preferred)||list[0];
  if(next)await load(next.id);else{empty(stage==='pending'?'当前类别已无未完成输入，请选择其它类别':'当前类别暂无已完成数据');$('progress').textContent=category;}
}
async function load(identity){
  // Long-lived tabs must pick up CSS changes when saving or switching inputs.
  $('annotation-style').href='/style.css?v='+Date.now();
  const version=++loadVersion,requestedStage=stage;
  puzzle.setDisabled(true);currentId=identity;$('round').value=identity;ready=false;$('overlay').style.visibility='hidden';$('view').disabled=true;$('save').disabled=true;$('undo').disabled=true;message('正在加载…');
  try{const response=await fetch(api('/api/item'));const result=await response.json();if(!response.ok)throw Error(result.error);
    if(version!==loadVersion||requestedStage!==stage)return;
    data=result;cells=[];history=[];puzzle.clear();$('heading').textContent=data.topic+' · '+(data.kind||'寻物')+' · '+(stage==='pending'?'待确认':'已完成');
    paintQueue();
    showReferences();showCaptureHeight();
    $('puzzle-workspace').hidden=!isPuzzle();$('stage').hidden=isPuzzle();$('item-legend').hidden=isPuzzle();$('puzzle-reset').hidden=!isPuzzle()||stage==='confirmed';
    $('instructions').textContent=!data.annotatable?'这项仅供查看原图，不能确认。具体原因见状态说明。':stage==='confirmed'?'已确认答案只读，可切换原图核对；采集高度见上方。':isPuzzle()?'拖动图块，恢复正确图案。每张原图核对后勾选“本张已还原”，再确认整项。':data.height>=data.minimum?'请选出整轮所有正确物品。确认成功后自动进入当前类别下一项。':'请核对现有原图中的物品；这次确认只覆盖可见区域，不代表题目已采全。';
    $('count-label').textContent=isPuzzle()?'张已还原 / 共 '+data.images.length+' 张':'个“是”';
    $('view-label').textContent=isPuzzle()?'待还原原图':'画面';
    $('reference-heading').textContent=isPuzzle()?'当前题目的参考资料':'当前题目的图标参考';
    $('interaction-hint').textContent=stage==='confirmed'?'归档中的原图及答案供独立核对；本页只读。':isPuzzle()?'拖到另一格时交换两块；移出拼图后松开取消。切换原图、类别或轮次会保留本页编辑。':'直接点击物品切换“是／否”。确认后归档并自动下一项；未完成编辑仅在当前页面保留。';
    $('zoom').max=isPuzzle()?'620':'1100';$('zoom').value=isPuzzle()?'440':'680';
    $(isPuzzle()?'puzzle-board':'stage').style.width=$('zoom').value+'px';
    $('view').replaceChildren();if(!isPuzzle()){const first=document.createElement('option');first.value='strip';first.textContent='整轮长图 · 去重';$('view').append(first);}
    for(const image of data.images){const o=document.createElement('option');o.value=image.name;o.textContent=image.name+' · 原图';$('view').append(o);}
    const snapshot=stage==='pending'?sessionEdits.get(identity):null;
    if(isPuzzle())puzzle.initialize(data,data.initial,snapshot);
    else{for(const a of data.cells){const c=canonical(a);if(c&&!cells.some(b=>same(c,b)))cells.push({...c,yes:false});}
      if(data.annotatable)for(const [image,boxes] of Object.entries(data.initial.正确[data.topic]||{}))for(const box of boxes){const a={image,box},cell=cells.find(c=>same(c,a));if(cell)cell.yes=true;else throw Error('已选位置没有对应完整物品格');}
      if(snapshot)cells.forEach((c,i)=>c.yes=snapshot[i]);}
    $('progress').textContent=`${category} · ${stage==='pending'?'待确认剩余':'归档共'} ${categoryItems().length} 项 · ${data.images.length} 张原图`;
    const hasSuggestions=isPuzzle()?Object.keys(data.suggestions.预期||{}).length>0:Object.values(data.suggestions.正确?.[data.topic]||{}).some(b=>b.length);
    $('advice').textContent=stage==='confirmed'?'已完成归档只读。AI 消费并删除队列文件后，此项会从列表消失。':isPuzzle()?(hasSuggestions?'当前排列含 AI 建议，请核对图案后逐张勾选。':'从原图顺序开始，请实际拖动还原；原图已正确时可直接勾选。'):hasSuggestions?'AI 已预选部分物品为“是”，点击物品反转。':'本项暂无 AI 建议，请点击正确物品置为“是”。';
    ready=true;$('view').disabled=false;if(isPuzzle())puzzle.setDisabled(stage!=='pending');switchView();$('save').hidden=stage==='confirmed';$('skip').hidden=stage==='confirmed';updateControls();
    message(data.limitation||(stage==='pending'?'确认后自动下一项 · 不修改正式真值':'已完成归档 · 可被独立消费或删除'));
  }catch(error){if(version===loadVersion&&requestedStage===stage){empty('加载失败：'+error.message);currentId=identity;}}
}
async function confirmCurrent(){
  if(!ready||stage!=='pending'||!data.annotatable||(isPuzzle()&&!puzzle.complete))return;const identity=currentId,body=signature();
  let archived=false;
  confirming=true;queueVersion++;loadVersion++;
  $('save').disabled=true;$('pending').disabled=true;$('confirmed').disabled=true;$('category').disabled=true;$('round').disabled=true;$('view').disabled=true;$('undo').disabled=true;puzzle.setDisabled(true);ready=false;message('正在确认…');
  try{const response=await fetch(api('/api/confirm'),{method:'POST',headers:{'Content-Type':'application/json','X-Annotation-Token':data.token},body});const result=await response.json();if(!response.ok)throw Error(result.error);
    archived=true;sessionEdits.delete(identity);await refresh('',true);
  }catch(error){if(archived){ready=false;$('save').disabled=true;message('已完成，下一项加载失败，请刷新队列。');}
    else{ready=!!data;if(isPuzzle())puzzle.setDisabled(false);updateControls();message('确认失败：'+error.message+'。当前项保留。');}}
  finally{confirming=false;$('pending').disabled=false;$('confirmed').disabled=false;$('category').disabled=false;$('round').disabled=!categoryItems().length;$('view').disabled=!ready;}
}
$('save').onclick=confirmCurrent;
for(const name of ['pending','confirmed'])$(name).onclick=async()=>{if(confirming)return;stage=name;
  if(!categoryItems().length&&queues[stage].length)category=categoryKey(queues[stage][0]);
  try{await refresh();}catch(error){message(error.message);}};
$('category').onchange=async()=>{if(confirming)return;category=$('category').value;loadVersion++;ready=false;try{await refresh();}catch(error){message(error.message);}};
$('round').onchange=()=>{if(!confirming)load($('round').value);};
$('refresh').onclick=async()=>{if(confirming)return;try{await refresh(currentId);}catch(error){message(error.message);}};
$('skip').onclick=async()=>{if(confirming||stage!=='pending')return;const list=categoryItems(),index=list.findIndex(i=>i.id===currentId);
  if(list.length>1)await load(list[(index+1)%list.length].id);else message('当前项仍待确认，此类别暂无其它项');};
// Poll only the file-backed lists; external deletion must invalidate the display.
setInterval(async()=>{if(confirming)return;const version=queueVersion,selection=loadVersion,requestedStage=stage;try{const response=await fetch('/api/queue');if(!response.ok)return;const next=await response.json();
  if(confirming||version!==queueVersion||selection!==loadVersion||requestedStage!==stage)return;
  if(JSON.stringify(next)!==JSON.stringify(queues)){queues=next;paintQueue();if(!queues[stage].some(i=>i.id===currentId))await refresh();}
}catch{}},3000);
refresh().catch(error=>empty(error.message));
