#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional, local-only Boltz-1 adapter; this is a trusted-code runner, not a sandbox."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shlex
import signal
import stat
import subprocess
import sys
import threading
import time

SCHEMA = 'research-writer.structure.v1'
REVISION = 'b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc'
MODEL_REVISION = '7c1d83b779e4c65ecc37dfdf0c6b2788076f31e1'
ASSETS = {
    'boltz1_conf.ckpt': 'fea245d912c570ec117b2277c2719f312a6fc109c07b6f6ef741690ee775c2f5',
    'ccd.pkl': '2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4',
}
AA3 = dict(zip('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split(),
               'ARNDCQEGHILKMFPSTWYV'))
BACKBONE = {'N', 'CA', 'C', 'O'}
REQUIRED = {'schema', 'python', 'boltz_source', 'assets_dir', 'output_dir', 'sequence',
            'chain_id', 'device', 'seed', 'threads', 'timeout_seconds', 'recycling_steps',
            'sampling_steps', 'max_output_bytes', 'max_log_bytes', 'memory_budget_bytes'}
MAX_INPUT = 65536
MAX_STRUCTURE = 8 * 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def regular(path, maximum=None):
    p = Path(path)
    if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode):
        raise ValueError('Require a regular nonsymlink file: ' + p.name)
    if maximum is not None and p.stat().st_size > maximum:
        raise ValueError('File exceeds byte limit: ' + p.name)
    return p


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode_json(raw):
    def bad(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=bad)


def read_json(path, maximum=MAX_INPUT):
    return decode_json(regular(path, maximum).read_text(encoding='utf-8'))


def atomic_json(path, value):
    target = Path(path)
    payload = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    if len(payload) > 1024 * 1024:
        raise ValueError('Report exceeds 1 MiB')
    temp = target.with_name(target.name + '.tmp')
    with temp.open('xb') as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, target)


def absolute(value, label):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(label + ' must be an explicit absolute path')
    return Path(value).resolve()


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != REQUIRED or spec.get('schema') != SCHEMA:
        raise ValueError('Require exact structure.v1 fields; unknown schemas/fields refused')
    sequence = spec['sequence']
    if (not isinstance(sequence, str) or not 4 <= len(sequence) <= 128 or
            set(sequence) - set(AA3.values()) or spec['chain_id'] != 'A'):
        raise ValueError('Require one chain A of 4–128 uppercase canonical amino acids')
    if spec['device'] != 'cpu':
        raise ValueError('This contract supports CPU only; GPU/MPS real execution remains pending')
    limits = {'seed': (0, 2147483647), 'threads': (1, 8), 'timeout_seconds': (1, 3600),
              'recycling_steps': (1, 3), 'sampling_steps': (1, 200),
              'max_output_bytes': (1024 * 1024, 256 * 1024 * 1024),
              'max_log_bytes': (1024, 4 * 1024 * 1024),
              'memory_budget_bytes': (1024 ** 3, 10 * 1024 ** 3)}
    for name, (lo, hi) in limits.items():
        if type(spec[name]) is not int or not lo <= spec[name] <= hi:
            raise ValueError(name + ' is outside its integer bound')
    paths = {name: absolute(spec[name], name) for name in
             ('python', 'boltz_source', 'assets_dir', 'output_dir')}
    # Preserve a venv launcher path: resolving its symlink before execution would
    # silently select the base interpreter and lose the chosen environment.
    paths['python'] = Path(spec['python'])
    for name in ('boltz_source', 'assets_dir'):
        if not paths[name].is_dir():
            raise ValueError(name + ' must be an existing directory')
        if paths['output_dir'].is_relative_to(paths[name]) or paths[name].is_relative_to(paths['output_dir']):
            raise ValueError('Output must not overlap source or assets')
    regular(paths['python'].resolve())
    if not os.access(paths['python'], os.X_OK):
        raise ValueError('Selected Python is not executable')
    return paths


def git(source, *args):
    completed = subprocess.run(['git', '-C', str(source), *args], capture_output=True, timeout=15)
    if completed.returncode or len(completed.stdout) > 2 * 1024 * 1024:
        raise ValueError('Cannot verify pinned Boltz source checkout')
    return completed.stdout


