"""Offline tests for first-run content, installation staging and release preparation."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from application import default_root,locations
from model import from_html
from settings import read_settings

class Packaging(unittest.TestCase):
    def test_first_run_installs_english_guide_and_embedded_photo_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'config'/'settings.json';documents=root/'data'/'Documents'
            with patch('application.locations',return_value=(config,documents)):
                selected,first=default_root(config)
                self.assertTrue(selected.is_relative_to(root/'data/Workspaces'))
                documents=selected
                self.assertEqual(documents/'Getting Started.html',first)
                doc,warnings=from_html(first.read_text())
                self.assertFalse(warnings)
                self.assertIn('Getting Started with Twinly',doc['text'])
                self.assertEqual(1,len(doc['images']))
                self.assertTrue(doc['images'][0]['src'].startswith('data:image/png;base64,'))
                self.assertTrue(any(span['style'].get('link',{}).get('href')=='Link%20Example.html' for span in doc['spans']))
                first.write_text('<p>My edited guide</p>')
                self.assertEqual((documents,None),default_root(config))
                self.assertEqual('<p>My edited guide</p>',first.read_text())
                self.assertTrue(read_settings(config)['managed_workspaces_version']==1)

    def test_packaged_storage_uses_xdg_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'FLATPAK_ID':'test.App','XDG_CONFIG_HOME':directory+'/config','XDG_DATA_HOME':directory+'/data'}):
                config,root=locations()
                self.assertEqual(Path(directory)/'config/twinly/preferences.json',config)
                self.assertEqual(Path(directory)/'data/twinly/Documents',root)

    def test_rename_preserves_existing_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            old_config=base/'config/weave-docs/preferences.json'
            old_data=base/'data/weave-docs/Documents'
            old_config.parent.mkdir(parents=True);old_config.write_text('{}')
            old_data.mkdir(parents=True)
            with patch.dict(os.environ,{'FLATPAK_ID':'test.App','XDG_CONFIG_HOME':str(base/'config'),'XDG_DATA_HOME':str(base/'data')}):
                self.assertEqual((old_config,old_data),locations())
                new_config=base/'config/twinly/preferences.json'
                new_config.parent.mkdir(parents=True);new_config.write_text('{}')
                self.assertEqual((new_config,base/'data/twinly/Documents'),locations())

    def test_install_staging_has_all_modules_and_no_user_documents(self):
        spec=importlib.util.spec_from_file_location('twinly_install',ROOT/'scripts/install.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory);module.install(ROOT,Path('/app'),stage)
            app=stage/'app/share/twinly'
            self.assertTrue((stage/'app/bin/twinly').is_file())
            for name in module.MODULES:self.assertTrue((app/name).is_file(),name)
            self.assertTrue((app/'data/getting-started.html').is_file())
            legal=stage/'app/share/licenses/twinly'
            for name in ('LICENSE','LICENSING.md'):
                self.assertEqual((ROOT/name).read_bytes(),(legal/name).read_bytes())
            self.assertEqual((ROOT/'data/CREDITS.md').read_bytes(),(legal/'CREDITS.md').read_bytes())
            self.assertTrue((app/'vendor/pypdf-LICENSE.txt').is_file())
            self.assertFalse((app/'Documenten').exists())
            self.assertFalse((app/'Instellingen').exists())
            self.assertNotIn('getting-started-photo.png',[p.name for p in (app/'data').iterdir()])

    def test_release_configuration_in_an_isolated_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)/'project'
            shutil.copytree(ROOT,project,ignore=shutil.ignore_patterns('__pycache__','Documenten','Instellingen','.git','dist'))
            subprocess.run([sys.executable,str(project/'scripts/configure_release.py'),'--app-id','io.github.TestOwner.Twinly','--repository','https://github.com/TestOwner/twinly','--author','Test Owner','--license','MIT'],check=True,capture_output=True)
            result=subprocess.run([sys.executable,str(project/'scripts/check_release.py'),'--publication'],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertTrue((project/'LICENSE').is_file())
            self.assertNotIn('<copyright holders>',(project/'LICENSE').read_text())
            self.assertTrue((project/'packaging/io.github.TestOwner.Twinly.json').is_file())
            self.assertNotIn('io.github.twinly.Preview',(project/'scripts/build-flatpak.sh').read_text())
            self.assertIn('flatpak run io.github.TestOwner.Twinly',(project/'README.md').read_text())

    def test_project_license_is_gpl_version_three_or_later(self):
        import xml.etree.ElementTree as ET
        from application import APP_ID,LICENSE_ID
        metadata=ET.parse(ROOT/'data'/(APP_ID+'.metainfo.xml')).getroot()
        self.assertEqual('GPL-3.0-or-later',LICENSE_ID)
        self.assertEqual(LICENSE_ID,metadata.findtext('project_license'))
        license=(ROOT/'LICENSE').read_text()
        self.assertIn('SPDX-License-Identifier: '+LICENSE_ID,license)
        self.assertIn('any later version',license)
        self.assertIn((ROOT/'licenses/GPL-3.0-or-later.txt').read_text(),license)
        self.assertIn('Paullinux',metadata.findtext('developer/name'))

    def test_offline_package_checks_pass(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/check_release.py')],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
