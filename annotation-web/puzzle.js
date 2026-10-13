/* The puzzle editor owns tile interaction; app.js owns queue and confirmation. */
class PuzzleEditor {
  constructor({api,beforeChange,onChange,message}) {
    Object.assign(this,{api,beforeChange,onChange,message});
    this.canvas=document.getElementById('puzzle-canvas');
    this.canvas.onpointerdown=e=>this.startDrag(e);
    this.canvas.onpointermove=e=>this.moveDrag(e);
    this.canvas.onpointerup=e=>this.finishDrag(e);
    this.canvas.onpointercancel=()=>this.cancelDrag();
    this.canvas.onlostpointercapture=()=>this.cancelDrag();
    this.canvas.onkeydown=e=>this.keydown(e);
    document.getElementById('puzzle-labels').onchange=()=>this.render();
    document.getElementById('puzzle-reviewed').onchange=e=>{
      if(this.disabled)return;
      this.beforeChange();this.reviewed[this.image]=e.target.checked;this.onChange();this.render();
    };
    document.getElementById('puzzle-reset').onclick=()=>{
      if(this.disabled)return;
      this.beforeChange();this.orders[this.image]=[0,1,2,3];this.reviewed[this.image]=false;
      this.onChange();this.render();this.message('已恢复本张原图顺序，请重新核对。');
    };
  }
  initialize(data,initial,snapshot) {
    this.clear();this.data=data;this.orders={};this.reviewed={};this.disabled=true;
    for(const image of data.images) {
      const value=initial.预期?.[image.name]?.[data.puzzle.field];
      this.orders[image.name]=value?(typeof value==='string'?[...value].map(c=>c.charCodeAt(0)-65):value.map(n=>n-1)):[0,1,2,3];
      // AI suggestions are arrangements to inspect; only archives are reviewed.
      this.reviewed[image.name]=data.stage==='confirmed';
    }
    if(snapshot)this.restore(snapshot);
  }
  snapshot() {return structuredClone({orders:this.orders,reviewed:this.reviewed});}
  restore(snapshot) {
    this.cancelDrag();this.orders=structuredClone(snapshot.orders);this.reviewed={...snapshot.reviewed};
  }
  answers() {
    const expected={};
    for(const image of this.data.images)if(this.reviewed[image.name]) {
      const order=this.orders[image.name];
      expected[image.name]={[this.data.puzzle.field]:this.data.puzzle.field==='puzzle_order'?order.map(n=>'ABCD'[n]).join(''):order.map(n=>n+1)};
    }
    return {预期:expected};
  }
  get complete() {return this.data.images.every(i=>this.reviewed[i.name]);}
  get count() {return this.data.images.filter(i=>this.reviewed[i.name]).length;}
  setDisabled(value) {this.disabled=value;this.cancelDrag();this.render();}
  setImage(name) {
    this.cancelDrag();this.image=name;const image=this.data.images.find(i=>i.name===name);
    const src=this.api('/api/image')+'&name='+encodeURIComponent(name);
    document.getElementById('puzzle-original-image').src=src;
    const labels=document.getElementById('puzzle-original-labels');labels.replaceChildren();
    labels.setAttribute('viewBox',`0 0 ${image.size[0]} ${image.size[1]}`);
    this.data.puzzle.cells.forEach((box,i)=>labels.append(this.badge('ABCD'[i],box[0]+8,box[1]+8)));
    const box=this.data.puzzle.cells[0];this.width=box[2]-box[0];this.height=box[3]-box[1];
    this.canvas.setAttribute('viewBox',`0 0 ${this.width*2} ${this.height*2}`);
    this.render();
  }
  svg(tag,attributes={}) {
    const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const [key,value] of Object.entries(attributes))node.setAttribute(key,value);
    return node;
  }
  badge(text,x,y) {
    const group=this.svg('g',{class:'puzzle-badge',transform:`translate(${x} ${y})`});
    group.append(this.svg('rect',{width:36,height:32,rx:4}));
    const label=this.svg('text',{x:18,y:23,'text-anchor':'middle'});label.textContent=text;group.append(label);return group;
  }
  tile(piece,slot) {
    const box=this.data.puzzle.cells[piece],image=this.data.images.find(i=>i.name===this.image);
    const group=this.svg('g',{'data-slot':slot,role:'button',tabindex:this.disabled?-1:0,
      'aria-disabled':String(this.disabled),'aria-label':`${['左上','右上','左下','右下'][slot]}格：原图块 ${'ABCD'[piece]}`,
      'aria-pressed':String(this.selected===slot),transform:`translate(${slot%2*this.width} ${Math.floor(slot/2)*this.height})`});
    const crop=this.svg('svg',{width:this.width,height:this.height,viewBox:box.join(' '),overflow:'hidden'});
    // viewBox takes x/y/width/height, while source boxes use endpoints.
    crop.setAttribute('viewBox',`${box[0]} ${box[1]} ${this.width} ${this.height}`);
    crop.append(this.svg('image',{href:this.api('/api/image')+'&name='+encodeURIComponent(this.image),width:image.size[0],height:image.size[1]}));
    group.append(crop,this.svg('rect',{class:'puzzle-edge',width:this.width,height:this.height}));
    if(document.getElementById('puzzle-labels').checked)group.append(this.badge('ABCD'[piece],8,8));
    if(this.selected===slot)group.classList.add('selected');return group;
  }
  render() {
    if(!this.data||!this.image)return;
    this.canvas.replaceChildren();this.orders[this.image].forEach((piece,slot)=>this.canvas.append(this.tile(piece,slot)));
    this.canvas.classList.toggle('readonly',this.disabled);
    const check=document.getElementById('puzzle-reviewed');check.checked=!!this.reviewed[this.image];check.disabled=this.disabled;
    document.getElementById('puzzle-reset').disabled=this.disabled;
    document.getElementById('puzzle-page-state').textContent=this.reviewed[this.image]?'已核对':'待核对';
    document.getElementById('puzzle-order').textContent='目标顺序（左上 → 右上 → 左下 → 右下）：'+this.orders[this.image].map(n=>'ABCD'[n]).join(' · ');
  }
  position(event) {
    const rect=this.canvas.getBoundingClientRect();
    return [(event.clientX-rect.left)*this.width*2/rect.width,(event.clientY-rect.top)*this.height*2/rect.height];
  }
  slotAt([x,y]) {return x>=0&&x<this.width*2&&y>=0&&y<this.height*2?Math.floor(y/this.height)*2+Math.floor(x/this.width):-1;}
  startDrag(event) {
    if(this.disabled||event.button!==0||this.drag)return;
    const slot=this.slotAt(this.position(event));if(slot<0)return;
    event.preventDefault();this.selected=null;
    const tile=this.canvas.children[slot],ghost=tile.cloneNode(true);
    ghost.removeAttribute('tabindex');ghost.removeAttribute('role');ghost.removeAttribute('data-slot');ghost.setAttribute('aria-hidden','true');ghost.classList.add('puzzle-drag');
    this.canvas.append(ghost);tile.classList.add('drag-origin');
    this.drag={slot,start:this.position(event),ghost,pointer:event.pointerId};this.canvas.setPointerCapture(event.pointerId);
    this.canvas.focus();
  }
  moveDrag(event) {
    if(!this.drag||event.pointerId!==this.drag.pointer)return;
    const point=this.position(event),{slot,start,ghost}=this.drag;
    ghost.setAttribute('transform',`translate(${slot%2*this.width+point[0]-start[0]} ${Math.floor(slot/2)*this.height+point[1]-start[1]})`);
    const target=this.slotAt(point);Array.from(this.canvas.children).slice(0,4).forEach((tile,i)=>tile.classList.toggle('drop-target',i===target&&i!==slot));
  }
  finishDrag(event) {
    if(!this.drag||event.pointerId!==this.drag.pointer)return;
    const source=this.drag.slot,target=this.slotAt(this.position(event));this.cancelDrag();
    if(target>=0&&target!==source)this.swap(source,target);else this.render();
  }
  cancelDrag() {
    if(this.drag){const pointer=this.drag.pointer;this.drag.ghost.remove();this.drag=null;
      if(this.canvas.hasPointerCapture(pointer))this.canvas.releasePointerCapture(pointer);}
    this.selected=null;
    for(const tile of this.canvas.children)tile.classList.remove('drag-origin','drop-target','selected');
  }
  swap(source,target) {
    if(this.disabled)return;
    this.beforeChange();const order=this.orders[this.image];[order[source],order[target]]=[order[target],order[source]];
    this.reviewed[this.image]=false;this.onChange();this.render();this.canvas.children[target].focus();
    this.message('已交换两块。还原后勾选“本张已还原”。');
  }
  keydown(event) {
    if(this.disabled)return;
    if(event.key==='Escape'){event.preventDefault();this.cancelDrag();this.render();return;}
    if(this.drag)return;
    const slot=Number(event.target.closest('[data-slot]')?.dataset.slot);if(!Number.isInteger(slot))return;
    if(event.key===' '||event.key==='Enter') {
      event.preventDefault();
      if(this.selected==null){this.selected=slot;this.render();this.canvas.children[slot].focus();}
      else {const source=this.selected;this.selected=null;if(source!==slot)this.swap(source,slot);else this.render();}
    }else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
      event.preventDefault();const column=slot%2,row=Math.floor(slot/2);
      const next={'ArrowLeft':row*2,'ArrowRight':row*2+1,'ArrowUp':column,'ArrowDown':column+2}[event.key];
      this.canvas.children[next].focus();
    }
  }
  clear() {
    this.cancelDrag();this.data=null;this.image='';this.canvas.replaceChildren();
    document.getElementById('puzzle-original-image').removeAttribute('src');
    document.getElementById('puzzle-original-labels').replaceChildren();
  }
}
