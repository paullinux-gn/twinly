import {test,after} from "node:test";
import assert from "node:assert/strict";
import {JSDOM} from "jsdom";
const dom=new JSDOM("<!doctype html><body></body>",{pretendToBeVisual:true,url:"https://editor.invalid"});
after(()=>dom.window.close());
globalThis.window=dom.window;globalThis.document=dom.window.document;
Object.defineProperty(globalThis,"navigator",{value:dom.window.navigator,configurable:true});
globalThis.getComputedStyle=dom.window.getComputedStyle.bind(dom.window);
dom.window.scrollTo=()=>{};
dom.window.Range.prototype.getClientRects=()=>[];
dom.window.Range.prototype.getBoundingClientRect=()=>({left:0,right:0,top:0,bottom:0,width:0,height:0});
const {createEditor,parseHTML,serializeHTML,schema}=await import("../src/editor.js");
const {DOMParser:LiveDOMParser}=await import("prosemirror-model");
const image="data:image/png;base64,iVBORw0KGgo=";

function editor(){const mount=document.createElement("div");document.body.append(mount);return createEditor(mount);}

test("HTML roundtrip retains supported formatting, image, lists, table and textbox",()=>{
  const doc=parseHTML(`<!doctype html><html><head><title>Not document content</title></head><body>
  <h2>Résumé — Ελληνικά</h2><p style="text-align:center"><strong>Bold</strong><u>underlined</u><span style="font-size:18pt;color:red">colour</span></p>
  <ul><li><p>List item</p></li></ul><p><img src="${image}" alt="embedded"></p>
  <table><tbody><tr><td><p>Cell</p></td></tr></tbody></table><section data-textbox><p>Box</p></section></body></html>`);
  const html=serializeHTML(doc);
  assert.deepEqual(parseHTML(html).toJSON(),doc.toJSON());
  assert.ok(!doc.textContent.includes("Not document content"));
  assert.ok(html.includes(image));assert.ok(html.includes("<table"));
});

test("import discards active content and remote images and unsafe links",()=>{
  const html=serializeHTML(parseHTML(`<p>Keep<script>alert('bad')</script><img src="https://example.org/tracker.png"><a href="javascript:alert(1)">text</a><img src="${image}" onload="alert(1)"></p>`));
  assert.ok(!html.includes("alert"));assert.ok(!html.includes("tracker"));assert.ok(!html.includes("javascript:"));assert.ok(!html.includes("onload"));
  assert.ok(html.includes(image));
});

test("text editing, marks and undo/redo operate on the structured document",()=>{
  const api=editor();
  try{
    api.exec("insertText",{text:"Hello café"});api.select(1,6);api.exec("bold");
    assert.ok(api.exportHTML().html.includes("<strong>Hello</strong>"));
    api.exec("undo");assert.ok(!api.exportHTML().html.includes("<strong>Hello</strong>"));
    api.exec("redo");assert.ok(api.exportHTML().html.includes("<strong>Hello</strong>"));
    assert.equal(api.getText(),"Hello café");
    const pasted=api.view.someProp("transformPastedHTML",fn=>fn("<p>Pasted text</p>"));
    assert.ok(!pasted.includes("<title>"));assert.ok(pasted.includes("Pasted text"));
    api.select(1);assert.ok(api.exec("bullets"));assert.ok(api.exec("bullets"));
    assert.equal(api.view.state.doc.firstChild.type.name,"paragraph");
    assert.ok(api.exec("table",{rows:2,cols:2}));
    assert.equal(api.view.state.selection.$from.node(-1).type.name,"table_cell");
  }finally{api.destroy();}
});

test("asynchronous save completion never marks later edits clean",()=>{
  const api=editor();
  try{
    api.exec("insertText",{text:"Saved"});const saved=api.exportHTML();
    api.exec("insertText",{text:" later"});
    assert.ok(api.markSaved(saved.documentId,saved.revision));
    assert.ok(api.getState().dirty);
    const current=api.exportHTML();api.markSaved(current.documentId,current.revision);
    assert.equal(api.getState().dirty,false);
    api.loadHTML("<p>New document</p>");
    assert.equal(api.markSaved(saved.documentId,saved.revision),false);
    assert.equal(api.getText(),"New document");
  }finally{api.destroy();}
});

test("image insertion and export/reimport are self-contained",()=>{
  const api=editor();
  try{
    api.exec("image",{src:image,alt:"A sample"});
    const html=api.exportHTML().html;api.loadHTML(html);
    assert.ok(api.exportHTML().html.includes(image));assert.ok(!api.getState().dirty);
    assert.throws(()=>api.exec("image",{src:"file:///etc/passwd"}));
  }finally{api.destroy();}
});

test("interface themes and blur never change document contents or save state",()=>{
  const api=editor();
  try{
    api.loadHTML("<p>Unchanged document</p>");const before=api.exportHTML().html;
    api.setAppearance({theme:"dark",blur:true,opacity:.65,blur_radius:22,fallback:true,geometry:{}});
    assert.equal(document.documentElement.dataset.theme,"dark");
    assert.equal(api.exportHTML().html,before);assert.equal(api.getSummary().dirty,false);
    api.setAppearance({theme:"mixed",blur:false,opacity:1,blur_radius:0,fallback:false});
    assert.equal(document.documentElement.dataset.theme,"mixed");
    assert.equal(api.exportHTML().html,before);
  }finally{api.destroy();}
});

test("text and highlight colour removal preserves other formatting",()=>{
  const api=editor();
  try{
    api.loadHTML("<p><strong>Hello</strong></p>");api.select(1,6);
    api.exec("color",{value:"#e01b24"});api.exec("highlight",{value:"#f6d32d"});
    api.exec("color",{value:null});
    let marks=api.view.state.doc.firstChild.firstChild.marks.map(m=>m.type.name);
    assert.ok(marks.includes("strong")&&marks.includes("highlight"));assert.ok(!marks.includes("color"));
    api.exec("highlight",{value:null});marks=api.view.state.doc.firstChild.firstChild.marks.map(m=>m.type.name);
    assert.deepEqual(marks,["strong"]);assert.equal(api.getText(),"Hello");
    api.select(6);api.exec("color",{value:"#3584e4"});api.exec("insertText",{text:"x"});
    api.exec("color",{value:null});api.exec("insertText",{text:"y"});
    assert.ok(!api.view.state.doc.firstChild.lastChild.marks.some(m=>m.type.name==="color"));
  }finally{api.destroy();}
});

