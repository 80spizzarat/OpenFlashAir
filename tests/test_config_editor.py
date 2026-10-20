import tempfile
import unittest
from pathlib import Path
import os
from unittest.mock import patch

from openflashair.config_editor import ConfigDocument, ConfigEditor


FIXTURE = b'# FlashAir sample\r\nAPPMODE=4\r\nAPPSSID=flashair\r\nUNKNOWN_KEY=value\r\n; preserved comment\r\nVERSION=F00\r\n'


class ConfigEditorTests(unittest.TestCase):
    def test_parse_preserves_comments_unknowns_and_structure(self):
        document=ConfigDocument.parse_bytes(FIXTURE)
        self.assertEqual(document.encoding,'ascii'); self.assertEqual(document.newline,'\r\n')
        self.assertEqual(document.values()['APPMODE'],'4')
        self.assertEqual(document.unknown(),[('UNKNOWN_KEY','value')])
        self.assertEqual(document.raw_text().encode('ascii'),FIXTURE)

    def test_utf8_and_non_utf8_validation(self):
        self.assertEqual(ConfigDocument.parse_bytes(b'APPSSID=caf\xc3\xa9\n').encoding,'utf-8')
        with self.assertRaises(ValueError): ConfigDocument.parse_bytes(b'APPSSID=\xff\n')

    def test_mode_specific_connection_safety_messages(self):
        self.assertIn('AP mode',ConfigDocument.parse_bytes(b'APPMODE=4\n').connection_mode())
        self.assertIn('APPNAME',ConfigDocument.parse_bytes(b'APPMODE=5\n').connection_mode())
        self.assertIn('BRGSSID',ConfigDocument.parse_bytes(b'APPMODE=6\n').connection_mode())

    def test_editor_is_read_only_and_manual_mount_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(FIXTURE)
            editor=ConfigEditor(root)
            self.assertEqual(editor.inspect().values()['VERSION'],'F00')
            with self.assertRaises(PermissionError): editor.save('APPMODE=5\n')
            self.assertEqual(config.read_bytes(),FIXTURE)

    def test_resolver_accepts_root_folder_and_direct_config_even_when_attributed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); folder=root/'SD_WLAN'; config=folder/'CONFIG'; folder.mkdir(); config.write_bytes(FIXTURE)
            if os.name == 'nt':
                import ctypes
                # Hidden/system attributes must not alter lexical path resolution or read-only access.
                self.assertNotEqual(ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x6),0)
                self.assertNotEqual(ctypes.windll.kernel32.SetFileAttributesW(str(config), 0x6),0)
            try:
                expected=config
                self.assertEqual(ConfigEditor.resolve_path(root),expected)
                self.assertEqual(ConfigEditor.resolve_path(folder),expected)
                self.assertEqual(ConfigEditor.resolve_path(config),expected)
                self.assertEqual(ConfigEditor(folder).inspect().values()['APPMODE'],'4')
            finally:
                if os.name == 'nt':
                    ctypes.windll.kernel32.SetFileAttributesW(str(config), 0x80)
                    ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x10)

    def test_safe_connection_save_preserves_unrelated_source_and_verifies_backup(self):
        source=(b'# keep comment\r\nAPPNAME=camera\r\nAPPMODE=4\r\nAPPSSID=old\r\n'
                b'APPNETWORKKEY=oldpassword\r\nUNKNOWN=value\r\nVERSION=F00\r\n')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(source); backups=root/'backups'
            original_attributes=None; saved_attributes=None
            if os.name == 'nt':
                import ctypes
                self.assertNotEqual(ctypes.windll.kernel32.SetFileAttributesW(str(config),0x6),0); original_attributes=0x6
            try:
                result=ConfigEditor(root).save_connection_settings('5','newssid','newpassword',backups)
                if original_attributes is not None: saved_attributes=ConfigEditor._attributes(config)
            finally:
                if os.name == 'nt': ctypes.windll.kernel32.SetFileAttributesW(str(config),0x80)
            written=config.read_bytes()
            self.assertTrue(result['changed']); self.assertEqual(result['backup'].read_bytes(),source)
            self.assertIn(b'# keep comment\r\nAPPNAME=camera\r\n',written); self.assertIn(b'UNKNOWN=value\r\nVERSION=F00\r\n',written)
            self.assertIn(b'APPMODE=5\r\nAPPSSID=newssid\r\nAPPNETWORKKEY=newpassword\r\n',written)
            if original_attributes is not None: self.assertEqual(saved_attributes,original_attributes)

    def test_client_to_hotspot_save_changes_only_mode_and_hotspot_credentials(self):
        source=(b'# keep\r\nAPPNAME=card\r\nAPPMODE=5\r\nAPPSSID=upstream-network\r\n'
                b'APPNETWORKKEY=synthetic-client-key\r\nUNKNOWN=value\r\nVERSION=F00\r\n')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(source)
            result=ConfigEditor(root).save_connection_settings('4','flashair','synthetic-hotspot-key',root/'backups')
            written=config.read_bytes()
            self.assertEqual(result['backup'].read_bytes(),source)
            self.assertIn(b'APPMODE=4\r\nAPPSSID=flashair\r\nAPPNETWORKKEY=synthetic-hotspot-key\r\n',written)
            self.assertIn(b'# keep\r\nAPPNAME=card\r\n',written)
            self.assertIn(b'UNKNOWN=value\r\nVERSION=F00\r\n',written)
            readback=ConfigEditor(root).inspect().values()
            self.assertEqual((readback['APPMODE'],readback['APPSSID']),('4','flashair'))

    def test_hotspot_transaction_removes_appname_without_touching_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir()
            source=b'; preserved\r\nAPPNAME=openflashair\r\nAPPMODE=5\r\nAPPSSID=router\r\nAPPNETWORKKEY=client-key\r\nUNKNOWN=keep\r\n'
            config.write_bytes(source)
            result=ConfigEditor(root).save_connection_settings('4','flashair','hotspot1',root/'backups',appname='')
            text=config.read_text(encoding='ascii')
            self.assertNotIn('APPNAME=',text); self.assertIn('UNKNOWN=keep',text); self.assertIn('; preserved',text)
            self.assertEqual(result['backup'].read_bytes(),source)

    def test_client_transaction_can_restore_saved_appname_after_hotspot_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir()
            config.write_bytes(b'APPMODE=4\nAPPSSID=flashair\nAPPNETWORKKEY=hotspot1\nUNKNOWN=keep\n')
            ConfigEditor(root).save_connection_settings('5','router','client-key',root/'backups',appname='openflashair')
            values=ConfigEditor(root).inspect().values()
            self.assertEqual(values['APPMODE'],'5'); self.assertEqual(values['APPSSID'],'router')
            self.assertEqual(values['APPNAME'],'openflashair'); self.assertEqual(values['UNKNOWN'],'keep')

    def test_client_restore_requires_owner_name_when_no_profile_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir()
            config.write_text('APPMODE=4\nAPPSSID=flashair\nAPPNETWORKKEY=hotspot1\n',encoding='ascii')
            with self.assertRaisesRegex(ValueError,'FlashAir name'):
                ConfigEditor(root).save_connection_settings('5','router','client-key',root/'backups')
            ConfigEditor(root).save_connection_settings('5','router','client-key',root/'backups',appname='owner-card')
            self.assertEqual(ConfigEditor(root).inspect().values()['APPNAME'],'owner-card')

    def test_save_rejects_missing_client_identifier_external_change_and_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(b'APPMODE=4\nAPPSSID=old\nAPPNETWORKKEY=oldpassword\n')
            editor=ConfigEditor(root)
            with self.assertRaises(ValueError): editor.save_connection_settings('5','ssid','newpassword',root/'backups')
            with patch('openflashair.config_editor.os.replace',side_effect=OSError('simulated replace failure')):
                with self.assertRaises(OSError): editor.save_connection_settings('4','ssid','newpassword',root/'backups')
            self.assertIn(b'APPSSID=old',config.read_bytes())
            self.assertTrue(list((root/'backups').glob('*.bak')))

    def test_save_detects_external_change_before_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(b'APPNAME=x\nAPPMODE=4\nAPPSSID=old\nAPPNETWORKKEY=oldpassword\n')
            class RacingEditor(ConfigEditor):
                calls=0
                def read_bytes(self):
                    self.calls+=1
                    if self.calls == 2: self.path.write_bytes(self.path.read_bytes()+b'# external\n')
                    return super().read_bytes()
            with self.assertRaises(RuntimeError): RacingEditor(root).save_connection_settings('4','new','newpassword',root/'backups')
            self.assertIn(b'# external',config.read_bytes())

    def test_unchanged_settings_skip_backup_and_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); source=b'APPMODE=4\nAPPSSID=card\nAPPNETWORKKEY=secret123\n'; config.write_bytes(source)
            backup=root/'backups'; result=ConfigEditor(root).save_connection_settings('4','card','secret123',backup)
            self.assertFalse(result['changed']); self.assertFalse(backup.exists()); self.assertEqual(config.read_bytes(),source)

    def test_backup_failure_and_disk_full_leave_source_untouched(self):
        source=b'APPMODE=4\nAPPSSID=card\nAPPNETWORKKEY=secret123\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); config.write_bytes(source)
            blocked_backup=root/'backup-file'; blocked_backup.write_text('not a directory')
            with self.assertRaises(FileExistsError): ConfigEditor(root).save_connection_settings('4','new','newpassword',blocked_backup)
            self.assertEqual(config.read_bytes(),source)
            real_open=Path.open
            def disk_full(path,*args,**kwargs):
                if path.name.endswith('.tmp'): raise OSError('simulated disk full')
                return real_open(path,*args,**kwargs)
            with patch('openflashair.config_editor.Path.open',new=disk_full):
                with self.assertRaises(OSError): ConfigEditor(root).save_connection_settings('4','new','newpassword',root/'backups')
            self.assertEqual(config.read_bytes(),source)
            self.assertTrue(list((root/'backups').glob('*.bak')))

    def test_interrupted_replace_retains_backup_and_staged_recovery_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); source=b'APPMODE=4\nAPPSSID=card\nAPPNETWORKKEY=secret123\n'; config.write_bytes(source)
            with patch('openflashair.config_editor.os.replace',side_effect=OSError('simulated interruption')):
                with self.assertRaises(OSError): ConfigEditor(root).save_connection_settings('4','new','newpassword',root/'backups')
            self.assertEqual(config.read_bytes(),source)
            self.assertTrue(list((root/'backups').glob('*.bak')))
            self.assertTrue(list(config.parent.glob('.CONFIG.openflashair.*.tmp')))

    def test_dialog_dirty_and_cancel_reopen_fixture_behavior(self):
        original={'APPMODE':'4','APPSSID':'card','APPNETWORKKEY':'secret123'}
        self.assertFalse(ConfigEditor.has_connection_changes(original,'4','card','secret123'))
        self.assertTrue(ConfigEditor.has_connection_changes(original,'4','edited','secret123'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'SD_WLAN'/'CONFIG'; config.parent.mkdir(); source=b'APPMODE=4\nAPPSSID=card\nAPPNETWORKKEY=secret123\n'; config.write_bytes(source)
            # Cancel is represented by never invoking the save transaction; reopening reads the original fixture.
            abandoned_ssid='edited'; self.assertNotEqual(abandoned_ssid,ConfigEditor(root).inspect().values()['APPSSID'])
            self.assertEqual(ConfigEditor(root).inspect().source_bytes,source)


if __name__ == '__main__': unittest.main()
