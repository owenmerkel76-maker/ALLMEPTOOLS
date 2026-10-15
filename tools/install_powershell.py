"""Install a checksum-verified, repository-external Linux test toolchain."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

VERSION = '7.4.13'
SHA256 = '59e5df675dacbfe45374c32c1bf2480168a33243423c9b19252d0476fd1b748c'
DEST = Path('/workspace/robmep-toolchains') / ('powershell-' + VERSION)


def main():
    if shutil.which('pwsh'):
        print('Using PowerShell on PATH')
        return
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('This bootstrap targets Linux x86_64; install PowerShell for your platform separately.')
    # Reuse the checksum-verified download, but revalidate before extraction.
    archive = Path('/tmp/robmep-powershell.tar.gz')
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        url = 'https://github.com/PowerShell/PowerShell/releases/download/v{0}/powershell-{0}-linux-x64.tar.gz'.format(VERSION)
        with tempfile.NamedTemporaryFile(dir='/tmp', delete=False) as tmp:
            temporary = Path(tmp.name)
        try:
            urllib.request.urlretrieve(url, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
                raise RuntimeError('PowerShell checksum mismatch; refusing installation')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(DEST, filter='data')
    (DEST / 'pwsh').chmod(0o755)
    print('Verified PowerShell ' + VERSION + ' at ' + str(DEST))


if __name__ == '__main__':
    main()