test("custom body and heading styles persist with HTML and can be reapplied",()=>{
  const api=editor();
  try{
    api.loadHTML("<p>First</p><p>Second</p>");api.select(1);
    api.exec("defineStyle",{name:"Body text",preset:{level:0,font:"Serif",size:14,bold:false,italic:false}});
    assert.equal(api.view.state.doc.firstChild.attrs.styleName,"Body text");
    api.exec("defineStyle",{name:"Chapter",preset:{level:2,font:"Monospace",size:20,bold:true,italic:false}});
    assert.equal(api.view.state.doc.firstChild.type.name,"heading");
    assert.equal(api.view.state.doc.firstChild.attrs.level,2);
    api.select(1,6);api.exec("bold");
    assert.ok(api.view.state.doc.firstChild.firstChild.marks.some(m=>m.type.name==="regular"));
    api.exec("bold");assert.ok(!api.view.state.doc.firstChild.firstChild.marks.some(m=>m.type.name==="regular"));
    api.select(api.view.state.doc.firstChild.nodeSize+1);api.exec("font",{value:"Sans"});
    api.exec("style",{name:"Chapter"});
    assert.equal(api.view.state.doc.lastChild.attrs.styleName,"Chapter");
    assert.ok(!api.view.state.doc.lastChild.firstChild.marks.some(m=>m.type.name==="font"));
    const json=api.getState().json,html=api.exportHTML().html;
    assert.ok(html.includes("font-family:Monospace;font-size:20pt"));
    api.loadHTML(html);assert.deepEqual(api.getState().json,json);
    assert.equal(api.getState().json.attrs.styles["Body text"].size,14);
    assert.equal(api.getState().json.attrs.styles.Chapter.level,2);
  }finally{api.destroy();}
});

test("horizontal lines span a block and remain distinct from page breaks on reload",()=>{
  const api=editor();
  try{
    api.exec("horizontalRule");api.exec("insertText",{text:"After the line"});
    assert.equal(api.view.state.doc.firstChild.type.name,"horizontal_rule");
    assert.equal(api.view.state.doc.lastChild.type.name,"paragraph");
    assert.ok(api.getText().includes("After the line"));
    api.exec("pageBreak");
    const before=api.getState().json,html=api.exportHTML().html;
    assert.ok(html.includes("<hr>"));assert.ok(html.includes("data-page-break"));
    api.loadHTML(html);assert.deepEqual(api.getState().json,before);
  }finally{api.destroy();}
});

test("table options preserve header, borders, width and floating layout through HTML and undo",()=>{
  const api=editor();
  try{
    api.exec("table",{rows:4,cols:2,header:true,borderWidth:3,width:50,floating:true});
    const table=api.view.state.doc.firstChild;
    assert.equal(table.childCount,4);assert.equal(table.firstChild.childCount,2);
    assert.equal(table.firstChild.firstChild.type.name,"table_header");
    assert.equal(table.child(1).firstChild.type.name,"table_cell");
    assert.deepEqual({...table.attrs},{borderWidth:3,width:50,floating:true});
    const wrapper=api.view.dom.querySelector(".tableWrapper");
    assert.equal(wrapper.style.width,"50%");assert.equal(wrapper.style.cssFloat,"left");
    assert.equal(wrapper.querySelector("table").style.getPropertyValue("--table-border-width"),"3px");
    const before=api.getState().json,html=api.exportHTML().html;
    assert.deepEqual(parseHTML(html).toJSON(),before);
    api.exec("undo");assert.equal(api.view.state.doc.firstChild.type.name,"paragraph");
    api.exec("redo");assert.deepEqual(api.getState().json,before);
    api.loadHTML("<p></p>");api.exec("table",{rows:1,cols:1,header:false,borderWidth:0,width:75});
    assert.equal(api.view.state.doc.firstChild.firstChild.firstChild.type.name,"table_cell");
    assert.equal(api.view.dom.querySelector("table").style.getPropertyValue("--table-border-width"),"0px");
  }finally{api.destroy();}
});

test("checklists support checking, undo, new unchecked items and HTML round trips",()=>{
  const api=editor();
  try{
    api.exec("insertText",{text:"Task one"});api.select(1);api.exec("checklist");
    assert.equal(api.view.state.doc.firstChild.type.name,"checklist");
    const checkbox=api.view.dom.querySelector('input[type="checkbox"]');
    assert.ok(checkbox);checkbox.checked=true;checkbox.dispatchEvent(new window.Event("change",{bubbles:true}));
    assert.equal(api.view.state.doc.firstChild.firstChild.attrs.checked,true);
    const saved=api.exportHTML().html;
    assert.deepEqual(parseHTML(saved).toJSON(),api.getState().json);
    api.exec("undo");assert.equal(api.view.state.doc.firstChild.firstChild.attrs.checked,false);
    api.exec("redo");assert.equal(api.view.state.doc.firstChild.firstChild.attrs.checked,true);
    api.select(api.view.state.doc.firstChild.nodeSize-3);
    api.view.someProp("handleKeyDown",handler=>handler(api.view,new window.KeyboardEvent("keydown",{key:"Enter",keyCode:13})));
    const list=api.view.state.doc.firstChild;
    assert.equal(list.childCount,2);assert.equal(list.child(1).attrs.checked,false);
    api.exec("insertText",{text:"Task two"});
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    api.exec("checklist");assert.equal(api.view.state.selection.$from.parent.type.name,"paragraph");
  }finally{api.destroy();}
});

