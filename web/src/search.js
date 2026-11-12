import {Plugin,PluginKey,TextSelection} from "prosemirror-state";
import {Decoration,DecorationSet} from "prosemirror-view";
import {closeHistory} from "prosemirror-history";

// Match complete inline text runs, including text split by formatting marks.
// Block boundaries and inline objects are barriers, not invisible joins.
export function findMatches(doc,query,caseSensitive=false,wholeWords=false){
  if(!query)return [];
  const expression=new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"),caseSensitive?"gu":"giu"),matches=[];
  doc.descendants((node,pos)=>{
    if(!node.isTextblock)return;
    const text=node.textBetween(0,node.content.size,"\0","\0");expression.lastIndex=0;
    for(let match;(match=expression.exec(text));){if(wholeWords&&(/[\p{L}\p{N}_]$/u.test(text.slice(0,match.index))||/^[\p{L}\p{N}_]/u.test(text.slice(match.index+match[0].length))))continue;matches.push({from:pos+1+match.index,to:pos+1+match.index+match[0].length});}
    return false;
  });
  return matches;
}

export function createSearch(){
  const key=new PluginKey("findReplace");
  const decorationCache=new WeakMap();
  const plugin=new Plugin({key,state:{
    init:()=>({query:"",caseSensitive:false,wholeWords:false,matches:[],current:-1}),
    apply(tr,previous){
      const update=tr.getMeta(key)||{},query=update.query??previous.query,caseSensitive=update.caseSensitive??previous.caseSensitive,wholeWords=update.wholeWords??previous.wholeWords;
      const matches=update.doc===tr.doc&&update.matches?update.matches:
        tr.docChanged||query!==previous.query||caseSensitive!==previous.caseSensitive||wholeWords!==previous.wholeWords?
        findMatches(tr.doc,query,caseSensitive,wholeWords):previous.matches;
      const current=matches.length?Math.max(0,Math.min(update.current??previous.current,matches.length-1)):-1;
      if(!tr.docChanged&&query===previous.query&&caseSensitive===previous.caseSensitive&&wholeWords===previous.wholeWords&&current===previous.current&&matches===previous.matches)return previous;
      return {query,caseSensitive,wholeWords,matches,current};
    }},props:{decorations(state){
      const search=key.getState(state);
      if(!search.matches.length)return DecorationSet.empty;
      if(decorationCache.has(search))return decorationCache.get(search);
      // Keep common one-character searches responsive in long documents.
      const start=Math.max(0,search.current-250),end=Math.min(search.matches.length,start+500);
      const decorations=DecorationSet.create(state.doc,search.matches.slice(start,end).map((match,index)=>
        Decoration.inline(match.from,match.to,{class:index+start===search.current?"search-match search-match-current":"search-match"})));
      decorationCache.set(search,decorations);return decorations;
    }}});
  const summary=state=>{const search=key.getState(state);return {count:search.matches.length,current:search.current+1};};
  function select(tr,search){
    const match=search.matches[search.current];
    if(match)tr.setSelection(TextSelection.create(tr.doc,match.from,match.to)).scrollIntoView();
    return tr;
  }
  return {plugin,summary,
    find(view,query,caseSensitive=false,wholeWords=false){
      const previous=key.getState(view.state),matches=query===previous.query&&caseSensitive===previous.caseSensitive&&wholeWords===previous.wholeWords?
        previous.matches:findMatches(view.state.doc,query,caseSensitive,wholeWords);
      let current=previous.current;
      if(query!==previous.query||caseSensitive!==previous.caseSensitive||wholeWords!==previous.wholeWords){
        current=matches.findIndex(match=>match.from>=view.state.selection.from);if(current<0)current=0;
      }
      current=matches.length?Math.max(0,Math.min(current,matches.length-1)):-1;
      const search={query,caseSensitive,wholeWords,matches,current};
      view.dispatch(select(view.state.tr.setMeta(key,{query,caseSensitive,wholeWords,current,matches,doc:view.state.doc}),search));
      return summary(view.state);
    },
    next(view,direction=1){
      const search=key.getState(view.state);if(!search.matches.length)return summary(view.state);
      const current=(search.current+(direction<0?-1:1)+search.matches.length)%search.matches.length;
      view.dispatch(select(view.state.tr.setMeta(key,{current}),{...search,current}));return summary(view.state);
    },
    replace(view,replacement,all=false){
      const search=key.getState(view.state);if(!search.matches.length)return {...summary(view.state),replaced:0};
      const selected=search.matches.find(match=>match.from===view.state.selection.from&&match.to===view.state.selection.to);
      const targets=all?search.matches:[selected||search.matches[search.current]],tr=closeHistory(view.state.tr);
      for(let index=targets.length-1;index>=0;index--){const match=targets[index];tr.insertText(replacement,match.from,match.to);}
      const matches=findMatches(tr.doc,search.query,search.caseSensitive,search.wholeWords);
      let current=all?0:matches.findIndex(match=>match.from>=targets[0].from+replacement.length);
      if(current<0)current=0;
      tr.setMeta(key,{current,matches,doc:tr.doc});select(tr,{matches,current});view.dispatch(tr);
      return {...summary(view.state),replaced:targets.length};
    },
    clear(view){view.dispatch(view.state.tr.setMeta(key,{query:"",current:-1}));return summary(view.state);},
  };
}
