# -*- coding: utf-8 -*-
"""Reload-time updates for the installed extension; Python 2/IronPython safe.

Only manifest-owned files are deployed. Git authentication stays with Git's
credential manager; tokens are never saved in the extension or printed here.
"""
from __future__ import print_function

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

REPOSITORY = 'https://github.com/owenmerkel76-maker/MEPTOOL.git'
BRANCH = 'main'
MANIFEST_NAME = 'update-manifest.json'
STATE_NAME = 'installed-state.json'
SOURCE_FOLDER = 'ROBMEPTOOLS.extension'
MAX_FILES = 500


class UpdateError(Exception):
    pass


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    with open(path, 'rb') as stream:
        return json.loads(stream.read().decode('utf-8-sig'))


def _replace(source, destination):
    if os.name == 'nt':
        from System.IO import File
        if os.path.exists(destination):
            File.Replace(source, destination, None)
        else:
            File.Move(source, destination)
    else:
        os.rename(source, destination)


def atomic_copy(source, destination):
    parent = os.path.dirname(destination)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    descriptor, temporary = tempfile.mkstemp(prefix='.robmep-', dir=parent)
    os.close(descriptor)
    try:
        shutil.copyfile(source, temporary)
        _replace(temporary, destination)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)


def write_json(path, value):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    descriptor, temporary = tempfile.mkstemp(prefix='.robmep-', dir=parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True).encode('utf-8'))
        _replace(temporary, path)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)


def _is_link(path):
    if os.path.islink(path):
        return True
    if os.name == 'nt' and os.path.exists(path):
        from System.IO import File, FileAttributes
        return bool(File.GetAttributes(path) & FileAttributes.ReparsePoint)
    return False


def safe_path(root, relative):
    if not isinstance(relative, type(u'')):
        # JSON produces unicode under IronPython 2, str under Python 3.
        try:
            relative = relative.decode('utf-8')
        except AttributeError:
            raise UpdateError('Invalid manifest path.')
    parts = relative.split('/')
    devices = set(['con', 'prn', 'aux', 'nul', 'clock$']
                  + ['com' + str(i) for i in range(1, 10)]
                  + ['lpt' + str(i) for i in range(1, 10)])
    if (not relative or '\\' in relative or ':' in relative or '\x00' in relative
            or any(p in ('', '.', '..') for p in parts)
            or any(p.rstrip(' .') != p for p in parts)
            or any(p.lower() in ('.git', '__pycache__') for p in parts)
            or any(p.split('.')[0].lower() in devices for p in parts)
            or any(ord(c) < 32 for c in relative)):
        raise UpdateError('Unsafe manifest path: ' + relative)
    current = os.path.abspath(root)
    for part in parts:
        current = os.path.join(current, part)
        if _is_link(current):
            raise UpdateError('Update path is a link or junction: ' + relative)
    return current


def _valid_digest(digest):
    return (isinstance(digest, type(u'')) and len(digest) == 64
            and all(c in '0123456789abcdef' for c in digest))


def validate_payload(source_root):
    manifest_path = safe_path(source_root, MANIFEST_NAME)
    manifest = read_json(manifest_path)
    files = manifest.get('files')
    if (manifest.get('schema') != 1 or not isinstance(files, dict)
            or not files or len(files) > MAX_FILES or MANIFEST_NAME in files):
        raise UpdateError('Unsupported or empty update manifest.')
    if manifest.get('restart_required'):
        raise UpdateError('This release needs Revit closed; it cannot be installed on Reload.')
    normalized = set()
    for relative, digest in files.items():
        lower = relative.lower()
        if lower in normalized or not _valid_digest(digest):
            raise UpdateError('Duplicate path or invalid checksum: ' + relative)
        normalized.add(lower)
        if os.path.splitext(lower)[1] in ('.dll', '.exe', '.pyd'):
            raise UpdateError('Compiled updates require Revit to be closed: ' + relative)
        source = safe_path(source_root, relative)
        if not os.path.isfile(source) or file_hash(source) != digest:
            raise UpdateError('Update checksum mismatch: ' + relative)
    previous = manifest.get('previous_hashes', {})
    if not isinstance(previous, dict):
        raise UpdateError('Invalid previous-release hashes.')
    for relative, hashes in previous.items():
        safe_path(source_root, relative)
        if not isinstance(hashes, list) or not all(_valid_digest(h) for h in hashes):
            raise UpdateError('Invalid previous-release hashes: ' + relative)
    return manifest