test("text box dimensions, border and wrapping survive HTML, preserve text and undo cleanly",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>Text inside the box.</p><p>Following paragraph.</p>');api.select(1);
    assert.ok(api.exec("textbox",{width:240,height:120,borderWidth:3,floating:true}));
    const box=api.view.state.doc.firstChild;
    assert.equal(box.type.name,"textbox");assert.equal(box.textContent,"Text inside the box.");
    assert.deepEqual({...box.attrs},{width:240,height:120,borderWidth:3,floating:true,background:null});
    const element=api.view.dom.querySelector("section[data-textbox]");
    assert.equal(element.style.width,"240px");assert.equal(element.style.minHeight,"120px");
    assert.equal(element.style.cssFloat,"left");assert.equal(element.style.borderWidth,"3px");
    const before=api.getState().json;
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),before);
    api.exec("undo");assert.equal(api.view.state.doc.firstChild.type.name,"paragraph");
    api.exec("redo");assert.deepEqual(api.getState().json,before);
    api.loadHTML('<p>Borderless</p>');api.select(1);api.exec("textbox",{borderWidth:0,floating:false});
    assert.equal(api.view.state.doc.firstChild.attrs.borderWidth,0);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    const legacy=parseHTML('<section data-textbox><p>Legacy text box</p></section>');
    assert.equal(legacy.firstChild.attrs.width,null);assert.equal(legacy.firstChild.attrs.floating,false);
  }finally{api.destroy();}
});

test("editing an existing table retains cell text, resizes, updates properties and undoes atomically",()=>{
  const api=editor();
  try{
    api.exec("table",{rows:2,cols:2,header:true});api.exec("insertText",{text:"Keep cell text"});
    const before=api.getState().json,info=api.getTable();
    assert.equal(info.rows,2);assert.equal(info.cols,2);assert.equal(info.header,true);
    api.exec("updateTable",{...info,rows:3,cols:4,header:false,width:75,borderWidth:0,floating:true});
    const table=api.view.state.doc.firstChild;
    assert.equal(table.childCount,3);assert.equal(table.firstChild.childCount,4);
    assert.equal(table.firstChild.firstChild.type.name,"table_cell");
    assert.equal(table.firstChild.firstChild.textContent,"Keep cell text");
    const after=api.getState().json;
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),after);
    api.exec("undo");assert.deepEqual(api.getState().json,before);
    api.exec("redo");assert.deepEqual(api.getState().json,after);
    api.exec("updateTable",{...api.getTable(),rows:1,cols:1});
    assert.equal(api.view.state.doc.firstChild.textContent,"Keep cell text");
    api.loadHTML('<p>Another document</p>');
    assert.throws(()=>api.exec("updateTable",info),/different document/);
  }finally{api.destroy();}
});

test("merged-table layout edits preserve spans and reject destructive dimension changes",()=>{
  const api=editor();
  try{
    api.loadHTML('<table><tr><td colspan="2"><p>Merged content</p></td></tr><tr><td><p>A</p></td><td><p>B</p></td></tr></table>');
    api.select(4);const info=api.getTable();assert.equal(info.merged,true);
    api.exec("updateTable",{...info,borderWidth:3,width:50,header:true});
    const table=api.view.state.doc.firstChild;
    assert.equal(table.firstChild.firstChild.attrs.colspan,2);
    assert.equal(table.firstChild.firstChild.textContent,"Merged content");
    assert.throws(()=>api.exec("updateTable",{...api.getTable(),cols:3}),/merged cells/);
  }finally{api.destroy();}
});

test("rounded text boxes retain chosen backgrounds and support property edits without replacing text",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>Retain my contents</p>');api.select(1);
    api.exec("textbox",{background:"#ffcc00"});
    const box=api.view.dom.querySelector("section[data-textbox]");
    assert.equal(box.style.borderRadius,"12px");assert.equal(box.style.backgroundColor,"rgb(255, 204, 0)");
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    const before=api.getState().json;
    api.exec("updateTextbox",{...api.getTextbox(),width:300,background:"rgba(12, 34, 56, 0.5)"});
    assert.equal(api.view.state.doc.firstChild.textContent,"Retain my contents");
    assert.equal(api.view.state.doc.firstChild.attrs.width,300);
    assert.equal(api.view.dom.querySelector("section").style.backgroundColor,"rgba(12, 34, 56, 0.5)");
    api.exec("undo");assert.deepEqual(api.getState().json,before);
    api.exec("redo");
    api.exec("updateTextbox",{...api.getTextbox(),background:null});
    assert.equal(api.view.state.doc.firstChild.attrs.background,null);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    api.exec("updateTextbox",{...api.getTextbox(),background:"url(https://example.org/tracker.png)"});
    assert.equal(api.view.state.doc.firstChild.attrs.background,null);
  }finally{api.destroy();}
});

test("table exit supports trailing paragraphs, table-only imports, reuse, floating layout and keyboard shortcuts",()=>{
  const api=editor();
  try{
    api.exec("table",{rows:1,cols:1});
    assert.equal(api.view.state.doc.lastChild.type.name,"paragraph");
    assert.ok(api.exec("exitTable"));assert.equal(api.getTable(),null);
    api.exec("insertText",{text:"Outside the table"});
    assert.equal(api.view.state.doc.firstChild.textContent,"");
    assert.equal(api.view.state.doc.lastChild.textContent,"Outside the table");
    api.loadHTML('<table data-floating="true" style="float:left"><tr><td><p>Keep me</p></td></tr></table>');
    api.select(4);assert.ok(api.exec("exitTable"));
    assert.equal(api.view.state.doc.childCount,2);
    assert.equal(api.view.state.doc.lastChild.attrs.clear,true);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    api.select(4);api.exec("exitTable");assert.equal(api.view.state.doc.childCount,2);
    api.loadHTML('<table><tr><td><p>Keep me</p></td></tr></table>');api.select(4);
    api.view.someProp("handleKeyDown",handler=>handler(api.view,new window.KeyboardEvent("keydown",{key:"Enter",keyCode:13,altKey:true})));
    assert.equal(api.getTable(),null);assert.equal(api.view.state.selection.$from.parent.type.name,"paragraph");
    api.select(4);
    api.view.someProp("handleKeyDown",handler=>handler(api.view,new window.KeyboardEvent("keydown",{key:"Enter",keyCode:13,altKey:true,shiftKey:true})));
    assert.equal(api.view.state.doc.firstChild.type.name,"paragraph");
    assert.equal(api.getTable(),null);
  }finally{api.destroy();}
});