def verify_source(source):
    """Bind the source tree to a known git commit; reject ignored injected modules too."""
    source = Path(source).resolve()
    if git(source, 'rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('Boltz checkout is not the pinned source revision')
    rows = git(source, 'ls-tree', '-r', '--full-tree', '-z', 'HEAD', '--', 'src/boltz', 'pyproject.toml')
    expected, hashes = set(), {}
    for row in rows.split(b'\0'):
        if not row:
            continue
        head, relative = row.split(b'\t', 1)
        mode, kind, oid = head.decode().split()
        rel = relative.decode(); p = source / rel
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Source contains unsupported git object')
        regular(p, 8 * 1024 * 1024)
        if any(parent.is_symlink() for parent in p.parents if parent != source and parent.is_relative_to(source)):
            raise ValueError('Source directory symlink refused')
        data = p.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != oid:
            raise ValueError('Pinned source content mismatch: ' + rel)
        expected.add(rel); hashes[rel] = hashlib.sha256(data).hexdigest()
    if 'src/boltz/main.py' not in expected or 'pyproject.toml' not in expected:
        raise ValueError('Incomplete pinned source tree')
    actual = {str(p.relative_to(source)) for p in (source / 'src/boltz').rglob('*') if p.is_file() or p.is_symlink()}
    if actual != expected - {'pyproject.toml'}:
        raise ValueError('Untracked/ignored source files or cached bytecode refused')
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {'revision': REVISION, 'file_count': len(hashes), 'tree_sha256': fingerprint,
            'main_sha256': hashes['src/boltz/main.py']}


def verify_assets(directory):
    root = Path(directory).resolve()
    if {p.name for p in root.iterdir()} != set(ASSETS):
        raise ValueError('Assets directory must contain exactly boltz1_conf.ckpt and ccd.pkl')
    result = {}
    total = 0
    for name, expected in ASSETS.items():
        p = regular(root / name, 4 * 1024 ** 3)
        size = p.stat().st_size; total += size
        if size <= 0 or digest(p) != expected:
            raise ValueError('Pinned asset hash mismatch: ' + name)
        result[name] = {'sha256': expected, 'bytes': size}
    if total > 5 * 1024 ** 3:
        raise ValueError('Asset total exceeds fixed 5 GiB budget')
    return result


def cif_tokens(text):
    """Tokenize the constrained text mmCIF syntax without executing CIF content."""
    multiline = None
    for line in text.splitlines():
        if line.startswith(';'):
            if multiline is None:
                multiline = [line[1:]]
            else:
                yield '\n'.join(multiline); multiline = None
            continue
        if multiline is not None:
            multiline.append(line); continue
        lexer = shlex.shlex(line, posix=True); lexer.whitespace_split = True; lexer.commenters = '#'
        yield from lexer
    if multiline is not None:
        raise ValueError('Unterminated CIF multiline field')


def parse_atoms(path):
    text = regular(path, MAX_STRUCTURE).read_text(encoding='utf-8')
    atoms = []
    if Path(path).suffix.lower() == '.pdb':
        models, ended = 0, False
        for line in text.splitlines():
            if line.startswith('MODEL '):
                models += 1
                if models > 1:
                    raise ValueError('Only one structure model accepted')
            if line.startswith('ENDMDL') or line.strip() == 'END':
                ended = True
            if line.startswith(('ATOM  ', 'HETATM')):
                if ended or line.startswith('HETATM') or len(line) < 54 or line[16:17].strip():
                    raise ValueError('Unsupported/truncated PDB atom record')
                if line[26:27].strip():
                    raise ValueError('Insertion codes unsupported')
                atoms.append((line[21:22], int(line[22:26]), line[17:20].strip(), line[12:16].strip(),
                              tuple(float(line[s:s+8]) for s in (30, 38, 46))))
        if not ended:
            raise ValueError('Truncated PDB: terminal END/ENDMDL required')
    elif Path(path).suffix.lower() in ('.cif', '.mmcif'):
        tokens = list(cif_tokens(text)); i = 0
        while i < len(tokens):
            if tokens[i] != 'loop_':
                i += 1; continue
            i += 1; tags = []
            while i < len(tokens) and tokens[i].startswith('_'):
                tags.append(tokens[i]); i += 1
            values = []
            while i < len(tokens) and not (tokens[i] in ('loop_', 'stop_') or tokens[i].startswith(('_', 'data_', 'save_'))):
                values.append(tokens[i]); i += 1
            if not tags or len(values) % len(tags):
                raise ValueError('Truncated/malformed CIF loop')
            if not any(t.startswith('_atom_site.') for t in tags):
                continue
            if len(set(tags)) != len(tags):
                raise ValueError('Duplicate CIF atom columns')
            required = ['group_PDB', 'label_asym_id', 'label_seq_id', 'label_comp_id',
                        'label_atom_id', 'Cartn_x', 'Cartn_y', 'Cartn_z']
            if any('_atom_site.' + k not in tags for k in required):
                raise ValueError('Missing CIF atom identity/coordinate columns')
            for start in range(0, len(values), len(tags)):
                row = dict(zip(tags, values[start:start+len(tags)]))
                get = lambda key, default='?': row.get('_atom_site.' + key, default)
                if (get('group_PDB') != 'ATOM' or get('label_alt_id') not in ('.', '?') or
                        get('pdbx_PDB_ins_code') not in ('.', '?') or get('pdbx_PDB_model_num', '1') != '1'):
                    raise ValueError('Unsupported CIF hetero/alternate/model atom')
                atoms.append((get('label_asym_id'), int(get('label_seq_id')), get('label_comp_id'),
                              get('label_atom_id'), tuple(float(get(k)) for k in ('Cartn_x', 'Cartn_y', 'Cartn_z'))))
    else:
        raise ValueError('Structure must be PDB or mmCIF')
    return atoms


def validate_structure(path, sequence):
    atoms = parse_atoms(path); residues = {}
    if not atoms:
        raise ValueError('Empty structure')
    for chain, index, name, atom, xyz in atoms:
        if chain != 'A' or not 1 <= index <= len(sequence) or name not in AA3 or AA3[name] != sequence[index-1]:
            raise ValueError('Structure chain/residue identity differs from requested sequence')
        if not atom or not all(math.isfinite(x) and abs(x) <= 1e5 for x in xyz):
            raise ValueError('Invalid or nonfinite coordinates')
        row = residues.setdefault(index, {})
        if atom in row:
            raise ValueError('Duplicate atom identity')
        row[atom] = xyz
    if set(residues) != set(range(1, len(sequence)+1)):
        raise ValueError('Missing residue coverage')
    for row in residues.values():
        if not BACKBONE <= set(row):
            raise ValueError('Missing N/CA/C/O backbone atom')
        for a, b, lo, hi in [('N', 'CA', 1.0, 1.9), ('CA', 'C', 1.0, 1.9), ('C', 'O', 0.9, 1.7)]:
            if not lo <= math.dist(row[a], row[b]) <= hi:
                raise ValueError('Implausible backbone bond geometry')
    for index in range(1, len(sequence)):
        if not 1.0 <= math.dist(residues[index]['C'], residues[index+1]['N']) <= 2.0:
            raise ValueError('Disconnected peptide backbone')
    return {'format': Path(path).suffix.lower(), 'chains': ['A'], 'residues': len(residues),
            'atoms': len(atoms), 'backbone_atoms_per_residue': 4, 'backbone_geometry': 'checked',
            'sha256': digest(path), 'sequence_sha256': hashlib.sha256(sequence.encode()).hexdigest()}


def validate_confidence(path):
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError('Confidence must be an object')
    required = ('confidence_score', 'ptm', 'complex_plddt')
    for name in required:
        if type(value.get(name)) not in (float, int) or not math.isfinite(value[name]) or not 0 <= value[name] <= 1:
            raise ValueError('Missing/out-of-range Boltz confidence: ' + name)
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in ('iptm', 'ligand_iptm', 'protein_iptm', 'complex_iplddt'):
                    if type(child) not in (float, int) or not math.isfinite(child) or not 0 <= child <= 1:
                        raise ValueError('Out-of-range optional confidence')
                walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
        elif type(item) is float and not math.isfinite(item):
            raise ValueError('Nonfinite confidence value')
    walk(value)
    return {'sha256': digest(path), 'fields': {name: value[name] for name in required},
            'meaning': 'Model confidence in [0,1], not measured structural accuracy or biological validity'}


def output_size(root):
    total = 0
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Output symlink refused')
        if p.is_file():
            regular(p); total += p.stat().st_size
        elif not p.is_dir():
            raise ValueError('Nonregular output refused')
    return total


def bounded_process(argv, directory, timeout, max_log, max_output, memory_budget, on_start=None):
    """Captured logs are hard-capped; aggregate output is monitored, not disk isolation."""
    if os.name != 'posix':
        raise ValueError('Process-tree bounds require POSIX; other hosts pending')
    import resource
    import psutil
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output, max_output))
    log_path = directory / 'worker.log'; overflow = threading.Event()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1',
           'TRANSFORMERS_OFFLINE': '1', 'WANDB_MODE': 'disabled', 'HF_HUB_DISABLE_TELEMETRY': '1'}
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, preexec_fn=limits, env=env)
    if on_start is not None:
        try: on_start()
        except BaseException:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except PermissionError: proc.kill()
            proc.wait(timeout=5); proc.stdout.close(); raise
    owner = psutil.Process(proc.pid); tracked = {proc.pid: owner}
    def capture():
        written = 0
        with log_path.open('xb') as stream:
            while True:
                raw = proc.stdout.read(65536)
                if not raw: break
                keep = raw[:max(0, max_log-written)]; stream.write(keep); written += len(keep)
                if len(keep) < len(raw): overflow.set()
    thread = threading.Thread(target=capture, daemon=True); thread.start()
    start = time.monotonic(); reason = None; peak_rss = 0; termination_mode='owned_process_group'
    try:
        while True:
            # Status inspection does not reap the child. This also works on
            # Python builds without os.waitid (some macOS distributions).
            if owner.status() == psutil.STATUS_ZOMBIE:
                break
            for child in owner.children(recursive=True): tracked[child.pid] = child
            rss = 0
            for child in list(tracked.values()):
                try:
                    if child.is_running(): rss += child.memory_info().rss
                except psutil.NoSuchProcess: pass
            peak_rss = max(peak_rss, rss)
            if rss > memory_budget: reason = 'memory_limit'; break
            if overflow.is_set(): reason = 'log_limit'; break
            if time.monotonic()-start >= timeout: reason = 'timed_out'; break
            if output_size(directory) > max_output: reason = 'output_limit'; break
            time.sleep(0.05)
    except BaseException:
        reason = 'interrupted'
        raise
    finally:
        # The group is owned by this still-unreaped session leader. Kill descendants
        # even if the leader exited; never reuse a historical PID as kill authority.
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        except PermissionError:
            # Some hosts permit signaling owned PIDs but prohibit killpg.
            # psutil retains creation identity and is_running checks PID reuse.
            termination_mode='tracked_owned_pids'
            for child in reversed(list(tracked.values())):
                try:
                    if child.is_running() and child.status() != psutil.STATUS_ZOMBIE: child.kill()
                except psutil.NoSuchProcess: pass
        proc.wait(timeout=5); thread.join(timeout=5)
        if proc.stdout: proc.stdout.close()
    if thread.is_alive():
        raise RuntimeError('Log capture did not terminate')
    if overflow.is_set(): reason = 'log_limit'
    if output_size(directory) > max_output: reason = 'output_limit'
    return {'returncode': proc.returncode, 'failure_kind': reason,
            'wall_seconds': round(time.monotonic()-start, 3), 'peak_tree_rss_bytes':peak_rss,
            'memory_budget_bytes':memory_budget, 'termination_mode':termination_mode,
            'memory_measurement':'psutil sampled owned process tree; transient peaks may be missed',
            'log_sha256': digest(log_path),
            'log_bytes': log_path.stat().st_size, 'output_bytes': output_size(directory)}