def plan_update(installed_root, source_root, manifest, state=None):
    wanted = dict(manifest['files'])
    wanted[MANIFEST_NAME] = file_hash(safe_path(source_root, MANIFEST_NAME))
    previous = manifest.get('previous_hashes', {})
    old_files = state.get('files', {}) if state else {}
    operations = []
    for relative, digest in sorted(wanted.items()):
        destination = safe_path(installed_root, relative)
        if os.path.exists(destination) and not os.path.isfile(destination):
            raise UpdateError('Expected a file, found a folder: ' + relative)
        actual = file_hash(destination) if os.path.isfile(destination) else None
        if actual == digest:
            continue
        if actual is not None:
            accepted = [old_files[relative]] if relative in old_files else previous.get(relative, [])
            if actual not in accepted:
                raise UpdateError('Local edits preserved; update stopped at: ' + relative)
        operations.append((relative, 'copy', actual))
    for relative, digest in sorted(old_files.items()):
        if relative in wanted:
            continue
        destination = safe_path(installed_root, relative)
        if os.path.exists(destination):
            if not os.path.isfile(destination) or file_hash(destination) != digest:
                raise UpdateError('Locally edited obsolete file preserved: ' + relative)
            operations.append((relative, 'remove', digest))
    return operations, wanted


def deploy(installed_root, source_root, work_dir, copy_file=atomic_copy):
    """Verify everything before mutation; restore changed files on any failure."""
    manifest = validate_payload(source_root)
    state_path = os.path.join(work_dir, STATE_NAME)
    state = read_json(state_path) if os.path.isfile(state_path) else None
    if state and os.path.normcase(state.get('extension_root', '')) != os.path.normcase(os.path.abspath(installed_root)):
        raise UpdateError('Update state belongs to another extension folder.')
    operations, wanted = plan_update(installed_root, source_root, manifest, state)
    backup = None
    applied = []
    if operations:
        backup_parent = os.path.join(work_dir, 'backups')
        if not os.path.isdir(backup_parent):
            os.makedirs(backup_parent)
        stamp = time.strftime('%Y%m%dT%H%M%SZ-', time.gmtime())
        backup = tempfile.mkdtemp(prefix=stamp, dir=backup_parent)
        write_json(os.path.join(backup, 'restore.json'), {
            'extension_root': os.path.abspath(installed_root),
            'operations': operations, 'previous_state': state})
        for relative, action, old_hash in operations:
            if old_hash is not None:
                destination = safe_path(backup, relative)
                parent = os.path.dirname(destination)
                if not os.path.isdir(parent):
                    os.makedirs(parent)
                shutil.copy2(safe_path(installed_root, relative), destination)
    try:
        for relative, action, old_hash in operations:
            destination = safe_path(installed_root, relative)
            # Record before copying: an exception after replacement must roll back too.
            applied.append((relative, action, old_hash))
            if action == 'copy':
                copy_file(safe_path(source_root, relative), destination)
                if file_hash(destination) != wanted[relative]:
                    raise UpdateError('Installed checksum mismatch: ' + relative)
            else:
                os.remove(destination)
        write_json(state_path, {'schema': 1, 'extension_root': os.path.abspath(installed_root),
                                'files': wanted, 'build': manifest.get('build')})
    except Exception:
        failures = []
        for relative, action, old_hash in reversed(applied):
            try:
                destination = safe_path(installed_root, relative)
                if old_hash is None:
                    if os.path.isfile(destination):
                        os.remove(destination)
                else:
                    atomic_copy(safe_path(backup, relative), destination)
            except Exception:
                failures.append(relative)
        if failures:
            raise UpdateError('Rollback incomplete for ' + ', '.join(failures)
                              + '. Backup: ' + str(backup))
        raise
    return {'changed': bool(operations), 'file_count': len(operations),
            'build': manifest.get('build', 'unknown'), 'backup': backup,
            'extension_root': os.path.abspath(installed_root)}


def installation_id(root):
    normalized = os.path.abspath(root).replace('\\', '/').rstrip('/').lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def work_directory(root):
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise UpdateError('LOCALAPPDATA is unavailable; updater requires Windows/Revit.')
    return os.path.join(local, 'ROBMEPTOOLS', 'updates', installation_id(root))


def find_git():
    from distutils.spawn import find_executable
    import glob
    executable = find_executable('git.exe') or find_executable('git')
    if executable:
        return executable
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        parent = os.environ.get(variable)
        if parent:
            roots = [os.path.join(parent, 'Git'), os.path.join(parent, 'Programs', 'Git')]
            desktop = os.path.join(parent, 'GitHubDesktop')
            versions = sorted(glob.glob(os.path.join(desktop, 'app-*')),
                              key=os.path.getmtime, reverse=True)
            roots.append(os.path.join(desktop, 'resources', 'app', 'git'))
            roots.extend(os.path.join(version, 'resources', 'app', 'git') for version in versions)
            for root in roots:
                for folder in ('cmd', 'bin'):
                    candidate = os.path.join(root, folder, 'git.exe')
                    if os.path.isfile(candidate):
                        return candidate
    raise UpdateError('Git was not found. Run Setup Auto Updates.cmd to locate your Git installation and check sign-in.')


