"""Run real Sublime Text archive tests on an isolated Linux/Xvfb display.

Requires an extracted official Sublime Text portable directory and Xvfb.
Never point --sublime-dir at a personal installation: an existing Data directory
is intentionally refused. No downloads or system installations are performed.
"""
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def editor_environment(parent, display, evidence):
    """Keep the CI interpreter's search paths out of Sublime's embedded host."""
    env = dict(parent)
    for name in ('LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH'):
        env.pop(name, None)
    env.update(DISPLAY=display, MD_FORMAT_EVIDENCE=evidence)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sublime-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.sublime_dir.resolve() / 'sublime_text'
    data = binary.parent / 'Data'
    data.mkdir(exist_ok=False)
    installed = data / 'Installed Packages'
    user = data / 'Packages/User'
    installed.mkdir()
    user.mkdir(parents=True)
    shutil.copy2(ROOT / 'dist/MarkdownFormatting.sublime-package', installed)
    shutil.copy2(ROOT / 'scripts/runtime_driver.py', user)
    (user / 'Preferences.sublime-settings').write_text(json.dumps({
        'update_check': False, 'hot_exit': False, 'remember_open_files': False,
        'hardware_acceleration': 'none', 'show_rel_path': False,
    }), encoding='utf-8')
    args.output.mkdir(parents=True, exist_ok=True)
    report = args.output.resolve() / 'runtime.json'
    if report.exists():
        raise SystemExit('Refusing to reuse prior runtime.json evidence')
    # Xvfb chooses an unused display; no assumptions about the user's desktop.
    read_fd, write_fd = os.pipe()
    processes = []
    try:
        with (args.output / 'editor.log').open('w', encoding='utf-8') as log:
            xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                                     '1440x1000x24', '-nolisten', 'tcp'],
                                    pass_fds=(write_fd,), stdout=log, stderr=log)
            processes.append(xvfb)
            os.close(write_fd)
            write_fd = None
            with os.fdopen(read_fd) as display_pipe:
                display = display_pipe.readline().strip()
            if not display:
                raise RuntimeError('Xvfb failed to allocate a display')
            env = editor_environment(os.environ, ':' + display,
                                     str(args.output.resolve()))
            editor = subprocess.Popen([str(binary), '--multiinstance'], env=env, stdout=log, stderr=log)
            processes.append(editor)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and not report.exists():
                if editor.poll() is not None:
                    raise RuntimeError('Editor exited before producing evidence')
                time.sleep(0.25)
            if not report.exists():
                raise RuntimeError('Editor runtime timed out; see editor.log')
            result = json.loads(report.read_text(encoding='utf-8'))
            if not result.get('passed'):
                raise RuntimeError(result.get('error', 'Runtime assertions failed'))
            print('PASS: Sublime {} — {} real-editor cases — {}'.format(
                result['build'], len(result['cases']), result['archive_sha256']))
    finally:
        if write_fd is not None:
            os.close(write_fd)
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
