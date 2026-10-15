import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'ROBMEPTOOLS.extension/lib/robmep_updater.py'
spec = importlib.util.spec_from_file_location('reload_updater', MODULE)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installed = self.root / 'Desktop' / 'PY REVIT' / 'CustomName.extension'
        self.source = self.root / 'source'
        self.work = self.root / 'work'
        for path in [self.installed, self.source, self.work]:
            path.mkdir(parents=True)

    def payload(self, files, previous=None):
        for relative, value in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        manifest = {'schema': 1, 'build': 'test',
                    'files': {r: hashlib.sha256(v).hexdigest() for r, v in files.items()},
                    'previous_hashes': previous or {}}
        (self.source / 'update-manifest.json').write_text(json.dumps(manifest))
        return manifest

    def deploy(self, **kwargs):
        return updater.deploy(str(self.installed), str(self.source), str(self.work), **kwargs)

    def test_custom_folder_updates_and_keeps_settings_and_untracked_files(self):
        extra = self.installed / 'user-settings.json'
        extra.write_bytes(b'user preferences')
        self.payload({'engine.py': b'new tool'})
        result = self.deploy()
        self.assertTrue(result['changed'])
        self.assertEqual((self.installed / 'engine.py').read_bytes(), b'new tool')
        self.assertEqual(extra.read_bytes(), b'user preferences')
        self.assertEqual(result['extension_root'], str(self.installed))

    def test_same_release_is_noop_and_does_not_create_another_backup(self):
        self.payload({'engine.py': b'new'})
        self.deploy()
        count = len(list((self.work / 'backups').iterdir()))
        self.assertFalse(self.deploy()['changed'])
        self.assertEqual(len(list((self.work / 'backups').iterdir())), count)

    def test_known_first_install_migration_backs_up_old_release(self):
        old = b'old published release'
        (self.installed / 'engine.py').write_bytes(old)
        self.payload({'engine.py': b'new'}, {'engine.py': [hashlib.sha256(old).hexdigest()]})
        result = self.deploy()
        self.assertEqual((Path(result['backup']) / 'engine.py').read_bytes(), old)

    def test_unknown_first_install_file_is_preserved_before_any_mutation(self):
        (self.installed / 'engine.py').write_bytes(b'custom code')
        self.payload({'added.py': b'new', 'engine.py': b'new'})
        with self.assertRaisesRegex(updater.UpdateError, 'Local edits preserved'):
            self.deploy()
        self.assertFalse((self.installed / 'added.py').exists())
        self.assertEqual((self.installed / 'engine.py').read_bytes(), b'custom code')

    def test_local_edits_after_install_stop_update(self):
        self.payload({'engine.py': b'one'})
        self.deploy()
        (self.installed / 'engine.py').write_bytes(b'user edit')
        self.payload({'engine.py': b'two'})
        with self.assertRaisesRegex(updater.UpdateError, 'Local edits preserved'):
            self.deploy()
        self.assertEqual((self.installed / 'engine.py').read_bytes(), b'user edit')

    def test_only_obsolete_owned_files_are_removed(self):
        self.payload({'old.py': b'owned'})
        self.deploy()
        (self.installed / 'extra.py').write_bytes(b'custom')
        self.payload({'new.py': b'new'})
        self.deploy()
        self.assertFalse((self.installed / 'old.py').exists())
        self.assertEqual((self.installed / 'extra.py').read_bytes(), b'custom')

    def test_edited_obsolete_file_stops_before_other_changes(self):
        self.payload({'old.py': b'one'})
        self.deploy()
        (self.installed / 'old.py').write_bytes(b'edit')
        self.payload({'new.py': b'new'})
        with self.assertRaisesRegex(updater.UpdateError, 'obsolete file preserved'):
            self.deploy()
        self.assertFalse((self.installed / 'new.py').exists())

    def test_source_checksum_failure_does_not_touch_installation(self):
        self.payload({'engine.py': b'intended'})
        (self.source / 'engine.py').write_bytes(b'corrupt')
        with self.assertRaisesRegex(updater.UpdateError, 'checksum mismatch'):
            self.deploy()
        self.assertEqual(list(self.installed.iterdir()), [])

    def test_path_traversal_ads_devices_and_case_duplicates_are_rejected(self):
        for relative in ['../outside', '/absolute', 'lib/../outside', 'lib\\evil',
                         'file:stream', 'CON.py', 'a/nul', 'a./file', '.git/config']:
            with self.subTest(relative=relative):
                with self.assertRaises(updater.UpdateError):
                    updater.safe_path(str(self.installed), relative)
        self.payload({'Engine.py': b'a', 'engine.py': b'b'})
        with self.assertRaisesRegex(updater.UpdateError, 'Duplicate path'):
            self.deploy()

    def test_symlink_destination_parent_cannot_escape_extension(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.installed / 'lib').symlink_to(outside, target_is_directory=True)
        self.payload({'lib/engine.py': b'new'})
        with self.assertRaisesRegex(updater.UpdateError, 'link or junction'):
            self.deploy()
        self.assertEqual(list(outside.iterdir()), [])

    def test_compiled_payload_requires_closed_revit(self):
        self.payload({'engine.dll': b'compiled'})
        with self.assertRaisesRegex(updater.UpdateError, 'Compiled updates'):
            self.deploy()

    def test_failure_after_atomic_replace_restores_files_and_old_state(self):
        self.payload({'a.py': b'one', 'b.py': b'one'})
        self.deploy()
        state_before = (self.work / updater.STATE_NAME).read_bytes()
        self.payload({'a.py': b'two', 'b.py': b'two', 'c.py': b'added'})

        def fail_after_replace(source, destination):
            updater.atomic_copy(source, destination)
            if destination.endswith('b.py'):
                raise OSError('disk problem after replacing b')

        with self.assertRaisesRegex(OSError, 'disk problem'):
            self.deploy(copy_file=fail_after_replace)
        self.assertEqual((self.installed / 'a.py').read_bytes(), b'one')
        self.assertEqual((self.installed / 'b.py').read_bytes(), b'one')
        self.assertFalse((self.installed / 'c.py').exists())
        self.assertEqual((self.work / updater.STATE_NAME).read_bytes(), state_before)

    def test_failure_after_obsolete_removal_restores_removed_file(self):
        self.payload({'old.py': b'old'})
        self.deploy()
        self.payload({'new.py': b'new'})
        write = updater.write_json
        def fail_state(path, value):
            if path.endswith(updater.STATE_NAME):
                raise OSError('state write failed')
            return write(path, value)
        with patch.object(updater, 'write_json', side_effect=fail_state):
            with self.assertRaisesRegex(OSError, 'state write failed'):
                self.deploy()
        self.assertEqual((self.installed / 'old.py').read_bytes(), b'old')
        self.assertFalse((self.installed / 'new.py').exists())

    def test_state_for_another_installation_is_rejected(self):
        self.payload({'engine.py': b'new'})
        (self.work / updater.STATE_NAME).write_text(json.dumps({'extension_root': 'another folder', 'files': {}}))
        with self.assertRaisesRegex(updater.UpdateError, 'another extension folder'):
            self.deploy()

    def test_offline_update_keeps_tool_and_releases_lock(self):
        (self.installed / 'ROBMEPTOOLS.tab').mkdir()
        work = Path(updater.work_directory(str(self.installed))) if os.environ.get('LOCALAPPDATA') else self.work
        with patch.object(updater, 'work_directory', return_value=str(work)), \
             patch.object(updater, 'find_git', return_value='git'), \
             patch.object(updater, 'sync_source', side_effect=updater.UpdateError('offline')):
            with self.assertRaisesRegex(updater.UpdateError, 'offline'):
                updater.update_installed(str(self.installed), force=True)
        self.assertFalse((work / 'update.lock').exists())
        self.assertEqual([p.name for p in self.installed.iterdir()], ['ROBMEPTOOLS.tab'])

    def test_manual_update_rediscovers_git_after_desktop_replaces_version_folder(self):
        (self.installed / 'ROBMEPTOOLS.tab').mkdir()
        (self.work / 'settings.json').write_text(json.dumps({'git_path': str(self.root / 'removed-app/git.exe')}))
        bundled = self.root / 'localappdata/GitHubDesktop/app-3.4.12/resources/app/git/cmd/git.exe'
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(b'Git fixture')
        self.payload({'engine.py': b'updated'})
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'localappdata'),
                                     'ProgramFiles': '', 'ProgramFiles(x86)': ''}), \
             patch('distutils.spawn.find_executable', return_value=None), \
             patch.object(updater, 'work_directory', return_value=str(self.work)), \
             patch.object(updater, 'sync_source', return_value=str(self.source)) as sync:
            updater.update_installed(str(self.installed), force=True)
        self.assertEqual(sync.call_args.args[1], str(bundled))
        self.assertEqual((self.installed / 'engine.py').read_bytes(), b'updated')

    def test_lock_prevents_second_session(self):
        (self.installed / 'ROBMEPTOOLS.tab').mkdir()
        (self.work / 'update.lock').write_text('another session')
        with patch.object(updater, 'work_directory', return_value=str(self.work)):
            with self.assertRaisesRegex(updater.UpdateError, 'Another Revit session'):
                updater.update_installed(str(self.installed), force=True)
        self.assertTrue((self.work / 'update.lock').exists())

    def test_disabled_auto_update_does_not_contact_git(self):
        (self.installed / 'ROBMEPTOOLS.tab').mkdir()
        (self.work / 'settings.json').write_text('{"auto_update": false}')
        with patch.object(updater, 'work_directory', return_value=str(self.work)), \
             patch.object(updater, 'sync_source') as sync:
            self.assertTrue(updater.update_installed(str(self.installed))['disabled'])
            sync.assert_not_called()

    def test_reload_mode_is_off_by_default_for_scheduled_installations(self):
        (self.installed / 'ROBMEPTOOLS.tab').mkdir()
        with patch.object(updater, 'work_directory', return_value=str(self.work)), \
             patch.object(updater, 'sync_source') as sync:
            self.assertTrue(updater.update_installed(str(self.installed))['disabled'])
            sync.assert_not_called()

    def test_install_id_matches_windows_installer_normalization(self):
        root = str(self.installed)
        expected = hashlib.sha256(os.path.abspath(root).replace('\\', '/').rstrip('/').lower().encode('utf-8')).hexdigest()[:16]
        self.assertEqual(updater.installation_id(root), expected)


