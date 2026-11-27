"""Build the Windows online runtime from the bundled, pinned open-source sources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = (
    ('cmake', '8c31aabdf2223a7bb5759209ada56a9a72c6a1c605c221f23967130d1989e171', 48623249,
     'https://github.com/Kitware/CMake/releases/download/v4.1.4/cmake-4.1.4-windows-x86_64.zip', 'cmake-4.1.4-windows-x86_64/bin/cmake.exe'),
    ('ninja', '07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65', 291570,
     'https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip', 'ninja.exe'),
)


def digest(path):
    with open(path, 'rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def unpack(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        if sum(item.file_size for item in source.infolist()) > 512 * 1024 * 1024:
            raise ValueError('Online dependency archive exceeds the size limit')
        for item in source.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination) or item.filename.startswith(('/', '\\')):
                raise ValueError('Unsafe online dependency archive path')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Online dependency archive contains a symlink')
        source.extractall(destination)


def tool(cache, spec):
    name, sha, size, url, executable = spec
    folder = cache / (name + '-' + sha[:12])
    archive = cache / (name + '-' + sha[:12] + '.zip')
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or archive.stat().st_size != size or digest(archive) != sha:
        print('Fetching pinned online build tool: ' + name, flush=True)
        request = urllib.request.Request(url, headers={'User-Agent': 'WondershotBuilder'})
        partial = archive.with_suffix('.part')
        with urllib.request.urlopen(request, timeout=60) as response, open(partial, 'wb') as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError('Online build tool exceeds its pinned size')
                output.write(chunk)
        if partial.stat().st_size != size or digest(partial) != sha:
            raise ValueError('Online build tool checksum mismatch: ' + name)
        partial.replace(archive)
    if not (folder / executable).is_file():
        unpack(archive, folder)
    return folder / executable


def cmake_source_args(build, source):
    """CMake records an absolute source root; a moved Builder must reconfigure it."""
    cache = Path(build) / 'CMakeCache.txt'
    if not cache.is_file():
        return []
    prefix = 'CMAKE_HOME_DIRECTORY:INTERNAL='
    previous = next((line[len(prefix):] for line in cache.read_text(encoding='utf-8', errors='replace').splitlines()
                     if line.startswith(prefix)), '')
    same = previous and os.path.normcase(os.path.realpath(previous)) == os.path.normcase(os.path.realpath(source))
    return [] if same else ['--fresh']


class OnlineBuildError(Exception):
    pass


_DIRTY_MANIFEST = "ninja: error: manifest 'build.ninja' still dirty after "


def _cmake_run(command, environment):
    # Keep progress in the Builder log and retain the actual error for the popup.
    error = last_line = ''
    with subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding='utf-8', errors='replace') as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            line = line.strip()
            if line:
                last_line = line
            if line.startswith(_DIRTY_MANIFEST):
                error = line
            elif not error.startswith(_DIRTY_MANIFEST) and ('error:' in line.lower() or line.startswith('CMake Error')):
                error = line
        status = process.wait()
    return status, error or last_line or f'exit code {status}'


def _build_runtime(configure, compile_runtime, source_args, environment):
    status, reason = _cmake_run(configure[:1] + source_args + configure[1:], environment)
    if status:
        raise OnlineBuildError(f'Could not configure the online runtime: {reason}')
    status, reason = _cmake_run(compile_runtime, environment)
    if status and reason.startswith(_DIRTY_MANIFEST):
        print('The online build files stayed out of date. Refreshing the online build and retrying once.', flush=True)
        # The Builder configures CMake explicitly every time. Suppress Ninja's
        # redundant regeneration so a stale or future input timestamp cannot loop.
        status, reason = _cmake_run(
            configure[:1] + ['--fresh', '-DCMAKE_SUPPRESS_REGENERATION=ON'] + configure[1:], environment)
        if status:
            raise OnlineBuildError(f'Could not refresh the online build files: {reason}')
        status, reason = _cmake_run(compile_runtime, environment)
    if status:
        raise OnlineBuildError(f'Could not build the online runtime: {reason}')


def libraries(out, compiler, jobs):
    """Called by the ordinary Builder. No game data, Git, Perl or pip is required."""
    out = Path(out).resolve()
    source = ROOT / 'host' / 'wonder_online'
    vendor = ROOT / 'third_party' / 'wonder-online'
    manifest = json.loads((vendor / 'sources.json').read_text(encoding='utf-8'))
    archive = vendor / 'sources.zip'
    if archive.stat().st_size != manifest['size'] or digest(archive) != manifest['sha256']:
        raise ValueError('Bundled online source checksum mismatch')
    dependencies = out / ('online-deps-' + manifest['sha256'][:12])
    if not (dependencies / '.complete').is_file():
        unpack(archive, dependencies)
        (dependencies / '.complete').write_text(manifest['sha256'], encoding='ascii')
    cmake, ninja = [tool(out / 'online-tools', spec) for spec in TOOLS]
    compiler = Path(compiler).resolve()
    build = out / 'online'
    build.mkdir(parents=True, exist_ok=True)
    toolchain = build / 'toolchain.cmake'
    toolchain.write_text('\n'.join([
        'set(CMAKE_SYSTEM_NAME Windows)',
        'set(CMAKE_C_COMPILER ' + json.dumps(compiler.as_posix()) + ')',
        'set(CMAKE_CXX_COMPILER ' + json.dumps(compiler.with_name('clang++.exe').as_posix()) + ')',
        'set(CMAKE_C_COMPILER_TARGET x86_64-w64-mingw32)',
        'set(CMAKE_CXX_COMPILER_TARGET x86_64-w64-mingw32)',
    ]) + '\n', encoding='utf-8', newline='\n')
    environment = dict(os.environ)
    environment['PATH'] = str(compiler.parent) + os.pathsep + environment.get('PATH', '')
    print('Building the native online runtime (incremental)', flush=True)
    configure = [str(cmake), '-S', str(source), '-B', str(build), '-G', 'Ninja',
                 '-DCMAKE_TOOLCHAIN_FILE=' + str(toolchain), '-DCMAKE_MAKE_PROGRAM=' + str(ninja),
                 '-DCMAKE_BUILD_TYPE=Release', '-DWONDER_DEPS=' + dependencies.as_posix()]
    compile_runtime = [str(cmake), '--build', str(build), '--target', 'wonder_online', '-j', str(max(1, min(jobs, 4)))]
    _build_runtime(configure, compile_runtime, cmake_source_args(build, source), environment)
    names = ('libwonder_online.a', 'datachannel/libdatachannel-static.a',
             'datachannel/deps/usrsctp/usrsctplib/libusrsctp.a', 'mbedtls/library/libmbedtls.a',
             'mbedtls/library/libmbedx509.a', 'mbedtls/library/libmbedcrypto.a',
             'mbedtls/3rdparty/everest/libeverest.a', 'mbedtls/3rdparty/p256-m/libp256m.a',
             'datachannel/deps/libjuice/libjuice-static.a')
    paths = [str(build / name) for name in names]
    if not all(Path(path).is_file() for path in paths):
        raise ValueError('The online runtime build did not produce all libraries')
    return paths + ['-lws2_32', '-lwinhttp', '-lbcrypt', '-liphlpapi', '-lpthread']


def redirect_socket(objects, compiler, out):
    """Redirect only Wonder's one private discovery initializer call, in a local copy."""
    matches = [path for path in objects if Path(path).name == 'code_019.o']
    if len(matches) != 1:
        raise ValueError('Wonder discovery initializer object is missing or ambiguous')
    source = Path(matches[0])
    symbols = subprocess.check_output([str(Path(compiler).with_name('llvm-nm.exe')), '--undefined-only', str(source)], text=True)
    if sum(line.strip().endswith(' f_83e23480') for line in symbols.splitlines()) != 1:
        raise ValueError('The supported Wonder discovery initializer reference changed')
    # Do not rename the SDK definition or other callers. This object's relocation is the one call.
    target = Path(out) / 'wonder_discovery.o'
    subprocess.run([str(Path(compiler).with_name('llvm-objcopy.exe')),
                    '--redefine-sym=f_83e23480=hos_wonder_discovery_socket_init', str(source), str(target)], check=True)
    return [str(target) if Path(path) == source else path for path in objects]