test("highlight contrast picks white on dark colours and inherited text on yellow, preserving original text colour",()=>{
  const api=editor();
  try{
    api.loadHTML('<p><strong><span style="color:red">Readable text</span></strong></p>');api.select(1,14);
    for(const value of ["#1c3d73","#1a5fb4","#1b5e20","#a51d2d","#613583","#63452c","#005b5b","#3d3846"]){
      api.exec("highlight",{value});
      const element=api.view.dom.querySelector('[data-highlight]');
      assert.equal(element.style.color,"rgb(255, 255, 255)");
      assert.equal(api.view.state.doc.firstChild.firstChild.marks.find(m=>m.type.name==="color").attrs.color,"red");
      assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    }
    api.exec("highlight",{value:"#f6d32d"});
    assert.equal(api.view.dom.querySelector('[data-highlight]').style.color,"inherit");
    const saved=api.exportHTML().html;api.loadHTML(saved);api.select(1,14);
    api.exec("highlight",{value:null});
    assert.equal(api.view.dom.querySelector('[data-highlight]'),null);
    assert.equal(api.view.state.doc.firstChild.firstChild.marks.find(m=>m.type.name==="color").attrs.color,"red");
    assert.ok(api.view.state.doc.firstChild.firstChild.marks.some(m=>m.type.name==="strong"));
    api.select(14);api.exec("highlight",{value:"#1a5fb4"});api.exec("insertText",{text:" more"});
    assert.equal(api.view.dom.querySelector('[data-highlight]').style.color,"rgb(255, 255, 255)");
  }finally{api.destroy();}
});

test("live DOM parsing never turns automatic contrast into permanent colour; removal repairs old leaks",()=>{
  const api=editor();
  try{
    api.exec("insertText",{text:"Sample"});api.select(1,7);api.exec("highlight",{value:"#1a5fb4"});
    const parsed=LiveDOMParser.fromSchema(schema).parse(api.view.dom);
    assert.ok(!parsed.firstChild.firstChild.marks.some(m=>m.type.name==="color"));
    const affected='<p><span style="color:white"><span data-highlight="true" data-auto-contrast="true" data-highlight-colour="#1a5fb4" style="background-color:#1a5fb4;color:white">Legacy</span></span></p>';
    api.loadHTML(affected);api.select(1,7);api.exec("highlight",{value:null});
    assert.deepEqual(api.view.state.doc.firstChild.firstChild.marks.map(m=>m.type.name),[]);
    api.loadHTML(affected);api.select(7);api.exec("highlight",{value:null});api.exec("insertText",{text:"x"});
    assert.deepEqual(api.view.state.doc.firstChild.lastChild.marks.map(m=>m.type.name),[]);
    api.loadHTML('<p>Chosen colour</p>');api.select(1,14);
    api.exec("color",{value:"#ffffff"});api.exec("highlight",{value:"#1a5fb4"});
    const saved=api.exportHTML().html;api.loadHTML(saved);api.select(1,14);
    api.exec("highlight",{value:null});
    assert.equal(api.view.state.doc.firstChild.firstChild.marks.find(m=>m.type.name==="color").attrs.color,"rgb(255, 255, 255)");
    assert.equal(api.view.state.doc.firstChild.firstChild.marks.find(m=>m.type.name==="color").attrs.explicit,true);
  }finally{api.destroy();}
});

test("line spacing applies to selected paragraphs, survives styles/HTML, and supports undo",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>First paragraph</p><p>Second paragraph</p>');api.select(1);
    const original=api.getState().json;
    api.exec("lineSpacing",{value:2});
    assert.equal(api.view.state.doc.firstChild.attrs.lineSpacing,2);
    assert.equal(api.view.state.doc.child(1).attrs.lineSpacing,1);
    api.exec("undo");assert.deepEqual(api.getState().json,original);
    api.exec("redo");assert.equal(api.view.state.doc.firstChild.attrs.lineSpacing,2);
    api.exec("style",{name:"H2"});assert.equal(api.view.state.doc.firstChild.attrs.lineSpacing,2);
    api.select(1,api.view.state.doc.content.size-1);api.exec("lineSpacing",{value:1.15});
    assert.ok(Array.from({length:2},(_,i)=>api.view.state.doc.child(i).attrs.lineSpacing).every(value=>value===1.15));
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    const lastStart=api.view.state.doc.firstChild.nodeSize+1;
    api.select(1,lastStart);api.exec("lineSpacing",{value:3});
    assert.equal(api.view.state.doc.child(1).attrs.lineSpacing,1.15);
    api.exec("lineSpacing",{value:.95});assert.equal(api.view.state.doc.firstChild.attrs.lineSpacing,.95);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    api.loadHTML('<p style="line-height:200%">Imported</p>');assert.equal(api.view.state.doc.firstChild.attrs.lineSpacing,2);
  }finally{api.destroy();}
});

test("literal find crosses formatting but not paragraphs; navigation and case matching leave the document clean",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>Ca<strong>fé</strong> café [a.b]</p><p>café</p><table><tr><td><p>café</p></td></tr></table>');
    const original=api.getState();
    assert.deepEqual(api.find('café'),{count:4,current:1});
    assert.deepEqual(api.findNext(-1),{count:4,current:4});
    assert.deepEqual(api.findNext(1),{count:4,current:1});
    assert.equal(api.find('café',true).count,3);
    assert.equal(api.find('[a.b]').count,1);
    assert.equal(api.find('[a.b]café').count,0);
    assert.equal(api.find('').count,0);
    api.find('café');assert.ok(api.view.dom.querySelector('.search-match-current'));
    assert.ok(!api.exportHTML().html.includes('search-match'));
    api.clearSearch();assert.equal(api.view.dom.querySelector('.search-match'),null);
    assert.deepEqual(api.getState(),original);
  }finally{api.destroy();}
});