class RuntimeAdapterTests(unittest.TestCase):
    def fake_diagnostics(self, succeeds=True, times_out=False):
        values = types.SimpleNamespace(stdout='commit-hash', stderr='secret credential text',
                                       disposed=False, killed=False, info=None)
        class Stream:
            def __init__(self, text): self.text = text
            def ReadToEndAsync(self): return types.SimpleNamespace(Result=self.text)
        class Process:
            def __init__(self):
                self.StandardOutput = Stream(values.stdout)
                self.StandardError = Stream(values.stderr)
                self.ExitCode = 0 if succeeds else 128
            def Start(self): values.info = self.StartInfo
            def WaitForExit(self, timeout): return not times_out
            def Kill(self, whole_tree): values.killed = whole_tree
            def Dispose(self): values.disposed = True
        diagnostics = types.ModuleType('System.Diagnostics')
        diagnostics.Process = Process
        diagnostics.ProcessStartInfo = lambda: types.SimpleNamespace(EnvironmentVariables={})
        return diagnostics, values

    def test_process_adapter_disables_auth_prompts_and_quotes_paths(self):
        diagnostics, values = self.fake_diagnostics()
        with patch.dict(sys.modules, {'System.Diagnostics': diagnostics}):
            result = updater.run_git('C:\\Program Files\\Git\\cmd\\git.exe',
                                     ['-C', 'C:\\Folder with spaces', 'fetch'], 'C:\\Work')
        self.assertEqual(result, 'commit-hash')
        self.assertEqual(values.info.EnvironmentVariables['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(values.info.EnvironmentVariables['GCM_INTERACTIVE'], 'Never')
        self.assertIn('"C:\\Folder with spaces"', values.info.Arguments)
        self.assertTrue(values.disposed)

    def test_failed_auth_does_not_expose_git_stderr(self):
        diagnostics, values = self.fake_diagnostics(succeeds=False)
        with patch.dict(sys.modules, {'System.Diagnostics': diagnostics}):
            with self.assertRaises(updater.UpdateError) as error:
                updater.run_git('git.exe', ['fetch'], 'C:\\Work')
        self.assertNotIn('secret credential', str(error.exception))
        self.assertTrue(values.disposed)

    def test_timeout_kills_git_process_tree_and_reports_kept_tool(self):
        diagnostics, values = self.fake_diagnostics(times_out=True)
        with patch.dict(sys.modules, {'System.Diagnostics': diagnostics}):
            with self.assertRaisesRegex(updater.UpdateError, 'timed out; installed tool was kept'):
                updater.run_git('git.exe', ['fetch'], 'C:\\Work')
        self.assertTrue(values.killed)
        self.assertTrue(values.disposed)

    def test_idling_reload_is_deferred_and_unsubscribes_before_reload(self):
        class Event:
            def __init__(self): self.callbacks = []
            def __iadd__(self, callback): self.callbacks.append(callback); return self
            def __isub__(self, callback): self.callbacks.remove(callback); return self
        class GenericHandler:
            def __class_getitem__(cls, arg): return lambda fn: fn
        system = types.ModuleType('System')
        system.EventHandler = GenericHandler
        events = types.ModuleType('Autodesk.Revit.UI.Events')
        events.IdlingEventArgs = object
        uiapp = types.SimpleNamespace(Idling=Event())
        calls = []
        def reload_session():
            self.assertEqual(uiapp.Idling.callbacks, [])
            calls.append('reload')
        with patch.dict(sys.modules, {'System': system, 'Autodesk.Revit.UI.Events': events}):
            updater.queue_reload(uiapp, reload_session)
            self.assertEqual(calls, [])
            for callback in list(uiapp.Idling.callbacks): callback(uiapp, None)
        self.assertEqual(calls, ['reload'])
        self.assertEqual(uiapp.Idling.callbacks, [])


class RepositoryTests(unittest.TestCase):
    def test_wrong_origin_and_dirty_cache_stop_before_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.git').mkdir()
            calls = []
            def wrong_origin(exe, args, cwd):
                calls.append(args)
                return 'https://example.com/other.git'
            with self.assertRaisesRegex(updater.UpdateError, 'unexpected repository'):
                updater.sync_source(directory, 'git', wrong_origin)
            self.assertEqual(len(calls), 1)
            calls.clear()
            def dirty(exe, args, cwd):
                calls.append(args)
                return updater.REPOSITORY if args[0] == 'remote' else ' M engine.py'
            with self.assertRaisesRegex(updater.UpdateError, 'local edits'):
                updater.sync_source(directory, 'git', dirty)
            self.assertFalse(any(c[0] == 'fetch' for c in calls))

    @unittest.skipUnless(shutil.which('git'), 'Git is required')
    def test_real_git_fetch_and_deploy_tracks_two_remote_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, author, cache = [root / n for n in ['remote.git', 'author', 'cache']]
            def git(*args, cwd=None):
                return subprocess.check_output(['git', *map(str, args)], cwd=cwd, stderr=subprocess.PIPE, text=True).strip()
            git('init', '--bare', remote)
            git('init', '-b', 'main', author)
            git('config', 'user.name', 'Test', cwd=author)
            git('config', 'user.email', 'test@example.invalid', cwd=author)
            source = author / updater.SOURCE_FOLDER
            source.mkdir()
            rules = Path(__file__).resolve().parents[1] / '.gitattributes'
            (author / '.gitattributes').write_bytes(rules.read_bytes())
            def release(value):
                (source / 'engine.py').write_bytes(value)
                manifest = {'schema': 1, 'build': value.decode(),
                            'files': {'engine.py': hashlib.sha256(value).hexdigest()}}
                (source / updater.MANIFEST_NAME).write_text(json.dumps(manifest))
                git('add', '.', cwd=author)
                git('commit', '-m', value.decode(), cwd=author)
                git('push', str(remote), 'main', cwd=author)
            release(b'one\n')
            git('-c', 'core.autocrlf=true', 'clone', '--filter=blob:none', '--sparse', '--depth', '1', '--branch', 'main', remote, cache)
            git('config', 'core.autocrlf', 'true', cwd=cache)
            git('sparse-checkout', 'set', updater.SOURCE_FOLDER, cwd=cache)
            installed, work = root / 'custom folder' / 'Tool.extension', root / 'work'
            installed.mkdir(parents=True)
            work.mkdir()
            def runner(executable, args, cwd): return git(*args, cwd=cwd)
            with patch.object(updater, 'REPOSITORY', str(remote)):
                payload = updater.sync_source(str(cache), 'git', runner)
                updater.deploy(str(installed), payload, str(work))
                self.assertEqual((installed / 'engine.py').read_bytes(), b'one\n')
                # Multiple commits between Reloads must not require a merge or full clone.
                release(b'intermediate\n')
                release(b'two\n')
                payload = updater.sync_source(str(cache), 'git', runner)
                updater.deploy(str(installed), payload, str(work))
                self.assertEqual((installed / 'engine.py').read_bytes(), b'two\n')
                self.assertFalse(updater.deploy(str(installed), payload, str(work))['changed'])


if __name__ == '__main__':
    unittest.main()
