// WebKit's print backend currently drops CSS multi-column layout. Freeze the
// balanced sections as ordinary table cells for printing, leaving editing intact.
export function installPrintLayout(view){
  let printable=null,measure=null;
  const cleanup=()=>{printable?.remove();measure?.remove();printable=measure=null;};
  function prepare(){
    cleanup();
    printable=view.dom.cloneNode(true);printable.id='print-document';
    printable.removeAttribute('contenteditable');printable.setAttribute('aria-hidden','true');
    // GTK page setup supplies this width before starting a print operation.
    const width=Number(document.documentElement.dataset.printWidth)||602.36;
    measure=document.createElement('div');measure.className='ProseMirror';measure.id='print-measure';
    Object.assign(measure.style,{position:'absolute',left:'-100000px',top:'0',visibility:'hidden',width:`${width}px`,padding:'0',minHeight:'0',zoom:'1'});
    document.body.append(measure);
    for(const section of Array.from(printable.querySelectorAll('[data-column-section]'))){
      const count=Number(section.dataset.columnSection);if(count<2)continue;
      const sample=section.cloneNode(true);measure.append(sample);
      const maxHeight=(Number(document.documentElement.dataset.printHeight)||910.63)-48;
      if(sample.getBoundingClientRect().height>maxHeight){sample.style.height=`${maxHeight}px`;sample.style.columnFill='auto';}
      const box=sample.getBoundingClientRect(),step=(box.width+32)/count;
      const boundaries=[],walker=document.createTreeWalker(sample,NodeFilter.SHOW_TEXT);
      const column=(text,offset)=>{
        const range=document.createRange();range.setStart(text,offset);range.setEnd(text,offset+1);
        const rect=range.getBoundingClientRect();
        return Math.max(0,Math.floor((rect.left-box.left+1)/step));
      };
      let nextColumn=1,text;
      while((text=walker.nextNode())){
        if(!text.length)continue;
        while(column(text,text.length-1)>=nextColumn){
          let lo=0,hi=text.length-1;
          while(lo<hi){const mid=(lo+hi)>>1;if(column(text,mid)>=nextColumn)hi=mid;else lo=mid+1;}
          boundaries.push({node:text,offset:lo});nextColumn++;
        }
      }
      const pages=document.createDocumentFragment();let start={node:sample,offset:0};
      const totalColumns=boundaries.length+1;
      for(let base=0;base<totalColumns;base+=count){
        const table=document.createElement('table');table.className='print-columns';
        Object.assign(table.style,{width:'100%',tableLayout:'fixed',borderCollapse:'collapse',margin:'0'});
        if(base){table.style.breakBefore='page';table.style.pageBreakBefore='always';}
        const row=table.createTBody().insertRow();
        for(let index=0;index<count;index++){
          const end=boundaries[base+index]||{node:sample,offset:sample.childNodes.length};
          const cell=row.insertCell();cell.style.width=`calc((100% - ${32*(count-1)}px) / ${count})`;
          const range=document.createRange();range.setStart(start.node,start.offset);range.setEnd(end.node,end.offset);
          cell.append(range.cloneContents());start=end;
          if(index<count-1){const gap=row.insertCell();gap.style.width='32px';}
        }
        pages.append(table);
      }
      section.replaceWith(pages);sample.remove();
    }
    measure.remove();measure=null;document.body.append(printable);
  }
  window.addEventListener('beforeprint',prepare);window.addEventListener('afterprint',cleanup);
  return ()=>{cleanup();window.removeEventListener('beforeprint',prepare);window.removeEventListener('afterprint',cleanup);};
}