test("replace/current and replace/all preserve structure and formatting, use literal text, and undo independently",()=>{
  const api=editor();
  try{
    api.loadHTML('<p><strong>cat</strong> cat cat</p><p>cat</p>');api.find('cat');
    assert.equal(api.replaceMatch('dog').replaced,1);
    assert.equal(api.view.state.doc.firstChild.firstChild.text,'dog');
    assert.ok(api.view.state.doc.firstChild.firstChild.marks.some(m=>m.type.name==='strong'));
    const afterOne=api.getState().json;
    assert.equal(api.replaceMatch('$&',true).replaced,3);
    assert.equal(api.getText(),'dog $& $&\n$&');
    api.exec('undo');assert.deepEqual(api.getState().json,afterOne);
    api.exec('redo');assert.equal(api.getText(),'dog $& $&\n$&');
    api.find('$&');assert.equal(api.replaceMatch('',true).replaced,3);
    assert.equal(api.view.state.doc.childCount,2);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),api.getState().json);
    api.loadHTML('<p>a a</p>');api.find('a');assert.equal(api.replaceMatch('aa',true).replaced,2);
    assert.equal(api.getText(),'aa aa');assert.equal(api.find('a').count,4);
  }finally{api.destroy();}
});

test("large find results remain fully counted without creating thousands of highlight nodes",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>'+('word '.repeat(3000))+'</p>');assert.equal(api.find('word').count,3000);
    assert.ok(api.view.dom.querySelectorAll('.search-match').length<=500);
    assert.equal(api.findNext(-1).current,3000);
    assert.ok(api.view.dom.querySelector('.search-match-current'));
  }finally{api.destroy();}
});

test("custom styles support all five categories, including distinct Title/H1 defaults and persistence",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>Styled text</p>');api.select(1);
    for(const [kind,level,size] of [['Body',0,12],['Title',1,30],['H1',1,24],['H2',2,18],['H3',3,14]]){
      const name='My '+kind;
      api.exec('defineStyle',{name,create:true,preset:{kind,level,size,font:'Sans',bold:level>0,italic:false}});
      const doc=api.getState().json;
      assert.equal(doc.attrs.styles[name].kind,kind);assert.equal(doc.attrs.styles[name].level,level);
      assert.equal(doc.content[0].type,level?'heading':'paragraph');
      assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),doc);
    }
    const before=api.getState().json;
    assert.throws(()=>api.exec('defineStyle',{name:'My Title',create:true}),/already exists/);
    assert.deepEqual(api.getState().json,before);
  }finally{api.destroy();}
});

test("renaming a custom style updates all references and semantic levels, preserves text/spacing, and undoes atomically",()=>{
  const api=editor();
  try{
    api.loadHTML('<p data-style="Accent" style="line-height:2">One</p><section data-textbox><p data-style="Accent"><strong>Two</strong></p></section><table><tr><td><p data-style="Accent" style="line-height:2.5">Three</p></td></tr></table>');
    api.select(1);api.exec('defineStyle',{name:'Accent',preset:{level:0,font:'Serif',size:13,bold:false,italic:false}});
    const before=api.getState().json,text=api.getText();
    api.exec('defineStyle',{oldName:'Accent',name:'Section blue',preset:{kind:'H2',level:2,font:'Sans',size:20,bold:true,italic:false}});
    const after=api.getState().json;assert.ok(!Object.hasOwn(after.attrs.styles,'Accent'));
    const blocks=[];api.view.state.doc.descendants(node=>{if(node.isTextblock)blocks.push(node);});
    assert.equal(blocks.length,3);assert.ok(blocks.every(node=>node.attrs.styleName==='Section blue'&&node.type.name==='heading'&&node.attrs.level===2));
    assert.deepEqual(blocks.map(node=>node.attrs.lineSpacing),[2,1,2.5]);assert.equal(api.getText(),text);
    assert.ok(blocks[1].firstChild.marks.some(mark=>mark.type.name==='strong'));
    api.exec('undo');assert.deepEqual(api.getState().json,before);
    api.exec('redo');assert.deepEqual(api.getState().json,after);
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),after);
    assert.throws(()=>api.exec('defineStyle',{oldName:'Section blue',name:'H1'}),/already exists/);
    assert.throws(()=>api.exec('defineStyle',{oldName:'Normal',name:'New body'}),/different name/);
    assert.deepEqual(api.getState().json,after);
  }finally{api.destroy();}
});

test("document outline includes titles/custom headings in document order and navigation is non-destructive",()=>{
  const api=editor();
  try{
    api.loadHTML('<h1 data-style="Title">Document title</h1><p>Body text</p><h1>Chapter</h1><section data-textbox><h2>Box heading</h2></section><table><tr><td><h3>Cell heading</h3></td></tr></table><h3></h3>');
    api.select(1);api.exec('defineStyle',{name:'My title',create:true,preset:{kind:'Title',level:1,font:'Sans',size:28,bold:true,italic:false}});
    const before=api.getState(),outline=api.getOutline();
    assert.deepEqual(outline.headings.map(h=>[h.text,h.level,h.kind]),[
      ['Document title',1,'Title'],['Chapter',1,'H1'],['Box heading',2,'H2'],['Cell heading',3,'H3'],['Untitled heading',3,'H3']]);
    const heading=outline.headings[3];
    assert.ok(api.gotoHeading(heading.position,outline.documentId,outline.revision));
    assert.equal(api.view.state.selection.from,heading.position+1);
    assert.deepEqual(api.getState(),before);
    assert.ok(!api.exportHTML().html.includes('outline-dropdown'));
    api.exec('insertText',{text:'Changed '});
    assert.equal(api.gotoHeading(heading.position,outline.documentId,outline.revision),false);
    assert.ok(api.getOutline().headings[3].text.startsWith('Changed '));
    api.loadHTML('<p>Another document</p>');
    assert.deepEqual(api.getOutline().headings,[]);
    assert.equal(api.gotoHeading(heading.position,outline.documentId,outline.revision),false);
  }finally{api.destroy();}
});