def boltz_argv(request):
    s = request['spec']; root = Path(request['output_dir'])
    return ['predict', str(root/'input.yaml'), '--model', 'boltz1', '--accelerator', 'cpu',
            '--devices', '1', '--cache', request['assets_dir'], '--out_dir', str(root/'engine'),
            '--no_kernels', '--num_workers', '0', '--preprocessing-threads', '1',
            '--recycling_steps', str(s['recycling_steps']), '--sampling_steps', str(s['sampling_steps']),
            '--diffusion_samples', '1', '--seed', str(s['seed']), '--output_format', 'pdb']


def worker(request_path):
    request = read_json(request_path); spec = request['spec']; paths = validate_spec(spec)
    if (set(request) != {'spec', *paths} or
            any(request[name] != str(value) for name, value in paths.items()) or
            Path(request_path).resolve().parent != paths['output_dir']):
        raise ValueError('Internal request paths differ from declared resources')
    expected_input = {'version':1, 'sequences':[{'protein':{
        'id':'A', 'sequence':spec['sequence'], 'msa':'empty'}}]}
    if read_json(paths['output_dir']/'input.yaml') != expected_input:
        raise ValueError('Staged sequence input differs from declared request')
    state = read_json(paths['output_dir']/'report.json')
    # The child may start before the parent has atomically recorded Popen success.
    if (state.get('status') not in ('starting', 'running') or
            state.get('worker_request_sha256') != digest(request_path)):
        raise ValueError('Internal request lacks matching active launch evidence')
    # Guards prevent accidental in-process service or downloader use. They do not
    # turn trusted Python dependencies into an adversarial security sandbox.
    import socket
    def no_network(*args, **kwargs):
        raise RuntimeError('Network disabled by structure adapter')
    socket.socket.connect = no_network; socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    source = Path(request['boltz_source']); source_evidence = verify_source(source)
    asset_evidence = verify_assets(request['assets_dir'])
    sys.dont_write_bytecode = True; sys.path.insert(0, str(source/'src'))
    os.environ.update(OMP_NUM_THREADS=str(spec['threads']), MKL_NUM_THREADS=str(spec['threads']),
                      OPENBLAS_NUM_THREADS=str(spec['threads']), WANDB_MODE='disabled')
    import torch
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError('Pinned Boltz requires Python 3.10–3.12')
    torch.set_num_threads(spec['threads']); torch.set_num_interop_threads(1)
    import boltz.main as main
    from boltz.model.models.boltz1 import Boltz1
    observed = {'forward_calls': 0, 'device': None, 'output_tensor_shapes': []}
    original = Boltz1.forward
    def tensor_list(item):
        if isinstance(item, torch.Tensor): return [item]
        if isinstance(item, dict): return [t for value in item.values() for t in tensor_list(value)]
        if isinstance(item, (list, tuple)): return [t for value in item for t in tensor_list(value)]
        return []
    def forward(self, *args, **kwargs):
        if {str(p.device) for p in self.parameters()} != {'cpu'}:
            raise RuntimeError('Model parameter device differs from required CPU')
        result = original(self, *args, **kwargs)
        tensors = tensor_list(result)
        if not tensors or any(t.device.type != 'cpu' for t in tensors):
            raise RuntimeError('Forward output device evidence unavailable or incorrect')
        observed.update(forward_calls=observed['forward_calls']+1, device='cpu',
                        output_tensor_shapes=[list(t.shape) for t in tensors[:16]])
        return result
    Boltz1.forward = forward
    # Do not invoke the upstream downloader, even with a complete cache.
    main.download_boltz1 = lambda cache: verify_assets(cache)
    main.download_boltz2 = no_network
    runtime_libraries = {}
    for name in ('libtorch_cpu.dylib', 'libtorch_cpu.so'):
        library = Path(torch.__file__).resolve().parent/'lib'/name
        if library.is_file(): runtime_libraries[name] = digest(regular(library, 1024**3))
    if not runtime_libraries:
        raise RuntimeError('CPU runtime library hash could not be recorded')
    receipt = {'source': source_evidence, 'assets': asset_evidence, 'observed': observed,
               'python': platform.python_version(), 'python_sha256': digest(Path(sys.executable).resolve()),
               'torch': torch.__version__, 'platform': platform.platform(), 'model': 'boltz1',
               'runtime_library_sha256':runtime_libraries,
               'versions':{name:importlib.metadata.version(name) for name in
                           ('torch','numpy','pytorch-lightning','rdkit','biopython')},
               'network_policy': 'in-process sockets denied; trusted dependencies, not sandbox'}
    try:
        main.cli.main(args=boltz_argv(request), prog_name='boltz', standalone_mode=False)
        if observed['forward_calls'] < 1:
            raise RuntimeError('No observed Boltz-1 forward workload')
        receipt['completed'] = True
    except BaseException as exc:
        receipt.update(completed=False, error_type=type(exc).__name__, error=str(exc)[:2000])
        raise
    finally:
        atomic_json(Path(request['output_dir'])/'worker-receipt.json', receipt)


