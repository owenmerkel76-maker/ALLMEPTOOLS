"""Build the live-source manifest and one-time Windows updater package."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'ROBMEPTOOLS.extension'
MANIFEST = EXTENSION / 'update-manifest.json'
OUT = ROOT / 'downloads/ROBMEPTOOLS-AutoUpdate.zip'


def main():
    files = sorted(p for p in EXTENSION.rglob('*') if p.is_file() and p != MANIFEST
                   and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
    previous = {}
    for archive in sorted((ROOT / 'downloads').glob('ROBMEPTOOLS-*.zip')):
        if archive == OUT:
            continue
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None, str(archive)
            for name in bundle.namelist():
                prefix = 'ROBMEPTOOLS.extension/'
                if name.startswith(prefix) and not name.endswith('/'):
                    relative = name[len(prefix):]
                    previous.setdefault(relative, set()).add(hashlib.sha256(bundle.read(name)).hexdigest())
    # Preserve the previous live manifest and release hashes across rebuilds too.
    old = None
    if MANIFEST.is_file():
        previous.setdefault(MANIFEST.name, set()).add(hashlib.sha256(MANIFEST.read_bytes()).hexdigest())
        old = json.loads(MANIFEST.read_text())
        for relative, hashes in old.get('previous_hashes', {}).items():
            previous.setdefault(relative, set()).update(hashes)
        for relative, digest in old.get('files', {}).items():
            previous.setdefault(relative, set()).add(digest)
    bootstrap = ['startup.py', 'lib/robmep_updater.py', 'ROBMEPTOOLS.tab/bundle.yaml',
                 'ROBMEPTOOLS.tab/Updates.panel/bundle.yaml']
    bootstrap += [p.relative_to(EXTENSION).as_posix() for p in files
                  if 'Update Tool.pushbutton' in p.parts]
    bootstrap += [p.relative_to(EXTENSION).as_posix() for p in files if 'updater' in p.parts]
    bootstrap.append(MANIFEST.name)
    value = {'schema': 1, 'build': 'ROBMEPTOOLS scheduled updater 1 / Duct AutoDim 6.8 text pockets / Duct AutoTag 5 all straight duct targets',
             'restart_required': False,
             'files': {p.relative_to(EXTENSION).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
             'previous_hashes': {r: sorted(h) for r, h in sorted(previous.items())},
             'bootstrap_files': bootstrap}
    serialized = json.dumps(value, indent=2, sort_keys=True) + '\n'
    # Rebuilding unchanged source must not grow a history of its own manifests.
    if not (old and old.get('files') == value['files'] and old.get('build') == value['build']
            and old.get('bootstrap_files') == value['bootstrap_files']):
        MANIFEST.write_text(serialized)
    package_files = files + [MANIFEST] + sorted((ROOT / 'installer').glob('*')) + [ROOT / 'AUTOUPDATE.md', ROOT / 'Setup Auto Updates.cmd', ROOT / 'Check Auto Updates.cmd']
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(package_files):
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 10, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())
    with zipfile.ZipFile(OUT) as bundle:
        assert bundle.testzip() is None
        for path in package_files:
            assert bundle.read(path.relative_to(ROOT).as_posix()) == path.read_bytes()
    print(OUT)
    print('Files:', len(package_files))
    print('SHA256:', hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
