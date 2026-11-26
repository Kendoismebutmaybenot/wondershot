"""Finish a verified Builder update after its running process exits."""
import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_wonder as wonder


def wait_for_exit(pid):
    if pid <= 0 or pid == os.getpid():
        raise ValueError('Invalid Builder process id.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE, no termination rights
    if not handle:
        if ctypes.get_last_error() == 87:  # The process has already exited.
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, 120_000) != 0:
            raise TimeoutError('The Builder has not closed. Close it and retry the update.')
    finally:
        kernel.CloseHandle(handle)


def replace_files(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('The update and installed Builder folders must be separate.')
    tag, old = wonder.builder_release(str(source)), wonder.builder_release(str(target))
    needed = ('WondershotBuilder.dll', 'WondershotBuilder.runtimeconfig.json',
              'tools/python/python.exe', 'tools/nx2/make_wonder.py', 'tools/nx2/builder_update.py')
    if (not wonder.BUILDER_TAG.fullmatch(tag) or
            wonder.installed_version(str(source / 'tools')) != tag or
            not all((source / name).is_file() for name in needed)):
        raise ValueError('The downloaded Builder is incomplete.')
    if not (target / 'WondershotBuilder.exe').is_file() or wonder.newer(old, tag):
        raise ValueError('The installed Builder is missing or newer than this update.')
    files = []
    for item in source.rglob('*'):
        if item.is_symlink():
            raise ValueError('The update contains a symbolic link.')
        if item.is_file() and item.name not in ('builder-update.log', 'builder_update_target.txt'):
            rel = item.relative_to(source)
            dest = (target / rel).resolve()
            if target not in dest.parents or dest.is_dir():
                raise ValueError('An installed Builder file has an invalid destination.')
            files.append(rel)
    # Write the version stamps last. A partially installed update is never current.
    files.sort(key=lambda p: (p.as_posix() in ('builder_version.txt', 'tools/version.txt'), p.as_posix()))
    transaction = Path(tempfile.mkdtemp(prefix='.builder-update-', dir=target))
    changed = []
    try:
        for rel in files:
            dest, backup = target / rel, transaction / 'old' / rel
            fresh = transaction / 'new' / rel
            fresh.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, fresh)
            existed = dest.exists()
            if existed:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(fresh, dest)
            changed.append((rel, existed))
    except BaseException:
        try:
            for rel, existed in reversed(changed):
                if existed:
                    os.replace(transaction / 'old' / rel, target / rel)
                else:
                    (target / rel).unlink()
        except OSError as error:
            raise OSError(f'The previous Builder could not be restored. Backup: {transaction}') from error
        shutil.rmtree(transaction)
        raise
    shutil.rmtree(transaction)
    return target / 'WondershotBuilder.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--wait-pid', type=int, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2]
    target = Path(args.target).resolve()
    try:
        wait_for_exit(args.wait_pid)
        exe = replace_files(source, target)
        # The reopened Builder removes this temporary download after we exit.
        (source / 'builder_update_target.txt').write_text(str(target), encoding='utf-8')
        subprocess.Popen([str(exe), '--cleanup-builder-update', str(source), str(os.getpid())], cwd=target)
    except Exception as error:
        log = source / 'builder-update.log'
        log.write_text(str(error), encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None, f'The Builder update could not be completed.\n\n{error}\n\nDetails: {log}',
                                        'Wondershot Builder', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
