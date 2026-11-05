"""Regression tests for hostile documents, anchored filesystem operations and privacy."""
import base64
import copy
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model
import filesystem
import private_trash
from settings import write_settings,read_settings
from application import default_root

PNG='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGZkAAAAASUVORK5CYII='

class Security(unittest.TestCase):
    def test_external_export_allows_portal_parent_but_not_final_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';grant.mkdir()
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            selected=portal/'export.html'
            filesystem.atomic_export(selected,'first',expected=None)
            self.assertEqual('first',(grant/'export.html').read_text())
            observed=filesystem.signature((grant/'export.html').stat())
            filesystem.atomic_export(selected,'second',expected=observed)
            self.assertEqual('second',(grant/'export.html').read_text())
            with self.assertRaises(ValueError):filesystem.atomic_export(selected,'stale',expected=observed)
            with self.assertRaises(FileExistsError):filesystem.atomic_export(selected,'duplicate',overwrite=False)
            target=root/'target';target.write_text('Keep me')
            (grant/'link.html').symlink_to(target)
            with self.assertRaises(ValueError):filesystem.atomic_export(portal/'link.html','Do not write')
            self.assertEqual('Keep me',target.read_text())
            with self.assertRaises(OSError):filesystem.atomic_write(selected,'Do not relax workspace writes')

    def test_export_rejects_retargeted_portal_parent_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';outside=root/'outside'
            grant.mkdir();outside.mkdir()
            (grant/'file.html').write_text('original');(outside/'file.html').write_text('outside')
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            def retarget(fd):
                portal.unlink();portal.symlink_to(outside,target_is_directory=True)
            with patch('filesystem.os.fsync',side_effect=retarget),self.assertRaisesRegex(ValueError,'folder changed'):
                filesystem.atomic_export(portal/'file.html','replacement')
            self.assertEqual('original',(grant/'file.html').read_text())
            self.assertEqual('outside',(outside/'file.html').read_text())
            self.assertEqual(['file.html'],[p.name for p in grant.iterdir()])

    def test_legacy_trash_remains_accessible_after_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);doc=root/'note.html';doc.write_text('original')
            private_trash.trash(doc,root)
            (root/private_trash.TRASH_NAME).rename(root/'.weave-trash')
            entry=private_trash.items(root)[0]
            private_trash.restore(entry,root)
            self.assertEqual('original',doc.read_text())
            private_trash.trash(doc,root)
            private_trash.delete(private_trash.items(root)[0],root)
            self.assertFalse(private_trash.items(root))

    def test_nested_html_and_node_flood_rejected(self):
        with self.assertRaises(model.ResourceLimitError):model.from_html('<div>'*140+'text'+'</div>'*140)
        with patch.object(model,'MAX_NODES',5),self.assertRaises(model.ResourceLimitError):model.from_html('<p>text</p>'*6)

    def test_text_and_span_limits(self):
        with patch.object(model,'MAX_TEXT',8),self.assertRaises(model.ResourceLimitError):model.from_html('<p>0123456789</p>')
        with patch.object(model,'MAX_SPANS',2),self.assertRaises(model.ResourceLimitError):model.from_html('<p><b>a</b><i>b</i><u>c</u></p>')

    def test_paragraph_limit_prevents_expensive_native_layout(self):
        doc=model.blank();doc['text']='a'*model.MAX_PARAGRAPH_CHARS
        self.assertEqual(doc['text'],model.validate_document(doc)['text'])
        with self.assertRaisesRegex(model.ResourceLimitError,'paragraph exceeds'):
            model.from_html('<p>'+'a'*(model.MAX_PARAGRAPH_CHARS+1)+'</p>')
        # Splitting the same amount of text is supported; the total remains 4 MiB.
        doc['text']=('a'*300+'\n')*(model.MAX_TEXT//301)
        self.assertEqual(doc['text'],model.validate_document(doc)['text'])

    def test_image_budget_enforced_before_decoding(self):
        raw=base64.b64decode(PNG.split(',')[1]);bad=raw[:16]+struct.pack('>II',100000,100000)+raw[24:]
        uri='data:image/png;base64,'+base64.b64encode(bad).decode()
        with self.assertRaises(model.ResourceLimitError):model.decode_image(uri)
        content='<p>'+('<img src="'+PNG+'">')*3+'</p>'
        with patch.object(model,'MAX_IMAGES',2),self.assertRaises(model.ResourceLimitError):model.from_html(content)
        with patch.object(model,'MAX_TOTAL_PIXELS',1),self.assertRaises(model.ResourceLimitError):model.from_html(content)

    def test_oversized_tags_attributes_and_paragraphs_rejected(self):
        with self.assertRaises(model.ResourceLimitError):model.from_html('<p title="'+'x'*17000+'">text</p>')
        with patch.object(model,'MAX_ATTRIBUTES',2),self.assertRaises(model.ResourceLimitError):model.from_html('<p a="1" b="2" c="3">text</p>')
        with patch.object(model,'MAX_PARAGRAPHS',2),self.assertRaises(model.ResourceLimitError):model.from_html('<p>a<br>b<br>c<br>d</p>')

    def test_jpeg_dimensions_and_bounded_read_identity(self):
        image=Path(__file__).resolve().parent/'fixtures/tiny.jpg'
        self.assertEqual((3,2),model.image_dimensions(image.read_bytes()))
        self.assertTrue(model.image_data(image).startswith('data:image/jpeg;base64,'))
        content,observed=filesystem.read_text(Path(__file__),100000,with_stamp=True)
        self.assertIn('test_jpeg_dimensions',content)
        self.assertEqual(model.stamp(Path(__file__)),observed)

    def test_forged_trash_restore_path_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);doc=root/'Doc.html';doc.write_text('keep')
            private_trash.trash(doc,root);item=private_trash.items(root)[0]
            item['metadata'].write_text(json.dumps({'relative':'../outside.html','date':'now'}))
            self.assertFalse(private_trash.items(root))
            self.assertTrue(item['payload'].exists())

    def test_import_reads_allow_directory_aliases_but_remain_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';grant.mkdir()
            source=grant/'photo';source.write_bytes(b'photo bytes')
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            self.assertEqual(b'photo bytes',filesystem.read_import_bytes(portal/'photo',20))
            with self.assertRaises(OSError):filesystem.read_bytes(portal/'photo',20)
            with self.assertRaises(OSError):filesystem.atomic_write(portal/'photo',b'changed')
            self.assertEqual(b'photo bytes',source.read_bytes())
            with self.assertRaises(ValueError):filesystem.read_import_bytes(portal/'photo',5)
            (grant/'link').symlink_to(source)
            with self.assertRaises(OSError):filesystem.read_import_bytes(portal/'link',20)
            os.mkfifo(grant/'pipe')
            with self.assertRaises(ValueError):filesystem.read_import_bytes(portal/'pipe',20)

    def test_import_read_rejects_file_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'photo';source.write_bytes(b'photo bytes')
            real_stat=filesystem.os.stat
            def replaced(path,*args,**kwargs):
                if Path(path)==source and kwargs.get('follow_symlinks') is False:
                    source.unlink();source.write_bytes(b'a replacement with a different length')
                return real_stat(path,*args,**kwargs)
            with patch('filesystem.os.stat',side_effect=replaced):
                with self.assertRaises(ValueError):filesystem.read_import_bytes(source,20)

    def test_reads_are_bounded_and_refuse_symlinks_and_fifos(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'document';file.write_bytes(b'x'*20)
            with self.assertRaises(ValueError):filesystem.read_bytes(file,10)
            link=root/'link';link.symlink_to(file)
            with self.assertRaises(OSError):filesystem.read_bytes(link,100)
            fifo=root/'fifo';os.mkfifo(fifo)
            with self.assertRaises(ValueError):filesystem.read_bytes(fifo,100)

    def test_parent_symlink_is_not_followed_for_reads_or_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);outside=root/'outside';outside.mkdir();(outside/'file').write_text('keep')
            link=root/'alias';link.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(OSError):filesystem.atomic_write(link/'file','overwrite')
            with self.assertRaises(OSError):filesystem.read_bytes(link/'file',100)
            self.assertEqual('keep',(outside/'file').read_text())

    def test_atomic_save_rejects_changed_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'file';target.write_text('original')
            stamp=model.stamp(target);target.write_text('external change')
            with self.assertRaises(ValueError):filesystem.atomic_write(target,'lost update',expected=stamp)
            self.assertEqual('external change',target.read_text())
            with self.assertRaises(FileExistsError):filesystem.atomic_write(target,'duplicate',overwrite=False)

    def test_parent_directory_swap_cannot_redirect_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'folder';folder.mkdir();outside=root/'outside';outside.mkdir()
            (folder/'file').write_text('original');(outside/'file').write_text('outside')
            original_fsync=os.fsync;swapped=[]
            def swap(fd):
                original_fsync(fd)
                if not swapped:
                    swapped.append(True);folder.rename(root/'pinned');folder.symlink_to(outside,target_is_directory=True)
            with patch('filesystem.os.fsync',side_effect=swap),self.assertRaises(OSError):
                filesystem.atomic_write(folder/'file','replacement')
            self.assertEqual('outside',(outside/'file').read_text())
            self.assertEqual('original',(root/'pinned/file').read_text())
            self.assertEqual(['file'],[p.name for p in (root/'pinned').iterdir()])

    def test_move_cannot_replace_an_existing_file_or_leave_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'A';b=root/'B';a.write_text('a');b.write_text('b')
            with self.assertRaises(FileExistsError):filesystem.move_path(a,b,root)
            self.assertEqual('a',a.read_text());self.assertEqual('b',b.read_text())
            with self.assertRaises(ValueError):filesystem.move_path(a,root.parent/'escape',root)

    def test_new_preferences_and_default_documents_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'config/preferences.json';documents=root/'data/Documents'
            with patch('application.locations',return_value=(config,documents)):documents,_=default_root(config)
            self.assertEqual(0o700,stat.S_IMODE(documents.stat().st_mode))
            self.assertEqual(0o700,stat.S_IMODE(config.parent.stat().st_mode))
            self.assertEqual(0o600,stat.S_IMODE(config.stat().st_mode))
            self.assertEqual(0o600,stat.S_IMODE((documents/'Start to note.html').stat().st_mode))
            config.chmod(0o644);write_settings(config,blur=True)
            self.assertEqual(0o600,stat.S_IMODE(config.stat().st_mode))

    def test_sandbox_trash_restore_is_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);doc=root/'Doc.html';doc.write_text('original')
            private_trash.trash(doc,root)
            self.assertFalse(doc.exists());items=private_trash.items(root);self.assertEqual(1,len(items))
            doc.write_text('replacement')
            with self.assertRaises(FileExistsError):private_trash.restore(items[0],root)
            self.assertEqual('replacement',doc.read_text())
            doc.unlink();private_trash.restore(items[0],root)
            self.assertEqual('original',doc.read_text());self.assertFalse(private_trash.items(root))

    def test_sandbox_trash_deletion_never_follows_nested_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'Folder';folder.mkdir()
            outside=root/'keep.txt';outside.write_text('keep')
            (folder/'link').symlink_to(outside)
            private_trash.trash(folder,root);item=private_trash.items(root)[0]
            private_trash.delete(item,root)
            self.assertEqual('keep',outside.read_text())
            self.assertFalse(private_trash.items(root))

    def test_flatpak_has_no_blanket_document_or_trash_grants(self):
        root=Path(__file__).resolve().parents[1]
        manifest=json.loads(next((root/'packaging').glob('*.json')).read_text())
        flags=manifest['finish-args']
        self.assertFalse(any(flag.startswith('--filesystem=') or flag.startswith('--talk-name=org.gtk.vfs') for flag in flags))
        self.assertNotIn('--share=network',flags)
        for path in (root/'.github/workflows').glob('*.yml'):
            for action in re.findall(r'uses:\s*([^\s#]+)',path.read_text()):
                self.assertRegex(action,r'@[0-9a-f]{40}$')