test("document columns round-trip, undo, retain content and reject invalid counts",()=>{
  const api=editor();
  try{
    api.loadHTML('<h1>Heading</h1><p>First paragraph.</p><p>Second paragraph.</p>');
    const original=api.getState().json;
    for(const count of [2,3,1]){
      assert.ok(api.exec('columns',{value:count}));
      assert.equal(api.getState().json.content[0].attrs.columns,count);
      assert.deepEqual(api.getState().json.content[0].content,original.content);
      assert.equal(api.view.dom.firstElementChild.style.columnCount,String(count));
      const html=api.exportHTML().html;
      assert.equal(parseHTML(html).firstChild.attrs.columns,count);
      assert.ok(html.includes('column-count: '+count));
    }
    api.exec('undo');assert.equal(api.getState().json.content[0].attrs.columns,3);
    api.exec('redo');assert.equal(api.getState().json.content[0].attrs.columns,1);
    assert.throws(()=>api.exec('columns',{value:4}));
    assert.equal(parseHTML('<body data-columns="99"><p>safe</p></body>').attrs.columns,1);
    api.loadHTML('<p>ordinary document</p>');assert.equal(api.getState().json.content[0].type,'paragraph');
  }finally{api.destroy();}
});

test("page break at the document end leaves an editable paragraph and prints without a rule",()=>{
  const api=editor();
  try{
    api.exec('insertText',{text:'First page'});
    api.exec('pageBreak');
    assert.equal(api.view.state.selection.$from.parent.type.name,'paragraph');
    api.exec('insertText',{text:'Second page'});
    const doc=api.getState().json;
    assert.equal(doc.content[1].type,'page_break');
    assert.equal(doc.content[2].content[0].text,'Second page');
    const html=api.exportHTML().html;
    assert.ok(html.includes('page-break-after:always'));
    assert.deepEqual(parseHTML(html).toJSON(),doc);
  }finally{api.destroy();}
});

test("page break ends column section, keeps following content full width, and supports independent layouts",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>First</p><p>Following</p>');api.exec('columns',{value:2});
    api.select(7);api.exec('pageBreak');
    let doc=api.getState().json;
    assert.equal(doc.content[0].type,'column_section');assert.equal(doc.content[0].attrs.columns,2);
    assert.equal(doc.content[1].type,'page_break');assert.equal(doc.content[2].type,'paragraph');
    assert.equal(api.view.state.selection.$from.depth,1);
    api.exec('columns',{value:3});doc=api.getState().json;
    assert.equal(doc.content[0].attrs.columns,2);assert.equal(doc.content[2].attrs.columns,3);
    const html=api.exportHTML().html;assert.deepEqual(parseHTML(html).toJSON(),doc);
    api.exec('undo');assert.equal(api.getState().json.content[2].type,'paragraph');
    api.loadHTML('<body data-columns="3"><p>Old columns</p><hr data-page-break><p>Full width</p></body>');
    doc=api.getState().json;assert.equal(doc.content[0].attrs.columns,3);assert.equal(doc.content[2].type,'paragraph');
  }finally{api.destroy();}
});

test("delete table removes only the target, remains editable, undoes and rejects stale documents",()=>{
  const api=editor();
  try{
    api.loadHTML('<p>Before</p><table><tr><td><p>Cell</p></td></tr></table><p>After</p>');
    const original=api.getState().json;
    const pos=api.view.state.doc.firstChild.nodeSize,info=api.getTable(pos);
    api.exec('deleteTable',info);
    assert.equal(api.getText(),'Before\nAfter');
    assert.equal(api.view.dom.querySelector('table'),null);
    api.exec('undo');assert.deepEqual(api.getState().json,original);
    api.exec('redo');assert.equal(api.view.dom.querySelector('table'),null);
    api.loadHTML('<table><tr><td><p>Only content</p></td></tr></table>');
    assert.throws(()=>api.exec('deleteTable',info),/different document/);
    api.exec('deleteTable',api.getTable(0));api.exec('insertText',{text:'Still editable'});
    assert.equal(api.getText(),'Still editable');
    api.loadHTML('<table><tr><td><p>In columns</p></td></tr></table>');api.exec('columns',{value:2});
    api.exec('deleteTable',api.getTable(1));api.exec('insertText',{text:'Column text'});
    assert.equal(api.getText(),'Column text');
  }finally{api.destroy();}
});

test("image resizing preserves image data, supports HTML roundtrip, undo, reset and stale-document checks",()=>{
  const api=editor();
  try{
    api.loadHTML(`<p>Before<img src="${image}" alt="Picture">After</p>`);
    const info=api.getImage(7),original=api.getState().json;
    assert.ok(info);
    api.exec('resizeImage',{...info,width:240});
    assert.equal(api.getImage(7).width,240);
    assert.equal(api.view.dom.querySelector('img').getAttribute('width'),'240');
    const resized=api.getState().json;
    assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),resized);
    assert.equal(api.view.state.doc.nodeAt(7).attrs.src,image);
    api.exec('undo');assert.deepEqual(api.getState().json,original);
    api.exec('redo');assert.deepEqual(api.getState().json,resized);
    api.exec('resizeImage',{...info,width:null});assert.equal(api.getImage(7).width,null);
    assert.throws(()=>api.exec('resizeImage',{...info,width:-1}));
    api.loadHTML(`<p><img src="${image}"></p>`);
    assert.throws(()=>api.exec('resizeImage',{...info,width:100}),/different document/);
  }finally{api.destroy();}
});

