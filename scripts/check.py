"""Canonical local/CI gate; no non-stdlib dependencies."""
import ast
import hashlib
import io
import pathlib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from build_package import PACKAGE_FILES, ROOT, build


def check_release_archive():
    """Fail unless the tag archive Package Control installs holds exactly PACKAGE_FILES.

    Package Control downloads GitHub's archive of a version tag, which is
    ``git archive`` honoring ``export-ignore`` in ``.gitattributes``. This
    archives the staged tree the same way and compares its files, and its
    folders (so no empty leftovers), with the builder's list.
    """
    if not (ROOT / '.git').exists():
        return
    tree = subprocess.run(['git', 'write-tree'], cwd=str(ROOT), check=True,
                          stdout=subprocess.PIPE).stdout.decode('ascii').strip()
    data = subprocess.run(['git', 'archive', '--worktree-attributes', '--format=tar', tree],
                          cwd=str(ROOT), check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
    files = {m.name for m in members if m.isfile()}
    folders = {m.name.rstrip('/') for m in members if m.isdir()}
    expected = set(PACKAGE_FILES)
    expected_folders = {str(pathlib.PurePosixPath(name).parent) for name in expected} - {'.'}
    expected_folders |= {str(p) for name in expected_folders for p in pathlib.PurePosixPath(name).parents} - {'.'}
    if files != expected or folders != expected_folders:
        raise SystemExit('Release archive differs from PACKAGE_FILES. Extra: {}; missing: {}. '
                         'Update export-ignore in .gitattributes.'.format(
                             sorted((files - expected) | (folders - expected_folders)),
                             sorted((expected - files) | (expected_folders - folders))))


def main():
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=str(ROOT), check=True)
    for name in ('mdformat', 'tests', 'scripts'):
        for path in (ROOT / name).glob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3, 8))
    ast.parse((ROOT / 'markdown_formatting.py').read_text(encoding='utf-8'), feature_version=(3, 8))
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'MarkdownFormatting.sublime-package'
        digest = build(target)
        shipped = ROOT / 'dist' / target.name
        if target.read_bytes() != shipped.read_bytes():
            raise SystemExit('Tracked package is stale. Run python3 scripts/build_package.py and commit dist/.')
        expected = '{}  {}\n'.format(digest, target.name)
        if shipped.with_suffix(shipped.suffix + '.sha256').read_text(encoding='utf-8') != expected:
            raise SystemExit('Tracked package checksum is stale.')
    check_release_archive()
    print('PASS: tests, Python 3.8 syntax, reproducible package, release archive and SHA-256 ' + hashlib.sha256(shipped.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