def run_git(executable, arguments, cwd, timeout_ms=25000):
    """Use Windows credential manager without prompting during Revit Reload."""
    from System.Diagnostics import Process, ProcessStartInfo
    info = ProcessStartInfo()
    info.FileName = executable
    info.Arguments = subprocess.list2cmdline(arguments)
    info.WorkingDirectory = cwd
    info.UseShellExecute = False
    info.CreateNoWindow = True
    info.RedirectStandardOutput = True
    info.RedirectStandardError = True
    info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    info.EnvironmentVariables['GCM_INTERACTIVE'] = 'Never'
    process = Process()
    process.StartInfo = info
    try:
        process.Start()
        output = process.StandardOutput.ReadToEndAsync()
        error = process.StandardError.ReadToEndAsync()
        if not process.WaitForExit(timeout_ms):
            try:
                process.Kill(True)
            except Exception:
                process.Kill()
            raise UpdateError('GitHub update timed out; installed tool was kept.')
        stdout = str(output.Result).strip()
        # Drain stderr but never expose credential-bearing network output.
        error.Result  # Drain stderr without displaying credential-bearing output.
        if process.ExitCode != 0:
            raise UpdateError('GitHub could not be read. Run Install-Updater.cmd to check your '
                              'GitHub sign-in. The installed tool was kept.')
        return stdout
    finally:
        process.Dispose()


def sync_source(cache, executable, runner=run_git):
    if not os.path.isdir(os.path.join(cache, '.git')):
        raise UpdateError('One-time setup is needed: run Install-Updater.cmd from the updater ZIP.')
    origin = runner(executable, ['remote', 'get-url', 'origin'], cache)
    if origin.rstrip('/') != REPOSITORY:
        raise UpdateError('Updater cache has an unexpected repository; it was left unchanged.')
    if runner(executable, ['status', '--porcelain'], cache):
        raise UpdateError('Updater cache has local edits; it was left unchanged.')
    runner(executable, ['fetch', '--filter=blob:none', 'origin', BRANCH], cache)
    commit = runner(executable, ['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], cache)
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise UpdateError('GitHub returned an invalid revision.')
    runner(executable, ['checkout', '--detach', commit], cache)
    return os.path.join(cache, SOURCE_FOLDER)


def update_installed(root, force=False, runner=run_git):
    root = os.path.abspath(root)
    if not os.path.isdir(os.path.join(root, 'ROBMEPTOOLS.tab')):
        raise UpdateError('Updater is not inside the active ROBMEPTOOLS extension.')
    work = work_directory(root)
    if not os.path.isdir(work):
        os.makedirs(work)
    settings_path = os.path.join(work, 'settings.json')
    settings = read_json(settings_path) if os.path.isfile(settings_path) else {}
    if not force and not settings.get('auto_update', False):
        return {'changed': False, 'disabled': True, 'extension_root': root}
    lock = os.path.join(work, 'update.lock')
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        raise UpdateError('Another Revit session is updating this tool. Try Reload again later. '
                          'If all Revit sessions are closed, remove the stale lock: ' + lock)
    try:
        try:
            os.write(descriptor, str(os.getpid()).encode('ascii'))
        finally:
            os.close(descriptor)
        cache = os.path.join(work, 'repository')
        executable = settings.get('git_path')
        if not executable or not os.path.isfile(executable):
            executable = find_git()
        source = sync_source(cache, executable, runner)
        return deploy(root, source, work)
    finally:
        os.remove(lock)


def queue_reload(uiapp, reload_function, on_error=None):
    """Reload at the next Revit idle callback, never recursively in startup."""
    from System import EventHandler
    from Autodesk.Revit.UI.Events import IdlingEventArgs
    delegate = [None]

    def reload_once(sender, args):
        uiapp.Idling -= delegate[0]
        try:
            reload_function()
        except Exception as error:
            message = 'Tool files were updated; click pyRevit Reload again. ' + str(error)
            if on_error:
                on_error(message)
            else:
                print(message)

    delegate[0] = EventHandler[IdlingEventArgs](reload_once)
    uiapp.Idling += delegate[0]
    return delegate[0]