test("deleting custom styles resets all references to their built-in category and undoes atomically",()=>{
  const api=editor();
  try{
    for(const [kind,level,base] of [['Body',0,'Normal'],['Title',1,'Title'],['H1',1,'H1'],['H2',2,'H2'],['H3',3,'H3']]){
      api.loadHTML('<p data-style="Custom" style="line-height:2;text-align:right">One</p><section data-textbox><p data-style="Custom"><strong>Two</strong></p></section><table><tr><td><p data-style="Custom">Three</p></td></tr></table>');
      api.exec('defineStyle',{name:'Custom',preset:{kind,level,font:'Serif',size:21,bold:true,italic:false}});
      const original=api.getState(),text=api.getText();
      api.exec('deleteStyle',{name:'Custom',documentId:original.documentId});
      const deleted=api.getState().json,blocks=[];
      api.view.state.doc.descendants(node=>{if(node.isTextblock)blocks.push(node);});
      assert.ok(!Object.hasOwn(deleted.attrs.styles,'Custom'));
      assert.ok(blocks.every(node=>node.attrs.styleName===base));
      assert.equal(blocks[0].attrs.lineSpacing,2);assert.equal(blocks[0].attrs.align,'right');
      assert.ok(blocks[1].firstChild.marks.some(mark=>mark.type.name==='strong'));
      assert.equal(api.getText(),text);
      assert.deepEqual(parseHTML(api.exportHTML().html).toJSON(),deleted);
      api.exec('undo');assert.deepEqual(api.getState().json,original.json);
      api.exec('redo');assert.deepEqual(api.getState().json,deleted);
      for(const name of ['Normal','Title','H1','H2','H3'])assert.throws(()=>api.exec('deleteStyle',{name}),/Built-in/);
      assert.throws(()=>api.exec('deleteStyle',{name:'Missing'}),/no longer exists/);
      assert.throws(()=>api.exec('deleteStyle',{name:'Custom',documentId:original.documentId-1}),/different document/);
    }
  }finally{api.destroy();}
});

test("style edits and deletion never mutate cached notifications or history snapshots",()=>{
  const mount=document.createElement('div');document.body.append(mount);const states=[];
  const api=createEditor(mount,state=>states.push(state));
  try{
    api.loadHTML('<p>Text</p>');const initial=states.at(-1).styles;
    api.exec('defineStyle',{name:'Accent',create:true});
    assert.ok(!Object.hasOwn(initial,'Accent'));
    const named=states.at(-1).styles;
    api.exec('defineStyle',{oldName:'Accent',name:'Renamed'});
    assert.ok(Object.hasOwn(named,'Accent'));assert.ok(!Object.hasOwn(named,'Renamed'));
    api.exec('undo');assert.ok(Object.hasOwn(states.at(-1).styles,'Accent'));
    assert.ok(!Object.hasOwn(states.at(-1).styles,'Renamed'));
    api.exec('deleteStyle',{name:'Accent'});assert.ok(Object.hasOwn(named,'Accent'));
    api.exec('undo');assert.ok(Object.hasOwn(states.at(-1).styles,'Accent'));
  }finally{api.destroy();}
});

test("document margins persist, undo, affect layout and reset for ordinary HTML",()=>{
  const api=editor();
  try{
    const margins={top:12.5,bottom:30,left:15,right:25};
    api.setMargins(margins);
    assert.deepEqual(api.getMargins(),margins);
    assert.equal(api.getSummary().dirty,true);
    const html=api.exportHTML().html;
    assert.ok(html.includes('@page{margin:12.5mm 25mm 30mm 15mm}'));
    assert.deepEqual(parseHTML(html).attrs.margins,margins);
    api.exec('undo');assert.deepEqual(api.getMargins(),{top:20,bottom:20,left:20,right:20});
    api.exec('redo');assert.deepEqual(api.getMargins(),margins);
    api.loadHTML(html);assert.deepEqual(api.getMargins(),margins);assert.equal(api.getSummary().dirty,false);
    api.loadHTML('<p>Imported</p>');assert.deepEqual(api.getMargins(),{top:20,bottom:20,left:20,right:20});
    api.setMargins({top:-1,bottom:Infinity,left:100,right:'12'});
    assert.deepEqual(api.getMargins(),{top:20,bottom:20,left:20,right:20});
  }finally{api.destroy();}
});

test('Twinly legacy lists and named paragraphs migrate without losing formatting',()=>{
 const api=editor();try{
  api.loadHTML('<p data-twinly-style="title"><strong>Original title</strong></p><p data-twinly-style="body">☑ Completed</p><p data-twinly-style="body">• Bullet</p>');
  assert.equal(api.view.state.doc.firstChild.attrs.styleName,'Title');
  assert.equal(api.view.state.doc.child(1).type.name,'checklist');
  assert.equal(api.view.state.doc.child(1).firstChild.attrs.checked,true);
  assert.equal(api.view.state.doc.child(2).type.name,'bullet_list');
 }finally{api.destroy();}
});

test('Twinly font chooser retains numeric weights, oblique style and stretch in HTML',()=>{
 const api=editor();try{
  api.exec('insertText',{text:'Variants'});api.select(1,9);
  api.exec('font',{value:'Noto Sans'});api.exec('size',{value:18});
  api.exec('character',{font_weight:350,font_style:'oblique',stretch:'condensed'});
  const json=api.getState().json,html=api.exportHTML().html;
  assert.match(html,/font-weight:\s*350/);assert.match(html,/font-style:\s*oblique/);assert.match(html,/font-stretch:\s*(?:condensed|75%)/);
  api.loadHTML(html);assert.deepEqual(api.getState().json,json);
 }finally{api.destroy();}
});

test('Twinly link commands support relative notes and reject active or absolute file URLs',()=>{
 const api=editor();try{
  api.exec('insertText',{text:'Link'});api.select(1,5);api.exec('link',{value:'../Other%20Note.html'});
  assert.ok(api.exportHTML().html.includes('../Other%20Note.html'));
  assert.throws(()=>api.exec('link',{value:'javascript:alert(1)'}));
  assert.throws(()=>api.exec('link',{value:'file:///etc/passwd'}));
  api.exec('removeLink');assert.ok(!api.getState().json.content[0].content[0].marks?.some(m=>m.type==='link'));
 }finally{api.destroy();}
});

test('Twinly read-only mode rejects formatting and insertion while allowing selection',()=>{
 const api=editor();try{
  api.exec('insertText',{text:'Protected'});const before=api.getState().json;
  api.setEditable(false);api.select(1,5);
  assert.equal(api.exec('bold'),false);assert.equal(api.exec('insertText',{text:'bad'}),false);
  assert.deepEqual(api.getState().json,before);
  api.setEditable(true);assert.equal(api.exec('bold'),true);
 }finally{api.destroy();}
});

