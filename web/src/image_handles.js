// Editor-only controls; image data and HTML serialization remain unchanged.
export function imageNodeView(node){
  const dom=document.createElement('img');
  function update(current){
    if(current.type.name!=='image')return false;
    for(const name of ['src','alt','title','width']){
      const value=current.attrs[name];if(value===null||value===undefined)dom.removeAttribute(name);else dom.setAttribute(name,String(value));
    }
    dom.loading='lazy';dom.decoding='async';dom.style.removeProperty('width');return true;
  }
  update(node);
  return {dom,update,ignoreMutation:record=>record.type==='attributes'&&['style','loading','decoding'].includes(record.attributeName)};
}

export function installImageHandles(view,resize){
  const overlay=document.createElement('div');overlay.className='image-resize-controls';overlay.hidden=true;
  const badge=document.createElement('span');badge.className='image-resize-size';overlay.append(badge);
  let frame=null,drag=null,disposed=false;
  for(const [kind,label] of [['right','Resize picture width'],['bottom','Resize picture height'],['corner','Resize picture']]){
    const button=document.createElement('button');button.type='button';button.className=`image-resize-handle ${kind}`;
    button.setAttribute('aria-label',label);button.title=label+' (proportions locked)';button.dataset.handle=kind;
    button.addEventListener('pointerdown',begin);button.addEventListener('pointermove',move);
    button.addEventListener('pointerup',finish);button.addEventListener('pointercancel',()=>cancel());
    button.addEventListener('lostpointercapture',()=>{if(drag)cancel();});
    button.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
      const current=selected();if(!current)return;
      event.preventDefault();event.stopPropagation();
      const sign=['ArrowLeft','ArrowUp'].includes(event.key)?-1:1;
      resize({position:current.position,width:Math.max(1,Math.min(1600,current.image.clientWidth+sign*(event.shiftKey?1:10)))});
      button.focus({preventScroll:true});
    });
    overlay.append(button);
  }
  document.body.append(overlay);
  function selected(){
    if(!view.editable)return null;
    const state=view.state;if(state.selection.node?.type.name!=='image')return null;
    const position=state.selection.from,image=view.nodeDOM(position);
    return image?.tagName==='IMG'?{image,position}:null;
  }
  function update(){
    frame=null;if(disposed)return;
    const current=selected();if(!current){if(drag)cancel();overlay.hidden=true;return;}
    const rect=current.image.getBoundingClientRect();
    overlay.hidden=rect.width<=0||rect.height<=0;
    Object.assign(overlay.style,{left:`${rect.left}px`,top:`${rect.top}px`,width:`${rect.width}px`,height:`${rect.height}px`});
    badge.textContent=`${current.image.clientWidth} × ${current.image.clientHeight} px`;
  }
  function schedule(){if(!disposed&&frame===null)frame=window.requestAnimationFrame(update);}
  function begin(event){
    if(event.button!==0)return;
    const current=selected();if(!current||!current.image.clientWidth)return;
    event.preventDefault();event.stopPropagation();
    const rect=current.image.getBoundingClientRect();
    drag={...current,button:event.currentTarget,pointer:event.pointerId,x:event.clientX,y:event.clientY,
      start:current.image.clientWidth,width:current.image.clientWidth,ratio:current.image.clientHeight/current.image.clientWidth,
      zoom:rect.width/current.image.clientWidth,doc:view.state.doc};
    drag.button.setPointerCapture(event.pointerId);overlay.classList.add('dragging');
  }
  function move(event){
    if(!drag||event.pointerId!==drag.pointer)return;
    event.preventDefault();
    const dx=(event.clientX-drag.x)/drag.zoom,dy=(event.clientY-drag.y)/(drag.zoom*drag.ratio);
    const kind=drag.button.dataset.handle;
    const delta=kind==='right'?dx:kind==='bottom'?dy:Math.abs(dx)>Math.abs(dy)?dx:dy;
    const available=drag.image.parentElement.clientWidth||1600;
    drag.width=Math.round(Math.max(16,Math.min(1600,available,drag.start+delta)));
    drag.image.style.width=`${drag.width}px`;update();
  }
  function finish(event){
    if(!drag||event.pointerId!==drag.pointer)return;
    move(event);const current=drag;drag=null;
    current.image.style.removeProperty('width');overlay.classList.remove('dragging');
    if(current.button.hasPointerCapture(current.pointer))current.button.releasePointerCapture(current.pointer);
    if(view.state.doc===current.doc&&current.width!==current.start)resize({position:current.position,width:current.width});
    else schedule();
  }
  function cancel(){
    if(!drag)return;const current=drag;drag=null;
    current.image.style.removeProperty('width');overlay.classList.remove('dragging');
    if(current.button.hasPointerCapture(current.pointer))current.button.releasePointerCapture(current.pointer);
    schedule();
  }
  function key(event){if(event.key==='Escape'&&drag){event.preventDefault();event.stopPropagation();cancel();view.focus();}}
  window.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);
  window.addEventListener('beforeprint',cancel);
  document.addEventListener('keydown',key,true);view.dom.addEventListener('load',schedule,true);
  const observer=window.ResizeObserver?new window.ResizeObserver(schedule):null;observer?.observe(view.dom);
  return {update:schedule,destroy(){cancel();disposed=true;if(frame!==null)window.cancelAnimationFrame(frame);observer?.disconnect();
    window.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);
    window.removeEventListener('beforeprint',cancel);
    document.removeEventListener('keydown',key,true);view.dom.removeEventListener('load',schedule,true);overlay.remove();}};
}
