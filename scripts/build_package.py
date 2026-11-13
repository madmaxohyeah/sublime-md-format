"""Build an allowlisted, byte-reproducible Sublime Text package."""
import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = (
    '.python-version', 'markdown_formatting.py',
    'mdformat/__init__.py', 'mdformat/catalog.py', 'mdformat/engine.py', 'mdformat/picker.py',
    'mdformat/sublime_picker.py',
    'Context.sublime-menu', 'Main.sublime-menu', 'Default.sublime-commands',
    'MarkdownFormatting.sublime-settings', 'README.md', 'LICENSE', 'CHANGELOG.md',
    'docs/configuration.md', 'docs/compatibility.md',
)


def build(destination):
    destination = Path(destination)
    contents = [(name, (ROOT / name).read_bytes()) for name in sorted(PACKAGE_FILES)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    # ZIP_STORED makes bytes independent of zlib release/platform differences.
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, content in contents:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/MarkdownFormatting.sublime-package')
    args = parser.parse_args()
    digest = build(args.output)
    checksum = args.output.with_suffix(args.output.suffix + '.sha256')
    checksum.write_text('{}  {}\n'.format(digest, args.output.name), encoding='utf-8')
    print('{}  {}'.format(digest, args.output))


if __name__ == '__main__':
    main()
