import base64
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import *

PNG='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGZkAAAAASUVORK5CYII='


def styles(doc):
    result=[{} for _ in doc['text']]
    for span in doc['spans']:
        for index in range(span['start'],span['end']):result[index].update(span['style'])
    return result


class Documents(unittest.TestCase):
    def test_style_cursor_matches_overlapping_span_precedence(self):
        import random
        rng=random.Random(407)
        spans=[]
        for _ in range(150):
            start=rng.randrange(200);end=rng.randrange(start+1,202)
            key=rng.choice(('foreground','size','weight'))
            value=rng.choice(('#123456','#654321')) if key=='foreground' else rng.randrange(10,25) if key=='size' else True
            spans.append({'start':start,'end':end,'style':{key:value}})
        cursor=StyleCursor(spans)
        for offset in range(205):
            expected={}
            for span in spans:
                if span['start']<=offset<span['end']:expected.update(span['style'])
            self.assertEqual(expected,cursor.at(offset))
            self.assertEqual(expected,cursor.at(offset))
        with self.assertRaises(ValueError):cursor.at(0)

    def test_custom_style_metadata_is_portable_and_validated(self):
        import json,html
        from model import validate_custom_style,validate_document
        definition={'id':'f'*32,'name':'My heading','base':'h2','format':{'family':'Serif','size':16,'font_weight':400,'font_style':'normal'}}
        doc={'text':'Heading','spans':[{'start':0,'end':7,'style':{'paragraph':'h2','custom_style':definition,**definition['format']}}],'images':[],'rules':[]}
        loaded,_=from_html(to_html(doc))
        self.assertTrue(any(s['style'].get('custom_style',{}).get('name')=='My heading' for s in loaded['spans']))
        self.assertTrue(any(s['style'].get('font_weight')==400 for s in loaded['spans']))
        for bad in ({**definition,'format':{'link':{'href':'https://example.com'}}},{**definition,'name':'bad\x00name'},{**definition,'base':'script'},{**definition,'format':{'custom_style':definition}}):
            with self.assertRaises(ValueError):validate_custom_style(bad)
        invalid=html.escape(json.dumps({**definition,'format':{'size':float('inf')}}),quote=True)
        loaded,warnings=from_html('<p><span data-twinly-custom="'+invalid+'">Safe text</span></p>')
        self.assertEqual('Safe text',loaded['text']);self.assertTrue(warnings)

    def test_html_roundtrip(self):
        doc={'text':'één & <test>\nTekst\n\nLaatste\n',
             'spans':[{'start':0,'end':3,'style':{'weight':True,'family':'Noto Sans','size':18}},
                      {'start':1,'end':6,'style':{'background':'#fff099','underline':True,'strike':True}}],
             'images':[]}
        html=to_html(doc)
        restored,warnings=from_html(html)
        self.assertEqual(doc['text'],restored['text'])
        for expected,actual in zip(styles(doc),styles(restored)):
            for key,value in expected.items():self.assertEqual(value,actual[key])
        self.assertFalse(warnings)
        self.assertIn('&lt;test&gt;',html)

    def test_embedded_photo(self):
        doc={'text':'Voor \ufffc na','spans':[],
             'images':[{'offset':5,'src':PNG,'width':200,'height':100,'alt':'Foto & café'}]}
        restored,_=from_html(to_html(doc))
        self.assertEqual(doc['text'],restored['text'])
        self.assertEqual(doc['images'],restored['images'])

    def test_import_does_not_execute_or_fetch(self):
        doc,warnings=from_html('<body><script>bad()</script><p>Veilig<img src="https://example.com/a.jpg"></p></body>')
        self.assertEqual('Veilig',doc['text'])
        self.assertFalse(doc['images'])
        self.assertTrue(warnings)

    def test_font_css_escaping(self):
        doc={'text':'abc','spans':[{'start':0,'end':3,'style':{'family':'Sans; color:red'}}],'images':[]}
        self.assertNotIn('; color:red',to_html(doc))

    def test_atomic_write_and_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=root/'A';first.mkdir()
            nested=first/'Sub';nested.mkdir()
            atomic_write(nested/'Tekst.html','first')
            atomic_write(nested/'Tekst.html','second')
            self.assertEqual('second',(nested/'Tekst.html').read_text())
            with self.assertRaises(ValueError):move_path(first,nested/'A',root)
            other=root/'B';other.mkdir()
            dest=move_path(first,other/'A',root)
            self.assertEqual('second',(dest/'Sub'/'Tekst.html').read_text())
            with self.assertRaises(FileExistsError):move_path(dest,other,root)
            with self.assertRaises(ValueError):move_path(dest,root.parent/'escape',root)

    def test_horizontal_rule_html_roundtrip(self):
        doc={'text':'Boven\n\ufffc\nOnder','spans':[],'images':[],'rules':[6]}
        content=to_html(doc)
        self.assertIn('<hr>',content)
        restored,_=from_html(content)
        for key in ('text','images','rules'):self.assertEqual(doc[key],restored[key])

    def test_invalid_names(self):
        for name in ['','..','../a','a/b','a\\b']:
            with self.assertRaises(ValueError):safe_name(name)

    def test_validation_rejects_corrupt_ranges_and_anchors(self):
        import copy
        base={'text':'A\ufffcB','spans':[],'images':[],'rules':[1]}
        self.assertEqual(base,validate_document(base))
        for change in ({'spans':[{'start':-1,'end':2,'style':{'weight':True}}]},
                       {'rules':[1,1]}, {'rules':[0]}, {'images':None},
                       {'spans':[{'start':0,'end':1,'style':{'size':float('nan')}}]},
                       {'spans':[{'start':0,'end':1,'style':{'stretch':99}}]},
                       {'spans':[{'start':0,'end':1,'style':{'link':{'href':'javascript:alert(1)'}}}]}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_document(dict(base,**change))
        self.assertEqual(base['rules'],[1])

    def test_preferences_recover_invalid_json_and_migrate(self):
        from settings import read_settings,write_settings,finite_number
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            for invalid in ('[]','null','true','42','{bad','{"blur_radius":NaN}'):
                path.write_text(invalid)
                self.assertEqual({},read_settings(path))
                write_settings(path,root='/example',appearance='dark')
                value=read_settings(path)
                self.assertEqual(1,value['schema_version'])
                self.assertEqual('/example',value['root'])
                write_settings(path,blur=True)
                self.assertEqual('/example',read_settings(path)['root'])
            for invalid in (float('nan'),float('inf'),True,{},'bad'):
                self.assertEqual(18,finite_number(invalid,18,0,40))

    def test_history_memory_budget_and_redo_branch(self):
        from session import DocumentSession
        session=DocumentSession()
        for number in range(8):session.append_history({'text':str(number)*100,'spans':[],'images':[],'rules':[]},max_bytes=1000)
        self.assertEqual(2,len(session.history))
        session.history_index=0
        session.append_history(blank(),max_bytes=1000)
        self.assertEqual('',session.history[-1]['text'])
        self.assertEqual(1,session.history_index)


if __name__=='__main__':unittest.main()