test('Twinly named custom definitions travel with the document and retain their stable IDs',()=>{
 const api=editor();try{
  const definition={id:'a'.repeat(32),name:'My body style',base:'body',format:{family:'Noto Sans',size:15,font_weight:400,font_style:'normal'}};
  api.exec('insertText',{text:'Custom'});api.select(1,7);
  api.exec('defineStyle',{name:'Twinly_'+definition.id,twinlyDefinition:definition,preset:{kind:'Body',level:0,font:'Noto Sans',size:15,bold:false,italic:false}});
  const html=api.exportHTML().html;api.loadHTML(html);
  assert.deepEqual(api.getState().json.attrs.customStyles[definition.id],definition);
 }finally{api.destroy();}
});

test('Twinly paragraph and table budgets reject oversized edits without changing the document',()=>{
 const mount=document.createElement('div');document.body.append(mount);const errors=[];
 const api=createEditor(mount,message=>{if(message.type==='error')errors.push(message.message);});
 try{
  const before=api.getState().json;api.exec('insertText',{text:'x'.repeat(16385)});
  assert.deepEqual(api.getState().json,before);assert.equal(errors.length,1);
  api.exec('table',{rows:100,cols:20});assert.deepEqual(api.getState().json,before);
 }finally{api.destroy();}
});

test('Twinly legacy empty-paragraph placeholders do not become unwanted soft breaks',()=>{
 const api=editor();try{
  api.loadHTML('<p data-twinly-style="body" style="text-align:left"><br></p>');
  assert.equal(api.getText(),'');api.exec('insertText',{text:'No trailing line break'});
  assert.equal(api.getText(),'No trailing line break');
 }finally{api.destroy();}
});

test('Twinly whole-word matching respects Unicode and case options',()=>{
 const api=editor();try{
  api.loadHTML('<p>cat scatter Cat cat</p>');
  assert.equal(api.find('cat',false,true).count,3);
  assert.equal(api.find('cat',true,true).count,2);
  assert.equal(api.find('cat',false,false).count,4);
 }finally{api.destroy();}
});

test('Twinly paragraph continuation keeps selected line spacing and exits headings as Body',()=>{
 const api=editor();try{
  api.exec('insertText',{text:'Heading'});api.select(8);api.exec('style',{name:'H1'});api.exec('lineSpacing',{value:2});
  api.view.someProp('handleKeyDown',handler=>handler(api.view,new window.KeyboardEvent('keydown',{key:'Enter',keyCode:13})));
  assert.equal(api.view.state.selection.$from.parent.type.name,'paragraph');
  assert.equal(api.view.state.selection.$from.parent.attrs.styleName,'Normal');
  assert.equal(api.view.state.selection.$from.parent.attrs.lineSpacing,2);
 }finally{api.destroy();}
});

test('Twinly native offsets handle Unicode, empty paragraphs and rules without changing stored marks',()=>{
  const api=editor();
  try{
    api.loadHTML('<p>A😀B</p><hr><p></p><p>Last</p>');
    const text=api.getText();
    for(let offset=0;offset<Array.from(text).length;offset++){
      if(Array.from(text)[offset]==='\n'||Array.from(text)[offset]==='\ufffc')continue;
      api.selectTextOffsets(offset,offset+1);
      assert.equal(api.view.state.doc.textBetween(api.view.state.selection.from,api.view.state.selection.to),Array.from(text)[offset]);
    }
    api.loadHTML('<p></p>');api.exec('insertText',{text:'Existing '});api.selectTextOffsets(9);api.exec('fontDescription',{family:'Noto Sans',size:18,weight:600,style:'oblique',stretch:'condensed'});
    api.replaceTextOffsets(9,9,'é漢');assert.equal(api.getText(),'Existing é漢');
    const last=api.getState().json.content[0].content.at(-1);
    assert.ok(last.marks.some(mark=>mark.type==='numeric_weight'&&mark.attrs.weight===600));
  }finally{api.destroy();}
});

test('Twinly changes list kind and keeps a font chooser change in one undo step',()=>{
  const api=editor();
  try{
    api.loadHTML('<p>First</p><p>Second</p>');api.selectTextOffsets(0,12);api.exec('numbered');api.exec('checklist');
    assert.equal(api.getState().json.content[0].type,'checklist');
    api.loadHTML('<p>Font</p>');api.selectTextOffsets(0,4);const before=api.getState().json;
    api.exec('fontDescription',{family:'Serif',size:19,weight:600,style:'oblique',stretch:'condensed'});api.exec('undo');assert.deepEqual(api.getState().json,before);
  }finally{api.destroy();}
});

test('Twinly read-only mode also blocks checkbox and plugin-originated document edits',()=>{
  const api=editor();
  try{
    api.loadHTML('<ul data-checklist="true"><li data-checked="false"><div class="checklist-content"><p>Private checklist</p></div></li></ul>');
    const before=api.getState().json;api.setEditable(false);
    const checkbox=api.view.dom.querySelector('input');checkbox.checked=true;checkbox.dispatchEvent(new window.Event('change'));
    assert.equal(checkbox.checked,false);assert.deepEqual(api.getState().json,before);
    api.view.dispatch(api.view.state.tr.insertText('Rejected',4));assert.deepEqual(api.getState().json,before);
    api.setEditable(true);assert.equal(checkbox.disabled,false);
  }finally{api.destroy();}
});

test('Twinly Enter leaves an empty checklist item as an ordinary paragraph',()=>{
  const api=editor();
  try{
    api.loadHTML('<ul data-checklist="true"><li data-checked="false"><div class="checklist-content"><p>Item</p></div></li></ul>');
    api.selectTextOffsets(4);api.exec('paragraphBreak');api.exec('paragraphBreak');
    assert.equal(api.getState().json.content.at(-1).type,'paragraph');
  }finally{api.destroy();}
});
