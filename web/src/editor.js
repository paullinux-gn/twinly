import {imageNodeView,installImageHandles} from "./image_handles.js";
import {installPrintLayout} from "./print_layout.js";
import {createSearch} from "./search.js";
import {Schema, Fragment, DOMParser as PMParser, DOMSerializer} from "prosemirror-model";
import {schema as basic} from "prosemirror-schema-basic";
import {addListNodes, wrapInList, liftListItem, splitListItem, sinkListItem} from "prosemirror-schema-list";
import {EditorState, Selection, TextSelection, NodeSelection} from "prosemirror-state";
import {EditorView} from "prosemirror-view";
import {baseKeymap, toggleMark, setBlockType, wrapIn, lift, chainCommands, splitBlockAs, liftEmptyBlock} from "prosemirror-commands";
import {history, undo, redo, closeHistory} from "prosemirror-history";
import {keymap} from "prosemirror-keymap";
import {TableMap, TableView, tableNodes, tableEditing, columnResizing, goToNextCell} from "prosemirror-tables";

const safeLink = href => typeof href==="string"&&!/[\x00-\x1f]/.test(href)&&(/^(https?:)/i.test(href)||(!/^(?:[a-z][a-z0-9+.-]*:|[/\\])/i.test(href)&&/\.html?(?:[?#].*)?$/i.test(href)));
const stretches=["ultra-condensed","extra-condensed","condensed","semi-condensed","normal","semi-expanded","expanded","extra-expanded","ultra-expanded"];
const stretchValue=value=>({"50%":"ultra-condensed","62.5%":"extra-condensed","75%":"condensed","87.5%":"semi-condensed","100%":"normal","112.5%":"semi-expanded","125%":"expanded","150%":"extra-expanded","200%":"ultra-expanded"}[value]||value);
const safeImage = src => /^data:image\/(png|jpeg);base64,/i.test(src || "");
const DEFAULT_STYLES={
  Subtitle:{kind:"Body",level:0,font:"Noto Sans",size:16,bold:false,italic:true},
  Quote:{kind:"Body",level:0,font:"Noto Sans",size:12,bold:false,italic:true},
  Normal:{kind:"Body",level:0,font:"Noto Sans",size:12,bold:false,italic:false},
  Title:{kind:"Title",level:1,font:"Noto Sans",size:28,bold:true,italic:false},
  H1:{kind:"H1",level:1,font:"Noto Sans",size:24,bold:true,italic:false},
  H2:{kind:"H2",level:2,font:"Noto Sans",size:20,bold:true,italic:false},
  H3:{kind:"H3",level:3,font:"Noto Sans",size:17,bold:true,italic:false},
};
const validName=name=>typeof name==="string"&&/^[\p{L}\p{N} _-]{1,40}$/u.test(name)&&!["__proto__","constructor","prototype"].includes(name);
function normaliseStyles(input){
  const result={...DEFAULT_STYLES};
  if(input&&typeof input==="object")for(const [name,style] of Object.entries(input).slice(0,100)){
    if(validName(name)&&style&&typeof style.font==="string"&&/^[\p{L}\p{N} ,\-]{1,80}$/u.test(style.font)&&Number.isFinite(style.size)){
      const level=Math.max(0,Math.min(3,Math.trunc(style.level)||0));
      const kind=["Body","Title","H1","H2","H3"].includes(style.kind)?style.kind:(name==="Title"&&level===1?"Title":level?`H${level}`:"Body");
      result[name]={kind,level:kind==="Body"?0:kind==="Title"?1:Number(kind.slice(1)),font:style.font,size:Math.max(1,Math.min(1000,style.size)),bold:!!style.bold,italic:!!style.italic};
    }
  }
  return result;
}
// ProseMirror document attributes are persistent: unchanged style maps can be
// reused across cursor movement and text edits without normalising them again.
const styleCache=new WeakMap();
function documentStyles(doc){
  const source=doc.attrs.styles;
  if(!source||typeof source!=="object")return DEFAULT_STYLES;
  if(!styleCache.has(source))styleCache.set(source,normaliseStyles(source));
  return styleCache.get(source);
}
const nodeStyle=node=>node.attrs.styleName||(node.type.name==="heading"?`H${node.attrs.level}`:"Normal");
function styleRules(styles,prefix=""){
  return Object.entries(styles).map(([name,s])=>`${prefix}[data-style=${JSON.stringify(name)}]{font-family:${s.font};font-size:${s.size}pt;font-weight:${s.bold?700:400};font-style:${s.italic?"italic":"normal"}}`).join("\n");
}
const escapeAttribute=value=>value.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function readLineSpacing(el){
  const value=el.style.lineHeight;
  const number=/^\d+(?:\.\d+)?%?$/.test(value)?parseFloat(value)/(value.endsWith("%")?100:1):1.0;
  return Math.max(.95,Math.min(3,number));
}
const blockAttrs = el => ({lineSpacing:readLineSpacing(el),align: ["left","center","right","justify"].includes(el.style.textAlign) ? el.style.textAlign : "left"});
export const DEFAULT_MARGINS=Object.freeze({top:20,bottom:20,left:20,right:20});
export function normaliseMargins(value) {
  const result={...DEFAULT_MARGINS};
  for(const side of Object.keys(result)) {
    const number=value?.[side];
    if(typeof number==='number'&&Number.isFinite(number)&&number>=0&&number<=90)result[side]=Math.round(number*10)/10;
  }
  return result;
}

let nodes = basic.spec.nodes.update("doc",{content:"block+",attrs:{customStyles:{default:{}},styles:{default:DEFAULT_STYLES},columns:{default:1},margins:{default:DEFAULT_MARGINS}}})
.update("horizontal_rule",{...basic.spec.nodes.get("horizontal_rule"),parseDOM:[{tag:"hr:not([data-page-break])"}]}).update("paragraph", {
  content: "inline*", group: "block", attrs: {align: {default:"left"},styleName:{default:"Normal"},clear:{default:false},lineSpacing:{default:1.0}},
  parseDOM: [{tag:"p",getAttrs:el=>({...blockAttrs(el),styleName:el.dataset.style||"Normal",clear:el.style.clear==="both"})}, {tag:"div",getAttrs:blockAttrs}],
  toDOM: node => ["p", {style:`text-align:${node.attrs.align};line-height:${node.attrs.lineSpacing};--twinly-line-spacing:${node.attrs.lineSpacing}${node.attrs.clear?";clear:both":""}`,"data-style":nodeStyle(node)},0],
}).update("heading", {
  content:"inline*", group:"block", defining:true,
  attrs:{level:{default:1},align:{default:"left"},styleName:{default:null},lineSpacing:{default:1.0}},
  parseDOM:[1,2,3].map(level => ({tag:`h${level}`,getAttrs:el=>({level,...blockAttrs(el),styleName:el.dataset.style||`H${level}`})})),
  toDOM:node=>[`h${node.attrs.level}`,{style:`text-align:${node.attrs.align};line-height:${node.attrs.lineSpacing};--twinly-line-spacing:${node.attrs.lineSpacing}`,"data-style":nodeStyle(node)},0],
}).update("image", {
  inline:true, group:"inline", draggable:true,
  attrs:{src:{},alt:{default:""},title:{default:null},width:{default:null}},
  parseDOM:[{tag:"img[src]",getAttrs:el=>safeImage(el.getAttribute("src")) ? {
    src:el.getAttribute("src"),alt:el.getAttribute("alt")||"",title:el.getAttribute("title"),
    width: /^\d+$/.test(el.getAttribute("width")||"") ? Math.min(1600,Number(el.getAttribute("width"))) : null,
  } : false}],
  toDOM:node=>["img",{...node.attrs,loading:"lazy",decoding:"async"}],
});
nodes = addListNodes(nodes,"paragraph block*","block");
const bounded=(value,min,max,fallback)=>Number.isFinite(Number(value))?Math.max(min,Math.min(max,Number(value))):fallback;
function backgroundColour(value){
  if(typeof value!=="string"||!(/^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%]+\)|[a-z]{3,20})$/i).test(value.trim()))return null;
  const style=document.createElement("span").style;style.backgroundColor=value.trim();return style.backgroundColor||null;
}
function highlightForeground(value){
  const normalized=backgroundColour(value),channels=normalized?.match(/[\d.]+/g)?.map(Number);
  if(!channels||channels.length<3)return "inherit";
  const linear=channels.slice(0,3).map(v=>v/255<=.04045?v/255/12.92:((v/255+.055)/1.055)**2.4);
  const luminance=linear.reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
  return 1.05/(luminance+.05)>=4.5?"#ffffff":"inherit";
}
const tables=tableNodes({tableGroup:"block",cellContent:"block+"});
tables.table={...tables.table,attrs:{borderWidth:{default:1},width:{default:100},floating:{default:false}},
  parseDOM:[{tag:"table",getAttrs:el=>({
    borderWidth:bounded(el.dataset.borderWidth||el.style.getPropertyValue("--table-border-width").replace("px","")||1,0,12,1),
    width:bounded(el.dataset.tableWidth||el.style.width.replace("%","")||100,25,100,100),
    floating:el.dataset.floating==="true"||el.style.cssFloat==="left"})}],
  toDOM:node=>["table",{"data-border-width":node.attrs.borderWidth,"data-table-width":node.attrs.width,
    "data-floating":String(node.attrs.floating),style:`width:${node.attrs.width}%;--table-border-width:${node.attrs.borderWidth}px;${node.attrs.floating?("float:left;"+(node.attrs.width<100?"margin-right:16px;":"")):""}`},["tbody",0]],
};
nodes = nodes.append(tables).append({
  checklist:{group:"block",content:"checklist_item+",
    parseDOM:[{tag:"ul[data-checklist]",priority:60}],
    toDOM:()=>["ul",{"data-checklist":"true",class:"checklist"},0]},
  checklist_item:{content:"paragraph block*",defining:true,attrs:{checked:{default:false}},
    parseDOM:[{tag:"li[data-checked]",priority:60,contentElement:".checklist-content",getAttrs:el=>({checked:el.dataset.checked==="true"})}],
    toDOM:node=>["li",{"data-checked":String(node.attrs.checked)},
      ["span",{class:"checklist-box","aria-hidden":"true"},node.attrs.checked?"☑":"☐"],
      ["div",{class:"checklist-content"},0]]},
  textbox:{group:"block",content:"block+",defining:true,draggable:true,
    attrs:{width:{default:null},height:{default:null},borderWidth:{default:1},floating:{default:false},background:{default:null}},
    parseDOM:[{tag:"section[data-textbox]",getAttrs:el=>({
      width:el.dataset.boxWidth||el.style.width?bounded(el.dataset.boxWidth||el.style.width.replace("px",""),60,1600,150):null,
      height:el.dataset.boxHeight||el.style.minHeight||el.style.height?bounded(el.dataset.boxHeight||(el.style.minHeight||el.style.height).replace("px",""),40,2000,100):null,
      borderWidth:bounded(el.dataset.borderWidth||el.style.borderWidth.replace("px","")||1,0,12,1),
      floating:el.dataset.floating==="true"||el.style.cssFloat==="left",
      background:backgroundColour(el.dataset.background||el.style.backgroundColor)})}],
    toDOM:node=>["section",{"data-textbox":"true",class:"text-box","data-box-width":node.attrs.width,
      "data-box-height":node.attrs.height,"data-border-width":node.attrs.borderWidth,"data-floating":String(node.attrs.floating),"data-background":node.attrs.background,
      style:`${node.attrs.width?`width:${node.attrs.width}px;`:""}${node.attrs.height?`min-height:${node.attrs.height}px;`:""}border-width:${node.attrs.borderWidth}px;border-radius:12px;${node.attrs.background?`background-color:${node.attrs.background};`:""}${node.attrs.floating?"float:left;margin-right:16px;max-width:calc(100% - 16px);":""}`},0]},
  column_section:{group:"block",content:"block+",defining:true,attrs:{columns:{default:2}},
    parseDOM:[{tag:"section[data-column-section]",getAttrs:el=>({columns:[1,2,3].includes(Number(el.dataset.columnSection))?Number(el.dataset.columnSection):1})}],
    toDOM:node=>["section",{"data-column-section":String(node.attrs.columns),style:`column-count:${node.attrs.columns};column-gap:32px;column-fill:balance;display:block`},0]},
  page_break:{group:"block",atom:true,selectable:true,
    parseDOM:[{tag:"hr[data-page-break]"}],toDOM:()=>["hr",{"data-page-break":"true"}]},
});
let marks = basic.spec.marks.update("strong",{...basic.spec.marks.get("strong"),excludes:"regular numeric_weight"})
.update("em",{...basic.spec.marks.get("em"),excludes:"upright slant"}).update("link", {
  attrs:{href:{},title:{default:null}},inclusive:false,
  parseDOM:[{tag:"a[href]",getAttrs:el=>safeLink(el.getAttribute("href")) ? {href:el.getAttribute("href"),title:el.getAttribute("title")} : false}],
  toDOM:mark=>["a",{...mark.attrs,rel:"noreferrer noopener"},0],
}).append({
  numeric_weight:{excludes:"strong regular",attrs:{weight:{}},parseDOM:[{style:"font-weight",priority:80,getAttrs:v=>/^\d+$/.test(v)&&Number(v)>=100&&Number(v)<=1000&&![400,700].includes(Number(v))?{weight:Number(v)}:false}],toDOM:m=>["span",{style:`font-weight:${m.attrs.weight}`},0]},
  stretch:{attrs:{value:{}},parseDOM:[{tag:"span[data-font-stretch]",getAttrs:el=>stretches.includes(el.dataset.fontStretch)?{value:el.dataset.fontStretch}:false},{style:"font-stretch",getAttrs:value=>stretches.includes(stretchValue(value))?{value:stretchValue(value)}:false}],toDOM:m=>["span",{"data-font-stretch":m.attrs.value,style:`font-stretch:${[50,62.5,75,87.5,100,112.5,125,150,200][stretches.indexOf(m.attrs.value)]}%`},0]},
  slant:{attrs:{value:{}},excludes:"em upright",parseDOM:[{style:"font-style",getAttrs:value=>["oblique","normal"].includes(value)?{value}:false}],toDOM:m=>["span",{style:`font-style:${m.attrs.value}`},0]},
  regular:{excludes:"strong numeric_weight",parseDOM:[{style:"font-weight",getAttrs:v=>["normal","400"].includes(v)?null:false}],toDOM:()=>["span",{style:"font-weight:400"},0]},
  upright:{excludes:"em slant",parseDOM:[{style:"font-style=normal"}],toDOM:()=>["span",{style:"font-style:normal"},0]},
  underline:{parseDOM:[{tag:"u"},{style:"text-decoration",getAttrs:v=>v.includes("underline")?null:false}],toDOM:()=>["u",0]},
  strike:{parseDOM:[{tag:"s"},{tag:"del"},{style:"text-decoration",getAttrs:v=>v.includes("line-through")?null:false}],toDOM:()=>["s",0]},
  subscript:{excludes:"superscript",parseDOM:[{tag:"sub"}],toDOM:()=>["sub",0]},
  superscript:{excludes:"subscript",parseDOM:[{tag:"sup"}],toDOM:()=>["sup",0]},
  font:{attrs:{family:{}},parseDOM:[{style:"font-family",getAttrs:family=>({family})}],toDOM:m=>["span",{style:`font-family:${m.attrs.family}`},0]},
  size:{attrs:{size:{}},parseDOM:[{style:"font-size",getAttrs:size=>/^\d+(\.\d+)?(pt|px)$/.test(size)?{size}:false}],toDOM:m=>["span",{style:`font-size:${m.attrs.size}`},0]},
  color:{attrs:{color:{},explicit:{default:false}},parseDOM:[{
    tag:"[style]",priority:70,consuming:false,getAttrs:el=>{
      if(!el.style.color||el.matches('span[data-highlight][data-auto-contrast="true"]'))return false;
      return {color:el.style.color,explicit:el.dataset.textColour==="true"};
    }}],toDOM:m=>["span",{style:`color:${m.attrs.color}`,"data-text-colour":String(m.attrs.explicit)},0]},
  highlight:{attrs:{color:{},autoContrast:{default:false}},parseDOM:[
    {tag:"span[data-highlight]",priority:60,getAttrs:el=>{
      const color=el.dataset.highlightColour||el.style.backgroundColor;
      return backgroundColour(color)?{color,autoContrast:el.dataset.autoContrast==="true"}:false;
    }},
    {style:"background-color",getAttrs:color=>({color})}],
    toDOM:m=>["span",{"data-highlight":"true","data-highlight-colour":m.attrs.color,"data-auto-contrast":String(m.attrs.autoContrast),
      style:`background-color:${m.attrs.color};border-radius:0.3em;padding:0.02em 0.25em 0.04em;box-decoration-break:clone;-webkit-box-decoration-break:clone${m.attrs.autoContrast?`;color:${highlightForeground(m.attrs.color)}`:""}`},0]},
});
export const schema = new Schema({nodes,marks});

export function parseHTML(html, domDocument=document) {
  // Parse in an inert HTML document; imported event handlers never enter the
  // live editor DOM, and head/title content does not become document text.
  const container = new domDocument.defaultView.DOMParser().parseFromString(html,"text/html").body;
  container.querySelectorAll("script,style,iframe,object,embed,form,input,button,meta,link,base,svg,noscript").forEach(el=>el.remove());
  // A box background belongs to the container, not a highlight mark on its text.
  container.querySelectorAll("section[data-textbox]").forEach(el=>{
    const colour=backgroundColour(el.dataset.background||el.style.backgroundColor);
    if(colour)el.dataset.background=colour;
    el.style.removeProperty("background-color");
  });
  container.querySelectorAll('span[data-highlight][data-auto-contrast="true"]').forEach(el=>el.style.removeProperty("color"));
  const legacy=!!container.querySelector('[data-twinly-style]');
  if(legacy){
    container.dataset.editorStyles=container.dataset.editorStyles||'null';
    container.querySelectorAll('p[data-twinly-style]').forEach(el=>{if(el.childNodes.length===1&&el.firstChild.nodeName==='BR')el.firstChild.remove();});
    for(const parent of [container,...container.querySelectorAll('ul,ol,table,tbody,thead,tfoot,tr,section')])for(const child of Array.from(parent.childNodes))if(child.nodeType===3&&!child.textContent.trim())child.remove();
  }
  container.querySelectorAll('table[data-twinly-border]').forEach(table=>{
    table.dataset.borderWidth=table.dataset.twinlyBorder;
    try{const widths=JSON.parse(table.dataset.twinlyWidths||'[]'),total=widths.reduce((sum,v)=>sum+v,0);if(total>0)table.querySelectorAll('tr').forEach(row=>Array.from(row.children).forEach((cell,index)=>{if(widths[index])cell.dataset.colwidth=String(Math.max(40,Math.round(760*widths[index]/total)));}));}catch{}
  });
  const importedCustom={};
  const roleNames={body:'Normal',title:'Title',subtitle:'Subtitle',quote:'Quote',h1:'H1',h2:'H2',h3:'H3'};
  container.querySelectorAll('[data-twinly-style]').forEach(el=>{el.dataset.style=roleNames[el.dataset.twinlyStyle]||'Normal';});
  container.querySelectorAll('[data-twinly-custom]').forEach(el=>{
    try{const definition=JSON.parse(el.dataset.twinlyCustom);if(/^[a-f0-9]{32}$/.test(definition.id)&&typeof definition.name==='string'){importedCustom[definition.id]=definition;const block=el.closest('p,h1,h2,h3,blockquote');if(block)block.dataset.style='Twinly_'+definition.id;}}catch{}
  });
  container.querySelectorAll('[data-twinly-highlight-foreground]').forEach(el=>{
    const original=el.dataset.twinlyHighlightForeground;
    el.dataset.highlight='true';el.dataset.highlightColour=el.style.backgroundColor;el.dataset.autoContrast='true';el.style.removeProperty('color');
    if(/^#[0-9a-f]{6}$/i.test(original)){const inner=domDocument.createElement('span');inner.style.color=original;inner.dataset.textColour='true';while(el.firstChild)inner.append(el.firstChild);el.append(inner);}
  });
  container.querySelectorAll('p[data-twinly-style]').forEach(el=>{
    const text=el.textContent,match=/^(• |[☐☑] |\d+\. )/.exec(text);if(!match)return;
    const walker=domDocument.createTreeWalker(el,domDocument.defaultView.NodeFilter.SHOW_TEXT);let remaining=match[0].length,node;
    while(remaining&&(node=walker.nextNode())){const take=Math.min(remaining,node.textContent.length);node.textContent=node.textContent.slice(take);remaining-=take;}
    const checklist=/^[☐☑]/.test(match[0]),list=domDocument.createElement(checklist?'ul':match[0].includes('•')?'ul':'ol'),item=domDocument.createElement('li');
    if(list.tagName==='OL')list.setAttribute('start',String(parseInt(match[0],10)));
    if(checklist){list.dataset.checklist='true';item.dataset.checked=String(match[0].startsWith('☑'));const content=domDocument.createElement('div');content.className='checklist-content';content.append(el.cloneNode(true));item.append(content);}else item.append(el.cloneNode(true));
    list.append(item);el.replaceWith(list);
  });
  let styles=DEFAULT_STYLES;
  try{styles=normaliseStyles(JSON.parse(container.dataset.editorStyles||"null"));}catch{/* Ordinary imported HTML uses the built-in styles. */}
  let customStyles={};
  try{customStyles=JSON.parse(container.dataset.twinlyCustomStyles||'{}');}catch{}
  customStyles={...customStyles,...importedCustom};
  for(const [id,definition] of Object.entries(customStyles).slice(0,100)){
    if(!/^[a-f0-9]{32}$/.test(id)||!definition?.format)continue;
    const base=DEFAULT_STYLES[roleNames[definition.base]]||DEFAULT_STYLES.Normal,f=definition.format;
    styles={...styles,['Twinly_'+id]:{...base,font:f.family||base.font,size:f.size||base.size,bold:f.font_weight?f.font_weight>=600:!!f.weight,italic:f.font_style?f.font_style==='italic':!!f.italic}};
  }
  let margins=DEFAULT_MARGINS;
  try{margins=normaliseMargins(JSON.parse(container.dataset.pageMargins||"null"));}catch{}
  const parsed=PMParser.fromSchema(schema).parse(container,{topNode:schema.topNodeType.create({styles,margins,customStyles}),preserveWhitespace:container.hasAttribute("data-editor-styles")?"full":false});
  const legacyColumns=Number(container.dataset.columns);
  if([2,3].includes(legacyColumns)&&!container.querySelector('[data-column-section]')){
    const children=[],first=[];let afterBreak=false;
    parsed.forEach(node=>{if(node.type===schema.nodes.page_break)afterBreak=true;if(afterBreak)children.push(node);else first.push(node);});
    if(first.length)children.unshift(schema.nodes.column_section.create({columns:legacyColumns},first));
    return parsed.copy(Fragment.fromArray(children));
  }
  return parsed;
}

function fragmentHTML(doc,domDocument=document) {
  const container = domDocument.createElement("div");
  container.append(DOMSerializer.fromSchema(schema).serializeFragment(doc.content,{document:domDocument}));
  return container.innerHTML;
}
export function serializeHTML(doc, domDocument=document) {
  const margins=normaliseMargins(doc.attrs.margins);
  return '<!doctype html><html><head><meta charset="utf-8"><title>Document</title><style>' +
    '@page{margin:'+margins.top+'mm '+margins.right+'mm '+margins.bottom+'mm '+margins.left+'mm}body{max-width:794px;margin:2em auto;font-family:serif;line-height:1.5;padding:0 2em}' +
    'img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #888;border-width:var(--table-border-width,1px);padding:6px}' +
    'ul[data-checklist]{list-style:none;padding-left:0}ul[data-checklist]>li{display:flex;gap:.5em}ul[data-checklist] .checklist-content{flex:1;min-width:0}' +
    '[data-textbox]{box-sizing:border-box;max-width:100%;border:1px solid #888;padding:16px;margin:16px 0;border-radius:12px;overflow-wrap:break-word;display:flow-root}' +
    '[data-page-break]{column-span:all;-webkit-column-span:all;break-after:page}@media print{body{margin:0;max-width:none;padding:0}[data-page-break]{display:block;border:0;margin:0;padding:0;height:0;break-after:page;page-break-after:always}}' +
    styleRules(documentStyles(doc)) +
    '</style></head><body data-twinly-custom-styles="'+escapeAttribute(JSON.stringify(doc.attrs.customStyles||{}))+'" data-page-margins="'+escapeAttribute(JSON.stringify(margins))+'" data-columns="'+doc.attrs.columns+'" data-editor-styles="'+escapeAttribute(JSON.stringify(documentStyles(doc)))+'">' + fragmentHTML(doc,domDocument) + '</body></html>';
}

function selectionMarks(state){
  if(state.storedMarks)return state.storedMarks;
  if(state.selection.empty)return state.selection.$from.marks();
  let marks=null;state.doc.nodesBetween(state.selection.from,state.selection.to,node=>{if(node.isInline&&marks===null)marks=node.marks;return marks===null;});
  return marks||state.selection.$from.marks();
}
function markValue(state,type,attr) {
  const marks = selectionMarks(state);
  return marks.find(mark=>mark.type===type)?.attrs[attr];
}
function markActive(state,type) {
  const {from,to,empty,$from} = state.selection;
  return empty ? !!type.isInSet(state.storedMarks||$from.marks()) : state.doc.rangeHasMark(from,to,type);
}

class DocumentTableView extends TableView {
  constructor(node,width){
    super(node,width);
    this.properties=document.createElement("button");this.properties.type="button";
    this.properties.dataset.tableProperties="true";this.properties.contentEditable="false";
    this.properties.textContent="⋮";this.properties.title="Table properties";
    this.properties.setAttribute("aria-label","Table properties");this.dom.append(this.properties);
    this.applyLayout();
  }
  applyLayout(){
    const {width,borderWidth,floating}=this.node.attrs;
    this.dom.style.width=`${width}%`;this.dom.style.cssFloat=floating?"left":"none";
    this.dom.style.marginRight=floating&&width<100?"16px":"0";
    this.table.style.width="100%";this.table.style.setProperty("--table-border-width",`${borderWidth}px`);
  }
  update(node){if(!super.update(node))return false;this.applyLayout();return true;}
  ignoreMutation(record){return record.type==="attributes"&&(record.target===this.dom||record.target===this.properties)||super.ignoreMutation(record);}
}

export function createEditor(mount, notify=()=>{}) {
  const search=createSearch();
  let glassReference=null,glassOptions=null;
  let cleanDoc, revision=0, documentId=1, updateTimer, wordTimer, words=0;
  const styleSheet=document.createElement("style");document.head.append(styleSheet);
  const refreshStyles=()=>{
    const margins=normaliseMargins(view.state.doc.attrs.margins);
    for(const [side,value] of Object.entries(margins))view.dom.style.setProperty('--margin-'+side,value+'mm');
    styleSheet.textContent=styleRules(documentStyles(view.state.doc),".ProseMirror ");};
  const exports = new Map();
  let dirtyDoc,dirtyClean,dirtyValue;
  function isDirty(){
    const doc=view.state.doc;
    if(doc!==dirtyDoc||cleanDoc!==dirtyClean){dirtyDoc=doc;dirtyClean=cleanDoc;dirtyValue=!doc.eq(cleanDoc);}
    return dirtyValue;
  }
  function tableInfo(position=null){
    const state=view.state;
    if(position===null){
      const $from=state.selection.$from;
      for(let depth=$from.depth;depth>0;depth--)if($from.node(depth).type===schema.nodes.table){position=$from.before(depth);break;}
      if(position===null&&state.selection.node?.type===schema.nodes.table)position=state.selection.from;
    }
    if(position===null)return null;
    const table=state.doc.nodeAt(position);if(table?.type!==schema.nodes.table)return null;
    let merged=false;table.descendants(node=>{if(node.type.spec.tableRole==="cell"||node.type.spec.tableRole==="header_cell")merged ||= node.attrs.colspan!==1||node.attrs.rowspan!==1;});
    return {...table.attrs,position,documentId,rows:table.childCount,cols:TableMap.get(table).width,
      header:Array.from({length:table.firstChild.childCount},(_,i)=>table.firstChild.child(i).type===schema.nodes.table_header).every(Boolean),merged};
  }
  function imageInfo(position=null){
    if(position===null){if(view.state.selection.node?.type!==schema.nodes.image)return null;position=view.state.selection.from;}
    const node=view.state.doc.nodeAt(position);if(node?.type!==schema.nodes.image)return null;
    const element=view.nodeDOM(position);
    return {position,documentId,width:node.attrs.width,naturalWidth:element?.naturalWidth||0,naturalHeight:element?.naturalHeight||0,
      displayedWidth:element?.clientWidth||node.attrs.width||0,alt:node.attrs.alt};
  }
  function textboxInfo(){
    const $from=view.state.selection.$from;
    for(let depth=$from.depth;depth>0;depth--)if($from.node(depth).type===schema.nodes.textbox){
      return {...$from.node(depth).attrs,position:$from.before(depth),documentId};
    }
    if(view.state.selection.node?.type===schema.nodes.textbox)return {...view.state.selection.node.attrs,position:view.state.selection.from,documentId};
    return null;
  }
  function editTableAt(element){
    const $pos=view.state.doc.resolve(view.posAtDOM(element.querySelector("td,th"),0));
    for(let depth=$pos.depth;depth>0;depth--)if($pos.node(depth).type===schema.nodes.table){
      const position=$pos.before(depth);
      if(tableInfo()?.position!==position)view.dispatch(view.state.tr.setSelection(TextSelection.near(view.state.doc.resolve(position+4))));
      notify({type:"edit-table",table:tableInfo(position)});return true;
    }
    return false;
  }
  function documentOutline(){
    const headings=[],styles=documentStyles(view.state.doc);
    view.state.doc.descendants((node,position)=>{
      if(node.type===schema.nodes.heading){
        headings.push({position,level:node.attrs.level,kind:styles[nodeStyle(node)]?.kind||`H${node.attrs.level}`,
          text:node.textBetween(0,node.content.size," "," ").replace(/\s+/gu," ").trim()||"Untitled heading"});
        return false;
      }
      if(node.isTextblock)return false;
    });
    return {documentId,revision,headings};
  }
  function linkRange(){
    const selection=view.state.selection,mark=schema.marks.link.isInSet(selectionMarks(view.state));
    if(!mark)return null;
    let from=selection.from,to=selection.to;
    if(selection.empty){
      const candidates=[];view.state.doc.descendants((node,pos)=>{if(node.isText&&node.marks.some(m=>m.type===schema.marks.link&&m.attrs.href===mark.attrs.href))candidates.push({from:pos,to:pos+node.nodeSize});});
      const index=candidates.findIndex(item=>item.from<=from&&item.to>=from);
      if(index>=0){from=candidates[index].from;to=candidates[index].to;for(let i=index-1;i>=0&&candidates[i].to===from;i--)from=candidates[i].from;for(let i=index+1;i<candidates.length&&candidates[i].from===to;i++)to=candidates[i].to;}
    }
    return {href:mark.attrs.href,from,to,text:view.state.doc.textBetween(from,to,'\n')};
  }
  const stateMessage = () => {
    const state=view.state;
    const parent=state.selection.$from.parent;
    const styles=documentStyles(state.doc),name=nodeStyle(parent),preset=styles[name]||DEFAULT_STYLES.Normal;
    const format={columns:state.selection.$from.node(1)?.type===schema.nodes.column_section?state.selection.$from.node(1).attrs.columns:1,font:markValue(state,schema.marks.font,"family")||preset.font,size:markValue(state,schema.marks.size,"size")||`${preset.size}pt`,
      color:markValue(state,schema.marks.color,"color")||null,highlight:markValue(state,schema.marks.highlight,"color")||null,
      align:parent.attrs.align||"left",lineSpacing:parent.attrs.lineSpacing||1.5,style:name};
    for (const name of ["strong","em","underline","strike","subscript","superscript"]) format[name]=markActive(state,schema.marks[name]);
    if(markValue(state,schema.marks.highlight,"autoContrast")&&highlightForeground(format.highlight)!=="inherit")format.color=highlightForeground(format.highlight);
    format.strong ||= preset.bold&&!markActive(state,schema.marks.regular);
    format.checklist=false;
    for(let depth=state.selection.$from.depth;depth>0;depth--)if(state.selection.$from.node(depth).type===schema.nodes.checklist)format.checklist=true;
    format.em ||= preset.italic&&!markActive(state,schema.marks.upright);
    format.font_weight=markValue(state,schema.marks.numeric_weight,'weight')??(format.strong?700:400);format.strong=format.font_weight>=600;
    format.font_style=markValue(state,schema.marks.slant,'value')||(markActive(state,schema.marks.upright)?'normal':format.em?'italic':'normal');format.em=format.font_style==='italic'||format.font_style==='oblique';
    format.stretch=markValue(state,schema.marks.stretch,'value')||'normal';
    return {type:"state",ready:true,documentId,revision,dirty:isDirty(),words,format,styles,selectionFrom:state.selection.from,selectionTo:state.selection.to,flatFrom:Array.from(state.doc.textBetween(0,state.selection.from,"\n","\ufffc")).length,flatTo:Array.from(state.doc.textBetween(0,state.selection.to,"\n","\ufffc")).length,selectedText:state.doc.textBetween(state.selection.from,state.selection.to,"\n"),link:markValue(state,schema.marks.link,"href")||null,linkInfo:linkRange(),search:search.summary(state),table:tableInfo(),textbox:textboxInfo(),image:imageInfo(),
      canUndo:undo(state),canRedo:redo(state)};
  };
  const send=()=>{clearTimeout(updateTimer);notify(stateMessage());};
  const recalculateWords = () => {
    words=view.state.doc.textBetween(0,view.state.doc.content.size," ").trim().split(/\s+/u).filter(Boolean).length;
    send();
  };
  function leaveTable(state,dispatch,before=false,position=null){
    const info=tableInfo(position);if(!info)return false;
    const table=state.doc.nodeAt(info.position),boundary=before?info.position:info.position+table.nodeSize;
    const $at=state.doc.resolve(boundary),adjacent=before?$at.nodeBefore:$at.nodeAfter;
    if(dispatch){
      let tr=state.tr,target;
      if(adjacent?.isTextblock&&(before||!info.floating||adjacent.type===schema.nodes.paragraph)){
        target=before?boundary-1:boundary+1;
        if(!before&&info.floating&&adjacent.type===schema.nodes.paragraph)
          tr.setNodeMarkup(boundary,null,{...adjacent.attrs,clear:true});
      }else{
        tr.insert(boundary,schema.nodes.paragraph.create({clear:!before&&info.floating}));target=boundary+1;
      }
      tr.setSelection(TextSelection.create(tr.doc,target));tr.setStoredMarks([]);dispatch(tr.scrollIntoView());
    }
    return true;
  }
  function continueParagraph(state,dispatch){
    const previous=state.selection.$from.parent;
    return splitBlockAs((node,atEnd)=>{
      const type=atEnd&&node.type===schema.nodes.heading?schema.nodes.paragraph:node.type;
      return {type,attrs:{...node.attrs,styleName:type===schema.nodes.paragraph&&node.type===schema.nodes.heading?'Normal':node.attrs.styleName}};
    })(state,tr=>{if(previous.type!==schema.nodes.heading)tr.ensureMarks(state.storedMarks||state.selection.$from.marks());dispatch?.(tr);});
  }
  const customKeys={
    "Alt-Enter":(state,dispatch)=>leaveTable(state,dispatch),
    "Alt-Shift-Enter":(state,dispatch)=>leaveTable(state,dispatch,true),
    "Enter":chainCommands(splitListItem(schema.nodes.checklist_item,{checked:false}),splitListItem(schema.nodes.list_item),liftEmptyBlock,continueParagraph),
    "Mod-Enter":()=>execute("pageBreak"),
    "Mod-z":()=>execute("undo"),"Mod-Shift-z":()=>execute("redo"),"Mod-y":redo,
    "Mod-b":()=>execute("bold"),"Mod-i":()=>execute("italic"),"Mod-u":()=>execute("underline"),
    "Tab":chainCommands(goToNextCell(1),sinkListItem(schema.nodes.checklist_item),sinkListItem(schema.nodes.list_item),(state,dispatch)=>{dispatch?.(state.tr.insertText("\t"));return true;}),
    "Shift-Tab":chainCommands(goToNextCell(-1),liftListItem(schema.nodes.checklist_item),liftListItem(schema.nodes.list_item)),
  };
  const makeState = doc => EditorState.create({doc,plugins:[history(),search.plugin,keymap(customKeys),keymap(baseKeymap),columnResizing({View:DocumentTableView}),tableEditing()]});
  const view = new EditorView(mount,{
    state:makeState(schema.topNodeType.createAndFill()),
    attributes:{class:"document-editor",spellcheck:"true","aria-label":"Document"},
    nodeViews:{image:imageNodeView,checklist_item(node,view,getPos){
      const dom=document.createElement("li"),checkbox=document.createElement("input"),contentDOM=document.createElement("div");
      checkbox.type="checkbox";checkbox.contentEditable="false";contentDOM.className="checklist-content";
      dom.append(checkbox,contentDOM);
      function update(current){
        if(current.type!==schema.nodes.checklist_item)return false;
        checkbox.checked=current.attrs.checked;dom.dataset.checked=String(current.attrs.checked);
        checkbox.setAttribute("aria-label",current.attrs.checked?"Mark item incomplete":"Mark item complete");return true;
      }
      update(node);
      checkbox.addEventListener("change",()=>{
        if(!view.editable){checkbox.checked=!!view.state.doc.nodeAt(getPos())?.attrs.checked;return;}
        const pos=getPos();if(typeof pos!=="number")return;
        view.dispatch(closeHistory(view.state.tr.setNodeMarkup(pos,null,{checked:checkbox.checked})));view.focus();
      });
      return {dom,contentDOM,update,stopEvent:event=>event.target===checkbox,
        ignoreMutation:record=>record.type==="attributes"&&(record.target===checkbox||record.target===dom)};
    }},
    handleDOMEvents:{
      keydown(view,event){
        if(!view.state.selection.empty&&(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey)){
          event.preventDefault();const bounds=view.coordsAtPos(view.state.selection.from);send();notify({type:'text-context',x:bounds.left,y:bounds.bottom});return true;
        }
        return false;
      },
      mousedown(view,event){
        const button=event.target.closest?.("[data-table-properties]");
        if(button){event.preventDefault();event.stopPropagation();return editTableAt(button.closest(".tableWrapper"));}
        return false;
      },
      dblclick(view,event){
        if(event.target.matches?.('img:not(.ProseMirror-separator)')){
          const position=view.posAtDOM(event.target,0);
          if(view.state.doc.nodeAt(position)?.type===schema.nodes.image){
            event.preventDefault();view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc,position)));
            notify({type:"edit-image",image:imageInfo(position)});return true;
          }
        }
        const wrapper=event.target.closest?.(".tableWrapper");if(!wrapper)return false;
        const rect=wrapper.querySelector("table").getBoundingClientRect();
        if(Math.min(Math.abs(event.clientX-rect.left),Math.abs(event.clientX-rect.right),Math.abs(event.clientY-rect.top),Math.abs(event.clientY-rect.bottom))<=8){
          event.preventDefault();return editTableAt(wrapper);
        }
        return false;
      },
    },
    transformPastedHTML:html=>fragmentHTML(parseHTML(html)),
    dispatchTransaction(tr){
      if(tr.docChanged&&!view.editable)return;
      if(tr.docChanged){try{assertLimits(tr.doc);}catch(error){notify({type:"error",message:error.message});return;}}
      const oldStyles=view.state.doc.attrs.styles;
      view.updateState(view.state.apply(tr));
      imageHandles.update();
      if(oldStyles!==view.state.doc.attrs.styles||tr.docChanged)refreshStyles();
      if(tr.docChanged) {
        revision++;
        clearTimeout(wordTimer);
        wordTimer=setTimeout(recalculateWords,250);
      }
      clearTimeout(updateTimer);
      updateTimer=setTimeout(send,20);
    },
  });
  view.dom.addEventListener('paste',event=>{
    const text=event.clipboardData?.getData('text/plain')||'',html=event.clipboardData?.getData('text/html')||'';
    const encoder=new TextEncoder();
    if(text.length>4*1024*1024||html.length>64*1024*1024||encoder.encode(text).length>4*1024*1024||encoder.encode(html).length>64*1024*1024){event.preventDefault();event.stopImmediatePropagation();notify({type:'error',message:'The clipboard exceeds Twinly’s document limits.'});}
  },true);
  view.dom.addEventListener('contextmenu',event=>{if(!view.state.selection.empty){event.preventDefault();send();notify({type:'text-context',x:event.clientX,y:event.clientY});}});
  view.dom.addEventListener('copy',event=>{event.preventDefault();api.copy(false);});
  view.dom.addEventListener('cut',event=>{event.preventDefault();api.copy(true);});
  view.dom.addEventListener('click',event=>{const anchor=event.target.closest('a[href]');if(anchor&&(!view.editable||event.ctrlKey)){event.preventDefault();notify({type:'open-link',href:anchor.getAttribute('href')});}});
  const imageHandles=installImageHandles(view,args=>execute("resizeImage",{...args,documentId}));
  const imageLoaded=event=>{if(event.target.matches?.('img:not(.ProseMirror-separator)'))send();};
  view.dom.addEventListener("load",imageLoaded,true);
  const disposePrintLayout=installPrintLayout(view);
  cleanDoc=view.state.doc;
  refreshStyles();
  function assertLimits(doc){
    let bytes=0,paragraphs=0,spans=0,tables=0,cells=0,images=0,imageBytes=0;
    const encoder=new TextEncoder();
    doc.descendants(node=>{
      if(node.isText){bytes+=encoder.encode(node.text).length;spans+=node.marks.length;}
      if(node.isTextblock){paragraphs++;if(node.textContent.length>16384)throw new Error('A paragraph exceeds 16,384 characters.');}
      if(node.type===schema.nodes.table){tables++;const map=TableMap.get(node);if(node.childCount>100||map.width>20||node.childCount*map.width>1000)throw new Error('Tables support up to 100 rows, 20 columns and 1000 cells.');}
      if(node.type===schema.nodes.table_cell||node.type===schema.nodes.table_header){cells++;if(node.textContent.length>4096)throw new Error('A table cell supports up to 4096 characters.');}
      if(node.type===schema.nodes.image){images++;imageBytes+=Math.ceil((node.attrs.src.split(',')[1]||'').length*3/4);}
    });
    if(bytes>4*1024*1024||paragraphs>20000||spans>20000||tables>32||cells>2000||images>128||imageBytes>32*1024*1024)throw new Error('The document exceeds Twinly’s text, table or image budget.');
  }
  function execute(command,args={}) {
    if(!view.editable)return false;
    const state=view.state, dispatch=tr=>view.dispatch(tr);
    const names={bold:"strong",italic:"em",underline:"underline",strike:"strike",subscript:"subscript",superscript:"superscript"};
    let success=false;
    const inherited=documentStyles(state.doc)[nodeStyle(state.selection.$from.parent)]||DEFAULT_STYLES.Normal;
    if(command==='bold'||command==='italic'){
      const bold=command==='bold',numeric=markValue(state,schema.marks.numeric_weight,'weight'),slant=markValue(state,schema.marks.slant,'value');
      const active=bold?(numeric!==undefined?numeric>=600:markActive(state,schema.marks.strong)||(inherited.bold&&!markActive(state,schema.marks.regular))):(slant==='oblique'||markActive(state,schema.marks.em)||(inherited.italic&&!markActive(state,schema.marks.upright)));
      const types=bold?[schema.marks.strong,schema.marks.regular,schema.marks.numeric_weight]:[schema.marks.em,schema.marks.upright,schema.marks.slant];
      let tr=state.tr;for(const type of types)tr=state.selection.empty?tr.removeStoredMark(type):tr.removeMark(state.selection.from,state.selection.to,type);
      const type=active?(bold?schema.marks.regular:schema.marks.upright):(bold?schema.marks.strong:schema.marks.em);
      if(!active||inherited[bold?'bold':'italic']||numeric!==undefined||slant)tr=state.selection.empty?tr.addStoredMark(type.create()):tr.addMark(state.selection.from,state.selection.to,type.create());
      dispatch(tr);success=true;
    }
    else if(names[command]) success=toggleMark(schema.marks[names[command]])(state,dispatch);
    else if(command==="undo"||command==="redo") success=(command==="undo"?undo:redo)(state,dispatch);
    else if(command==="columns") {
      const count=Number(args.value);
      if(![1,2,3].includes(count))throw new Error("Choose one, two or three columns.");
      const topIndex=state.selection.$from.index(0),top=state.doc.child(topIndex);
      const tr=closeHistory(state.tr);
      if(top.type===schema.nodes.column_section){
        let pos=0;for(let i=0;i<topIndex;i++)pos+=state.doc.child(i).nodeSize;
        if(top.attrs.columns!==count)tr.setNodeMarkup(pos,null,{columns:count});
      }else{
        let startIndex=topIndex,endIndex=topIndex+1;
        while(startIndex>0&&![schema.nodes.page_break,schema.nodes.column_section].includes(state.doc.child(startIndex-1).type))startIndex--;
        while(endIndex<state.doc.childCount&&![schema.nodes.page_break,schema.nodes.column_section].includes(state.doc.child(endIndex).type))endIndex++;
        let start=0;for(let i=0;i<startIndex;i++)start+=state.doc.child(i).nodeSize;
        let end=start;const blocks=[];for(let i=startIndex;i<endIndex;i++){const node=state.doc.child(i);blocks.push(node);end+=node.nodeSize;}
        if(count!==1){
          tr.replaceWith(start,end,schema.nodes.column_section.create({columns:count},blocks));
          tr.setSelection(TextSelection.create(tr.doc,state.selection.from+1,state.selection.to+1));
        }
      }
      if(tr.docChanged)dispatch(tr);
      success=true;
    } else if(command==="style") {
      const name=args.name||(args.level?`H${args.level}`:"Normal"),preset=documentStyles(state.doc)[name];
      if(!preset)throw new Error("Unknown paragraph style.");
      let tr=state.tr;
      setBlockType(preset.level?schema.nodes.heading:schema.nodes.paragraph,{level:preset.level,styleName:name,align:state.selection.$from.parent.attrs.align||"left",lineSpacing:state.selection.$from.parent.attrs.lineSpacing||1.5,clear:state.selection.$from.parent.attrs.clear||false})(state,candidate=>{tr=candidate;});
      dispatch(tr.setStoredMarks(null));success=true;
    } else if(command==="defineStyle") {
      if(!validName(args.name))throw new Error("Use 1–40 letters, numbers, spaces, dashes or underscores for the style name.");
      const styles={...documentStyles(state.doc)},parent=state.selection.$from.parent;
      const inherited=styles[nodeStyle(parent)]||DEFAULT_STYLES.Normal;
      const size=markValue(state,schema.marks.size,"size")||`${inherited.size}pt`;
      const preset={kind:inherited.kind,level:inherited.level,font:markValue(state,schema.marks.font,"family")||inherited.font,
        size:parseFloat(size)*(size.endsWith("px")?.75:1),
        bold:markActive(state,schema.marks.strong)||(inherited.bold&&!markActive(state,schema.marks.regular)),
        italic:markActive(state,schema.marks.em)||(inherited.italic&&!markActive(state,schema.marks.upright))};
      const source=args.oldName??(Object.hasOwn(styles,args.name)?args.name:null);
      if(args.oldName&&!Object.hasOwn(styles,args.oldName))throw new Error("The original style no longer exists.");
      if(args.oldName&&args.oldName!==args.name){
        if(Object.hasOwn(DEFAULT_STYLES,args.oldName))throw new Error("Create a custom style to use a different name.");
        if(Object.hasOwn(styles,args.name))throw new Error("A style with this name already exists.");
      }
      if(args.create&&Object.hasOwn(styles,args.name))throw new Error("A style with this name already exists.");
      const candidate=args.preset||preset;
      if(!candidate||typeof candidate.font!=="string"||!(/^[\p{L}\p{N} ,\-]{1,80}$/u).test(candidate.font)||!Number.isFinite(candidate.size))throw new Error("Invalid style font or size.");
      if(args.oldName&&Object.hasOwn(DEFAULT_STYLES,args.oldName)&&candidate.kind&&candidate.kind!==styles[args.oldName].kind)
        throw new Error("Create a custom style to use a different style type.");
      if(args.oldName&&args.oldName!==args.name)delete styles[args.oldName];
      styles[args.name]=candidate;
      const checked=normaliseStyles(styles),definition=checked[args.name];
      let tr=closeHistory(state.tr.setDocAttribute("styles",checked));
      if(args.twinlyDefinition&&/^[a-f0-9]{32}$/.test(args.twinlyDefinition.id))tr.setDocAttribute('customStyles',{...state.doc.attrs.customStyles,[args.twinlyDefinition.id]:args.twinlyDefinition});
      const updateBlock=(node,pos)=>{
        tr.setNodeMarkup(pos,definition.level?schema.nodes.heading:schema.nodes.paragraph,
          {...node.attrs,level:definition.level,styleName:args.name});
      };
      if(source)state.doc.descendants((node,pos)=>{if(node.isTextblock&&nodeStyle(node)===source)updateBlock(node,pos);});
      if(!args.oldName){
        state.doc.nodesBetween(state.selection.from,state.selection.to,(node,pos)=>{
          if(!node.isTextblock)return;
          if(!state.selection.empty&&state.selection.to===pos+1)return false;
          updateBlock(node,pos);
          tr.removeMark(pos+1,pos+node.nodeSize-1,schema.marks.font);
          tr.removeMark(pos+1,pos+node.nodeSize-1,schema.marks.size);
        });
      }
      dispatch(tr.setStoredMarks(null));success=true;
    } else if(command==="deleteStyle") {
      if(args.documentId!==undefined&&args.documentId!==documentId)throw new Error("This style belongs to a different document.");
      if(Object.hasOwn(DEFAULT_STYLES,args.name))throw new Error("Built-in styles cannot be deleted.");
      const styles={...documentStyles(state.doc)},preset=styles[args.name];
      if(!validName(args.name)||!Object.hasOwn(styles,args.name))throw new Error("The selected style no longer exists.");
      const fallback=preset.kind==="Body"?"Normal":preset.kind,definition=styles[fallback];
      delete styles[args.name];
      const tr=closeHistory(state.tr).setDocAttribute("styles",styles);
      state.doc.descendants((node,pos)=>{
        if(node.isTextblock&&nodeStyle(node)===args.name)
          tr.setNodeMarkup(pos,definition.level?schema.nodes.heading:schema.nodes.paragraph,
            {...node.attrs,level:definition.level,styleName:fallback});
      });
      dispatch(tr.setStoredMarks(null));success=true;
    } else if(command==="pageMargins") {
      dispatch(closeHistory(state.tr).setDocAttribute("margins",normaliseMargins(args.value)));
      success=true;
    } else if(command==="lineSpacing") {
      const value=bounded(args.value,.95,3,1.5);let tr=state.tr;
      state.doc.nodesBetween(state.selection.from,state.selection.to,(node,pos)=>{
        if(node.type===schema.nodes.paragraph||node.type===schema.nodes.heading){
          if(!state.selection.empty&&state.selection.to===pos+1)return false;
          tr.setNodeMarkup(pos,null,{...node.attrs,lineSpacing:value});
        }
      });
      dispatch(closeHistory(tr));success=true;
    } else if(command==="align") {
      let tr=state.tr;
      state.doc.nodesBetween(state.selection.from,state.selection.to,(node,pos)=>{
        if(node.type===schema.nodes.paragraph||node.type===schema.nodes.heading) tr.setNodeMarkup(pos,null,{...node.attrs,align:args.value});
      });
      dispatch(tr);success=true;
    } else if(["checklist","bullets","numbered"].includes(command)) {
      const type=schema.nodes[{checklist:'checklist',bullets:'bullet_list',numbered:'ordered_list'}[command]];
      let previous=null;
      for(let depth=state.selection.$from.depth;depth>0;depth--){const node=state.selection.$from.node(depth);if([schema.nodes.checklist,schema.nodes.bullet_list,schema.nodes.ordered_list].includes(node.type)){previous={node,position:state.selection.$from.before(depth)};break;}}
      const itemType=type===schema.nodes.checklist?schema.nodes.checklist_item:schema.nodes.list_item;
      if(previous&&previous.node.type!==type){
        const children=[];previous.node.forEach(item=>children.push(itemType.create(itemType===schema.nodes.checklist_item?{checked:!!item.attrs.checked}:null,item.content)));
        const tr=state.tr.replaceWith(previous.position,previous.position+previous.node.nodeSize,type.create(null,children));
        tr.setSelection(TextSelection.between(tr.doc.resolve(state.selection.from),tr.doc.resolve(state.selection.to)));dispatch(tr);success=true;
      }else success=(previous?liftListItem(itemType):wrapInList(type))(state,dispatch);
    }
    else if(command==="lift") success=lift(state,dispatch);
    else if(command==="updateTextbox") {
      if(args.documentId!==documentId)throw new Error("This text box belongs to a different document.");
      const box=state.doc.nodeAt(args.position);
      if(box?.type!==schema.nodes.textbox)throw new Error("The selected text box no longer exists.");
      dispatch(closeHistory(state.tr.setNodeMarkup(args.position,null,{
        width:bounded(args.width,60,1600,150),height:bounded(args.height,40,2000,100),
        borderWidth:bounded(args.borderWidth,0,12,1),floating:!!args.floating,background:backgroundColour(args.background)})));success=true;
    }
    else if(command==="textbox") success=wrapIn(schema.nodes.textbox,{
      width:bounded(args.width??150,60,1600,150),height:bounded(args.height??100,40,2000,100),
      borderWidth:bounded(args.borderWidth??1,0,12,1),floating:args.floating??true,background:backgroundColour(args.background)})(state,dispatch);
    else if(["font","size","color","highlight","link"].includes(command)) {
      const type=schema.marks[command];
      if((command==="color"||command==="highlight")&&!args.value){
        const accidentalColour=marks=>{
          const highlight=schema.marks.highlight.isInSet(marks),colour=schema.marks.color.isInSet(marks);
          if(!highlight?.attrs.autoContrast||!colour||colour.attrs.explicit)return false;
          const actual=backgroundColour(colour.attrs.color);
          return (actual==="white"?"rgb(255, 255, 255)":actual)===backgroundColour(highlightForeground(highlight.attrs.color));
        };
        let tr=state.tr;
        if(state.selection.empty){
          if(command==="highlight"&&accidentalColour(state.storedMarks||state.selection.$from.marks()))tr.removeStoredMark(schema.marks.color);
          tr.removeStoredMark(type);
        }else{
          if(command==="highlight")state.doc.nodesBetween(state.selection.from,state.selection.to,(node,pos)=>{
            if(node.isText&&accidentalColour(node.marks))tr.removeMark(Math.max(pos,state.selection.from),Math.min(pos+node.nodeSize,state.selection.to),schema.marks.color);
          });
          tr.removeMark(state.selection.from,state.selection.to,type);
        }
        dispatch(tr);view.focus();send();return true;
      }
      const attrs=command==="font"?{family:args.value}:command==="size"?{size:`${Math.max(1,Math.min(1000,Number(args.value)))}pt`}:
        command==="link"?{href:args.value}:command==="highlight"?{color:args.value,autoContrast:true}:{color:args.value,explicit:true};
      if(command==="link"&&!safeLink(args.value)) throw new Error("Use an https://, http:// or mailto: link.");
      const mark=type.create(attrs);
      dispatch(state.selection.empty?state.tr.addStoredMark(mark):state.tr.addMark(state.selection.from,state.selection.to,mark));success=true;
    } else if(command==="removeLink") {
      const range=linkRange(),tr=state.tr.removeStoredMark(schema.marks.link);if(range)tr.removeMark(range.from,range.to,schema.marks.link);else if(!state.selection.empty)tr.removeMark(state.selection.from,state.selection.to,schema.marks.link);dispatch(tr);success=true;
    } else if(command==="fontDescription") {
      let tr=closeHistory(state.tr);
      const types=[schema.marks.font,schema.marks.size,schema.marks.strong,schema.marks.regular,schema.marks.numeric_weight,schema.marks.em,schema.marks.upright,schema.marks.slant,schema.marks.stretch];
      for(const type of types)tr=state.selection.empty?tr.removeStoredMark(type):tr.removeMark(state.selection.from,state.selection.to,type);
      const marks=[schema.marks.font.create({family:args.family}),schema.marks.size.create({size:`${bounded(args.size,1,1000,12)}pt`}),
        args.weight===700?schema.marks.strong.create():args.weight===400?schema.marks.regular.create():schema.marks.numeric_weight.create({weight:bounded(args.weight,100,1000,400)}),
        args.style==='italic'?schema.marks.em.create():args.style==='oblique'?schema.marks.slant.create({value:'oblique'}):schema.marks.upright.create(),schema.marks.stretch.create({value:stretches.includes(args.stretch)?args.stretch:'normal'})];
      for(const mark of marks)tr=state.selection.empty?tr.addStoredMark(mark):tr.addMark(state.selection.from,state.selection.to,mark);
      dispatch(tr);success=true;
    } else if(command==="character") {
      let tr=state.tr;
      for(const [key,value] of Object.entries(args)){
        const mapping={font_weight:value===700?[schema.marks.strong,{}]:value===400?[schema.marks.regular,{}]:[schema.marks.numeric_weight,{weight:value}],stretch:[schema.marks.stretch,{value}],font_style:value==='italic'?[schema.marks.em,{}]:value==='normal'?[schema.marks.upright,{}]:[schema.marks.slant,{value}]};
        if(key==='font_style')for(const type of [schema.marks.em,schema.marks.upright,schema.marks.slant])tr=state.selection.empty?tr.removeStoredMark(type):tr.removeMark(state.selection.from,state.selection.to,type);
        const entry=mapping[key];if(!entry)continue;
        tr=state.selection.empty?(value===null?tr.removeStoredMark(entry[0]):tr.addStoredMark(entry[0].create(entry[1]))):(value===null?tr.removeMark(state.selection.from,state.selection.to,entry[0]):tr.addMark(state.selection.from,state.selection.to,entry[0].create(entry[1])));
      }
      dispatch(tr);success=true;
    } else if(command==="toggleCheck") {
      let tr=state.tr;
      for(let depth=state.selection.$from.depth;depth>0;depth--){const node=state.selection.$from.node(depth);if(node.type===schema.nodes.checklist_item){tr.setNodeMarkup(state.selection.$from.before(depth),null,{...node.attrs,checked:!node.attrs.checked});break;}}
      dispatch(tr);success=true;
    } else if(command==="deleteImage") {
      const info=imageInfo();if(info){dispatch(closeHistory(state.tr.delete(info.position,info.position+state.doc.nodeAt(info.position).nodeSize)));success=true;}
    } else if(command==="clear") {
      let tr=state.selection.empty?state.tr.setStoredMarks([]):state.tr.removeMark(state.selection.from,state.selection.to);
      if(!state.selection.empty)state.doc.nodesBetween(state.selection.from,state.selection.to,(node,pos)=>{if(node.type===schema.nodes.paragraph||node.type===schema.nodes.heading)tr.setNodeMarkup(pos,schema.nodes.paragraph,{...node.attrs,styleName:'Normal',align:'left',lineSpacing:1});});
      dispatch(tr);success=true;
    } else if(command==="resizeImage") {
      if(args.documentId!==documentId)throw new Error("This picture belongs to a different document.");
      const node=state.doc.nodeAt(args.position);
      if(node?.type!==schema.nodes.image)throw new Error("The selected picture no longer exists.");
      const width=args.width===null?null:Math.round(Number(args.width));
      if(width!==null&&(!Number.isFinite(width)||width<1||width>1600))throw new Error("Choose a width between 1 and 1600 pixels.");
      const tr=closeHistory(state.tr).setNodeMarkup(args.position,null,{...node.attrs,width});
      tr.setSelection(NodeSelection.create(tr.doc,args.position));dispatch(tr.scrollIntoView());success=true;
    } else if(command==="image") {
      if(!safeImage(args.src)) throw new Error("Unsupported image format.");
      dispatch(state.tr.replaceSelectionWith(schema.nodes.image.create({src:args.src,alt:args.alt||"",width:args.width||null})).scrollIntoView());success=true;
    } else if(command==="exitTable") {
      if(args.documentId!==undefined&&args.documentId!==documentId)throw new Error("This table belongs to a different document.");
      success=leaveTable(state,dispatch,!!args.before,args.position??null);
    } else if(command==="deleteTable") {
      if(args.documentId!==undefined&&args.documentId!==documentId)throw new Error("This table belongs to a different document.");
      const info=tableInfo(args.position??null);if(!info)throw new Error("The selected table no longer exists.");
      const table=state.doc.nodeAt(info.position);
      const tr=closeHistory(state.tr).delete(info.position,info.position+table.nodeSize);
      tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(info.position,tr.doc.content.size)),1));
      tr.setStoredMarks(null);dispatch(tr.scrollIntoView());success=true;
    } else if(command==="updateTable") {
      if(args.documentId!==documentId)throw new Error("This table belongs to a different document.");
      const info=tableInfo(args.position);if(!info)throw new Error("The selected table no longer exists.");
      const old=state.doc.nodeAt(info.position),rowCount=Math.trunc(bounded(args.rows,1,Math.max(100,info.rows),info.rows)),colCount=Math.trunc(bounded(args.cols,1,Math.max(20,info.cols),info.cols));
      if(info.merged&&(rowCount!==info.rows||colCount!==info.cols))throw new Error("Split merged cells before changing the row or column count.");
      const rows=[];
      for(let r=0;r<rowCount;r++){
        const oldRow=r<old.childCount?old.child(r):null,cells=[];
        const count=info.merged&&oldRow?oldRow.childCount:colCount;
        for(let c=0;c<count;c++){
          const cell=oldRow&&c<oldRow.childCount?oldRow.child(c):null;
          const type=r===0?schema.nodes[args.header?"table_header":"table_cell"]:(cell?.type||schema.nodes.table_cell);
          cells.push(cell?type.create(cell.attrs,cell.content,cell.marks):type.createAndFill());
        }
        rows.push(schema.nodes.table_row.create(oldRow?.attrs,cells));
      }
      const table=schema.nodes.table.create({borderWidth:bounded(args.borderWidth,0,12,info.borderWidth),width:bounded(args.width,25,100,info.width),floating:!!args.floating},rows);
      const tr=closeHistory(state.tr.replaceWith(info.position,info.position+old.nodeSize,table));
      tr.setSelection(TextSelection.near(tr.doc.resolve(info.position+4)));dispatch(tr.scrollIntoView());success=true;
    } else if(command==="table") {
      const rows=[];
      for(let r=0;r<Math.trunc(bounded(args.rows||3,1,100,3));r++) {
        const cells=[];
        for(let c=0;c<Math.max(1,Math.min(20,args.cols||3));c++) cells.push(schema.nodes[r===0&&args.header?"table_header":"table_cell"].createAndFill());
        rows.push(schema.nodes.table_row.create(null,cells));
      }
      const table=schema.nodes.table.create({borderWidth:bounded(args.borderWidth??1,0,12,1),width:bounded(args.width??100,25,100,100),floating:!!args.floating},rows);
      const tr=state.tr.replaceSelectionWith(table,false);
      tr.doc.descendants((node,pos)=>{if(node===table){
        const after=pos+node.nodeSize;
        if(!tr.doc.resolve(after).nodeAfter?.isTextblock)tr.insert(after,schema.nodes.paragraph.create());
        tr.setSelection(TextSelection.near(tr.doc.resolve(pos+4)));return false;
      }});
      dispatch(tr.scrollIntoView());success=true;
    } else if(command==="horizontalRule") {
      const tr=state.tr.replaceSelectionWith(schema.nodes.horizontal_rule.create(),false);
      if(!tr.selection.$from.parent.isTextblock){
        const after=tr.selection.to;
        tr.insert(after,schema.nodes.paragraph.create());tr.setSelection(TextSelection.near(tr.doc.resolve(after+1)));
      }
      dispatch(tr.scrollIntoView());success=true;
    } else if(command==="pageBreak") {
      const tr=state.tr.replaceSelectionWith(schema.nodes.page_break.create(),false);
      if(!tr.selection.$from.parent.isTextblock){
        const after=tr.selection.to;
        tr.insert(after,schema.nodes.paragraph.create());tr.setSelection(TextSelection.near(tr.doc.resolve(after+1)));
      }
      // A page break terminates the current layout section. Following blocks
      // become ordinary full-width blocks until another column layout is chosen.
      const topIndex=state.selection.$from.index(0),top=state.doc.child(topIndex);
      if(top.type===schema.nodes.column_section){
        let pos=0;for(let i=0;i<topIndex;i++)pos+=state.doc.child(i).nodeSize;
        const section=tr.doc.nodeAt(pos),before=[],after=[];let marker=null;
        section.forEach(node=>{if(node.type===schema.nodes.page_break&&!marker)marker=node;else (marker?after:before).push(node);});
        if(marker){
          if(!after.length)after.push(schema.nodes.paragraph.create());
          const replacement=[];
          if(before.length)replacement.push(schema.nodes.column_section.create(top.attrs,before));
          const breakPos=pos+replacement.reduce((sum,node)=>sum+node.nodeSize,0);
          replacement.push(marker,...after);
          tr.replaceWith(pos,pos+section.nodeSize,replacement);
          tr.setSelection(TextSelection.near(tr.doc.resolve(breakPos+1),1));
        }
      }
      dispatch(tr.scrollIntoView());success=true;
    } else if(command==="paper") {
      document.documentElement.style.setProperty("--paper-width",args.value==="Letter"?"816px":"794px");success=true;
    } else if(command==="paragraphBreak") {
      success=customKeys.Enter(state,dispatch,view);
    } else if(command==="insertText") {
      dispatch(state.tr.insertText(args.text).scrollIntoView());success=true;
    } else throw new Error(`Unknown editor action: ${command}`);
    view.focus();send();return success;
  }
  const api={
    exec:execute,
    setEditable(value){view.setProps({editable:()=>!!value});view.dom.querySelectorAll("input[type=checkbox]").forEach(box=>box.disabled=!value);imageHandles.update();return true;},
    setLayout(options){
      document.documentElement.dataset.theme=options.dark?"dark":"light";
      document.documentElement.style.setProperty('--document-zoom',options.zoom||1);
      document.body.style.paddingTop=(options.top||80)+'px';return true;
    },
    copy(cut=false){
      const {from,to}=view.state.selection;if(from===to)return false;
      const fragment=DOMSerializer.fromSchema(schema).serializeFragment(view.state.selection.content().content),holder=document.createElement('div');holder.append(fragment);
      notify({type:'clipboard',text:view.state.doc.textBetween(from,to,'\n'),html:holder.innerHTML});
      if(cut&&view.editable)view.dispatch(view.state.tr.deleteSelection());return true;
    },
    insertLinkedText(text,href){if(!safeLink(href))throw new Error('Invalid link.');const {from,to}=view.state.selection.empty?(linkRange()||view.state.selection):view.state.selection;const tr=view.state.tr.insertText(text,from,to).addMark(from,from+text.length,schema.marks.link.create({href}));view.dispatch(tr);send();return true;},
    selectTextOffsets(from,to=from){
      // GTK uses Unicode character offsets; ProseMirror uses UTF-16 positions.
      // Follow Fragment.textBetween exactly, retaining only the two requested positions.
      let flat=0,first=true,start=null,end=null;
      const record=pos=>{if(flat===from)start=pos;if(flat===to)end=pos;};
      view.state.doc.descendants((node,pos)=>{
        if(node.isBlock&&(node.isLeaf||node.isTextblock)){
          if(!first)flat++;first=false;record(node.isTextblock?pos+1:pos);
        }
        if(node.isText){let local=0;record(pos);for(const character of node.text){local+=character.length;flat++;record(pos+local);}}
        else if(node.isLeaf){record(pos);flat++;record(pos+node.nodeSize);}
      });
      const fallback=Selection.atEnd(view.state.doc).from;
      const selection=TextSelection.between(view.state.doc.resolve(start??fallback),view.state.doc.resolve(end??start??fallback));
      if(!selection.eq(view.state.selection))view.dispatch(view.state.tr.setSelection(selection));return true;
    },
    replaceTextOffsets(from,to,text){
      if(!view.editable)return false;
      api.selectTextOffsets(from,to);
      if(text.includes('\n'))view.pasteText(text);
      else view.dispatch(view.state.tr.insertText(text));
      send();return true;
    },
    checkpoint(){view.dispatch(closeHistory(view.state.tr));return true;},
    selectNode(position){view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc,position)));send();return true;},
    getMargins(){return normaliseMargins(view.state.doc.attrs.margins);},
    setMargins(value){
      view.dispatch(view.state.tr.setDocAttribute('margins',normaliseMargins(value)));
      return normaliseMargins(view.state.doc.attrs.margins);
    },
    find(query,caseSensitive=false,wholeWords=false){const result=search.find(view,query,caseSensitive,wholeWords);send();return result;},
    findNext(direction=1){const result=search.next(view,direction);send();return result;},
    replaceMatch(replacement,all=false){const result=search.replace(view,replacement,all);send();return result;},
    clearSearch(){const result=search.clear(view);send();return result;},
    loadHTML(html){
      clearTimeout(wordTimer);exports.clear();
      const doc=parseHTML(html);assertLimits(doc);documentId++;revision=0;cleanDoc=doc;
      view.updateState(makeState(doc));imageHandles.update();refreshStyles();window.scrollTo(0,0);recalculateWords();
      return {documentId,revision};
    },
    exportHTML(){exports.set(revision,view.state.doc);while(exports.size>3)exports.delete(exports.keys().next().value);return {html:serializeHTML(view.state.doc),revision,documentId};},
    markSaved(id,rev){if(id===documentId&&exports.has(rev)){cleanDoc=exports.get(rev);exports.clear();send();return true;}return false;},
    focus(){view.focus();return true;},
    getTable:tableInfo,
    getImage:imageInfo,
    getTextbox:textboxInfo,
    getOutline:documentOutline,
    gotoHeading(position,id,rev,topMargin=180){
      if(id!==documentId||rev!==revision||!Number.isInteger(position)||position<0||position>=view.state.doc.content.size||view.state.doc.nodeAt(position)?.type!==schema.nodes.heading)return false;
      view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,position+1)).scrollIntoView());
      view.focus();send();
      const element=view.nodeDOM(position);
      if(element?.getBoundingClientRect)window.scrollTo(window.scrollX,Math.max(0,window.scrollY+element.getBoundingClientRect().top-topMargin));
      return true;
    },
    getText(){return view.state.doc.textBetween(0,view.state.doc.content.size,"\n","\ufffc");},
    getState(){return {json:view.state.doc.toJSON(),revision,documentId,dirty:isDirty()};},
    getToolbarState:stateMessage,
    getSummary(){return {revision,documentId,dirty:isDirty()};},
    setAppearance(options){
      glassOptions=options;
      if(!glassReference){
        glassReference=document.createElement("div");glassReference.setAttribute("aria-hidden","true");
        glassReference.style.cssText="position:fixed;left:0;top:0;width:100vw;height:0;visibility:hidden;pointer-events:none";
        document.body.append(glassReference);
      }
      // GTK reports logical widget pixels. WebKit's CSS viewport may have a
      // different scale (e.g. Flatpak font/DPI settings), and stable gutters can
      // offset fixed-position elements. Calibrate both against the real viewport.
      const reference=glassReference.getBoundingClientRect();
      const scale=options.viewport?.width>0&&reference.width>0?options.viewport.width/reference.width:1;
      const theme=["light","dark","mixed"].includes(options.theme)?options.theme:"mixed";
      document.documentElement.dataset.theme=theme;
      document.documentElement.style.setProperty("--glass-blur",`${(options.blur_radius||0)/scale}px`);
      for(const name of ["header","toolbar","search","outline"]){
        const element=document.getElementById(`${name}-glass`);
        if(!element)continue;
        const bounds=options.geometry?.[name];
        element.style.display=(name==="header"||options.fallback)&&options.blur&&bounds?"block":"none";
        if(bounds){
          element.style.left=`${bounds.left/scale-reference.left}px`;
          element.style.top=`${bounds.top/scale-reference.top}px`;
          element.style.width=`${bounds.width/scale}px`;
          element.style.height=`${bounds.height/scale}px`;
          if(name!=="header")element.style.borderRadius=`${(name==="toolbar"?20:18)/scale}px`;
          if(name==="header"){
            // An eased fade begins inside the header and continues into the document.
            // Zero slope at either end avoids a visible start/stop in the glass tint.
            const fadeStart=Math.max(0,bounds.height-16)/scale,fadeLength=112/scale;
            element.style.setProperty("--fade-start",`${fadeStart}px`);
            element.style.setProperty("--fade-length",`${fadeLength}px`);
            element.style.height=`${fadeStart+fadeLength}px`;
          }
        }
        const dark=theme==="dark"||(name!=="header"&&theme==="mixed");
        element.style.background=dark?`rgba(37,39,45,${options.opacity})`:`rgba(250,250,252,${options.opacity})`;
      }
      return true;
    },
    select(from,to=from){view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,from,to)));view.focus();},
    destroy(){window.removeEventListener("resize",refreshGlass);glassReference?.remove();view.dom.removeEventListener("load",imageLoaded,true);imageHandles.destroy();disposePrintLayout();clearTimeout(updateTimer);clearTimeout(wordTimer);styleSheet.remove();view.destroy();},
    view,
  };
  const refreshGlass=()=>{if(glassOptions)api.setAppearance(glassOptions);};
  window.addEventListener("resize",refreshGlass);
  recalculateWords();
  return api;
}

if(typeof window!=="undefined"&&document.getElementById("editor")) {
  window.editor=createEditor(document.getElementById("editor"),state=>{
    window.webkit?.messageHandlers?.editor?.postMessage(JSON.stringify(state));
  });
}