def run(spec_path):
    raw = regular(spec_path, MAX_INPUT).read_bytes(); spec = decode_json(raw)
    if not isinstance(spec, dict): raise ValueError('Spec must be an object')
    destination = absolute(spec.get('output_dir'), 'output_dir')
    # Destination guards precede *all* writes, including failure receipts. A
    # diagnostic directory inside the pinned cache would itself corrupt it.
    for name in ('boltz_source', 'assets_dir'):
        protected = absolute(spec.get(name), name)
        if destination.is_relative_to(protected) or protected.is_relative_to(destination):
            raise ValueError('Output must not overlap source or assets')
    if not destination.parent.is_dir(): raise ValueError('Output parent must exist')
    destination.mkdir()  # exclusive reservation: never modify an existing output
    report = {'schema': SCHEMA, 'status': 'preflight', 'accepted': False, 'engine_started': False,
              'actual_runtime_verified': False, 'scientific_accuracy': 'not_evaluated',
              'spec_sha256': hashlib.sha256(raw).hexdigest(), 'model': 'boltz1',
              'source_revision': REVISION, 'model_revision': MODEL_REVISION}
    target = destination/'report.json'; atomic_json(target, report)
    try:
        paths = validate_spec(spec)
        report['source'] = verify_source(paths['boltz_source'])
        report['assets'] = verify_assets(paths['assets_dir'])
        report['python_sha256'] = digest(paths['python'])
        report['sequence_sha256'] = hashlib.sha256(spec['sequence'].encode()).hexdigest()
        report['settings'] = {k: spec[k] for k in ('device','seed','threads','timeout_seconds',
                            'recycling_steps','sampling_steps','max_output_bytes','max_log_bytes','memory_budget_bytes')}
        request = {'spec': spec, **{key: str(value) for key, value in paths.items()}}
        atomic_json(destination/'request.json', request)
        report['worker_request_sha256'] = digest(destination/'request.json')
        # JSON is a strict subset of YAML; no string interpolation in YAML values.
        atomic_json(destination/'input.yaml', {'version':1, 'sequences':[{'protein':{
            'id':'A', 'sequence':spec['sequence'], 'msa':'empty'}}]})
        argv = [str(paths['python']), '-I', '-B', str(Path(__file__).resolve()), '_worker',
                '--request', str(destination/'request.json')]
        report.update(status='starting'); atomic_json(target, report)
        def started():
            report.update(status='running', engine_started=True); atomic_json(target, report)
        execution = bounded_process(argv, destination, spec['timeout_seconds'],
                                    spec['max_log_bytes'], spec['max_output_bytes'], spec['memory_budget_bytes'], started)
        report['execution'] = execution
        if execution['failure_kind'] or execution['returncode']:
            report['failure_kind'] = execution['failure_kind'] or 'child_nonzero'
            raise RuntimeError('Structure worker did not complete successfully')
        receipt = read_json(destination/'worker-receipt.json')
        if (receipt.get('completed') is not True or receipt.get('source') != report['source'] or
                receipt.get('assets') != report['assets'] or receipt.get('python_sha256') != report['python_sha256'] or
                receipt.get('model') != 'boltz1' or receipt.get('observed',{}).get('device') != 'cpu' or
                type(receipt.get('observed',{}).get('forward_calls')) is not int or receipt['observed']['forward_calls'] < 1 or
                not receipt.get('runtime_library_sha256')):
            raise ValueError('Worker provenance or workload evidence mismatch')
        pred = destination/'engine/boltz_results_input/predictions/input'
        report['structure'] = validate_structure(pred/'input_model_0.pdb', spec['sequence'])
        report['confidence'] = validate_confidence(pred/'confidence_input_model_0.json')
        report['workload'] = receipt
        report.update(status='succeeded', accepted=True, actual_runtime_verified=True)
    except BaseException as exc:
        report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else
                      ('partial' if report['engine_started'] else 'failed'), accepted=False,
                      error_type=type(exc).__name__, error=str(exc)[:2000])
        report['actual_runtime_verified'] = False
    finally:
        atomic_json(target, report)
        if report['accepted'] and output_size(destination) > spec['max_output_bytes']:
            report.update(status='partial', accepted=False, actual_runtime_verified=False,
                          failure_kind='output_limit', error='Final retained output exceeds declared byte budget')
            atomic_json(target, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run_parser = sub.add_parser('run'); run_parser.add_argument('--spec', required=True)
    validate = sub.add_parser('validate-output')
    validate.add_argument('--structure', required=True); validate.add_argument('--confidence', required=True)
    validate.add_argument('--sequence', required=True)
    internal = sub.add_parser('_worker', help=argparse.SUPPRESS); internal.add_argument('--request', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == '_worker': worker(args.request); return 0
        if args.command == 'run':
            result = run(args.spec)
        else:
            if not 4 <= len(args.sequence) <= 128 or set(args.sequence)-set(AA3.values()):
                raise ValueError('Canonical sequence length 4–128 required')
            result = {'status':'validated_output_only', 'actual_runtime_verified':False,
                      'scientific_accuracy':'not_evaluated',
                      'structure':validate_structure(args.structure,args.sequence),
                      'confidence':validate_confidence(args.confidence)}
        print(json.dumps(result,allow_nan=False)); return 0 if result.get('status') in ('succeeded','validated_output_only') else 2
    except Exception as exc:
        print(json.dumps({'status':'failed','accepted':False,'actual_runtime_verified':False,
                          'error_type':type(exc).__name__,'error':str(exc)[:2000]}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
