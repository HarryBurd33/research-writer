#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded ESM-2 representations. Only prepare-model --allow-download uses HTTP."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

MODEL = 'facebook/esm2_t6_8M_UR50D'
REVISION = 'c731040fcd8d73dceaa04b0a8e6329b345b0f5df'
FILES = {
 'model.safetensors': (31384292, '24c5fa474c48f3b754b86efe752d5f189d2bcd88190fa2270fc92b2ef3034189'),
 'config.json': (775, 'facb9355e8252149f6f99dff5fd1e32e890c3c655362b261d0c81cd6b5839c85'),
 'tokenizer_config.json': (95, '7e9161ecdb548ec45a41cbc6b24aa4476fdd418461f491c4207baa99419a29ad'),
 'special_tokens_map.json': (125, '3aedcd4211c0d43aec4e607ff60a63255f3174ead795e997350f09a5f8cd9ee1'),
 'vocab.txt': (93, '0b82cc0a7c7cf9e567b1e5892d793285b9fbae822c964ca48696f7db44598e03'),
 'README.md': (1705, '462a2f24724e19c6be0efab926315c294a863c9a9770e2c8b3d859b2d81a07de')}
MAX_BYTES = 1024 * 1024
AA = set('ACDEFGHIKLMNPQRSTVWY')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_small(path):
    with Path(path).open('rb') as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Input/report exceeds 1 MiB')
    return data


def write_new(path, value):
    payload = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    if len(payload) > MAX_BYTES:
        raise ValueError('Output exceeds 1 MiB')
    with Path(path).open('xb') as f:
        f.write(payload)


def fasta(raw):
    text = raw.decode('utf-8')
    records, name, seq, seen = [], None, [], set()
    def finish():
        if name is None:
            return
        sequence = ''.join(seq)
        if not 1 <= len(sequence) <= 512 or set(sequence) - AA:
            raise ValueError('Require 1–512 uppercase canonical amino acids; no truncation or residue mapping')
        records.append({'id': name, 'sequence': sequence, 'sequence_sha256': sha(sequence.encode())})
        if len(records) > 16:
            raise ValueError('At most 16 sequences per run')
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith('>'):
            finish()
            name = line[1:].strip()
            if not name or name in seen or len(name) > 256:
                raise ValueError('FASTA IDs must be unique, nonempty and <=256 characters')
            seen.add(name); seq = []
        else:
            if name is None:
                raise ValueError('Sequence before FASTA header')
            seq.append(line.strip())
    finish()
    if not records:
        raise ValueError('No sequences')
    return records


def verify_model(directory):
    root = Path(directory).resolve()
    if not root.is_dir() or {p.name for p in root.iterdir()} != set(FILES):
        raise ValueError('Model directory must contain exactly the six pinned assets; no unverified sidecars')
    for name, (size, expected) in FILES.items():
        p = root / name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root) or p.stat().st_size != size:
            raise ValueError('Missing, escaping or wrong-sized pinned model asset: ' + name)
        if sha(p.read_bytes()) != expected:
            raise ValueError('Model asset hash mismatch: ' + name)
    config = json.loads((root / 'config.json').read_text())
    if config.get('hidden_size') != 320 or config.get('num_hidden_layers') != 6 or config.get('model_type') != 'esm':
        raise ValueError('Unsupported model architecture')
    return root


def allowed_download(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    return p.scheme == 'https' and not p.username and not p.password and p.port in (None, 443) and (
        host == 'huggingface.co' or host.endswith('.huggingface.co') or host.endswith('.hf.co'))


class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_download(newurl):
            raise ValueError('Model redirect outside approved HTTPS model hosts')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def prepare_model(directory, allow_download):
    if not allow_download:
        raise ValueError('Explicit --allow-download is required; about 31.4 MB from the pinned public model')
    target = Path(directory)
    if target.exists():
        raise FileExistsError('Model directory exists; preserve it or choose another path')
    if not target.parent.is_dir():
        raise ValueError('Model parent directory must exist')
    with tempfile.TemporaryDirectory(prefix='.esm-download-', dir=target.parent) as temp:
        staged = Path(temp) / 'model'; staged.mkdir()
        opener = urllib.request.build_opener(DownloadRedirect())
        for name, (size, expected) in FILES.items():
            url = 'https://huggingface.co/' + MODEL + '/resolve/' + REVISION + '/' + name
            request = urllib.request.Request(url, headers={'User-Agent': 'research-writer-protein-tools/0.7.0'})
            with opener.open(request, timeout=30) as response:
                raw = response.read(size + 1)
            if len(raw) != size or sha(raw) != expected:
                raise ValueError('Downloaded asset identity mismatch: ' + name)
            (staged / name).write_bytes(raw)
        verify_model(staged)
        # Reservation is exclusive; a competing target is never replaced.
        target.mkdir()
        try:
            for name in FILES:
                shutil.copyfile(staged / name, target / name)
        except BaseException:
            shutil.rmtree(target)
            raise
    return {'status': 'prepared', 'model': MODEL, 'revision': REVISION,
            'directory': str(target.resolve()), 'downloaded_bytes': sum(x[0] for x in FILES.values()),
            'license': 'MIT model card; package/dependency terms separate', 'inference_executed': False}


def select_device(torch, requested):
    if requested in ('auto', 'cpu'):
        return 'cpu'
    if requested == 'cuda' and torch.cuda.is_available() and not getattr(torch.version, 'hip', None):
        return 'cuda'
    if requested == 'mps' and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return 'mps'
    raise ValueError('Requested accelerator is unavailable or unsupported; no silent fallback: ' + requested)


def compute(request):
    records = request.get('records')
    if (not isinstance(records, list) or not 1 <= len(records) <= 16 or
            type(request.get('threads')) is not int or not 1 <= request['threads'] <= 8 or
            request.get('device') not in ('auto', 'cpu', 'cuda', 'mps')):
        raise ValueError('Invalid bounded worker request')
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid worker sequence record')
        name, sequence = record.get('id'), record.get('sequence')
        if (not isinstance(name, str) or not name.strip() or len(name) > 256 or name in ids or
                not isinstance(sequence, str) or not 1 <= len(sequence) <= 512 or set(sequence) - AA or
                record.get('sequence_sha256') != sha(sequence.encode())):
            raise ValueError('Invalid worker sequence identity/length/chemistry')
        ids.add(name)
    # No remote resolution, custom model code, pickle weights or implicit token.
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    root = verify_model(request['model_dir'])
    import torch
    import transformers
    from transformers import EsmModel, EsmTokenizer
    torch.set_num_threads(request['threads'])
    device = select_device(torch, request['device'])
    tokenizer = EsmTokenizer.from_pretrained(str(root), local_files_only=True, token=False)
    model = EsmModel.from_pretrained(str(root), local_files_only=True, token=False,
                                    use_safetensors=True, trust_remote_code=False, add_pooling_layer=False)
    model.eval(); model.to(device)
    records = []
    with torch.inference_mode():
        for source in request['records']:
            sequence = source['sequence']
            encoded = tokenizer(sequence, return_tensors='pt', truncation=False)
            if encoded['input_ids'].shape[1] != len(sequence) + 2:
                raise ValueError('Tokenizer did not preserve one token per canonical residue plus BOS/EOS')
            encoded = {k: v.to(device) for k, v in encoded.items()}
            states = model(**encoded).last_hidden_state
            pooled = states[0, 1:len(sequence)+1].mean(dim=0).detach().cpu().tolist()
            if len(pooled) != 320 or not all(math.isfinite(x) for x in pooled):
                raise ValueError('Embedding must have 320 finite values')
            records.append({'id': source['id'], 'length': len(sequence),
                            'sequence_sha256': source['sequence_sha256'], 'embedding': pooled})
    return {'records': records, 'dimension': 320, 'device': device,
            'versions': {'python': platform.python_version(), 'torch': torch.__version__,
                         'transformers': transformers.__version__},
            'pooling': 'last hidden layer mean over residues, excluding BOS/EOS; no truncation'}


def validate_result(result, sources):
    records = result.get('records')
    if not isinstance(records, list) or len(records) != len(sources):
        raise ValueError('Worker output count mismatch')
    for actual, expected in zip(records, sources):
        values = actual.get('embedding')
        if any(actual.get(k) != expected[k] for k in ('id', 'sequence_sha256')) or actual.get('length') != len(expected['sequence']):
            raise ValueError('Worker output identity mismatch')
        if not isinstance(values, list) or len(values) != 320 or not all(type(v) in (int, float) and math.isfinite(v) for v in values):
            raise ValueError('Malformed or nonfinite embedding')
    if result.get('device') not in ('cpu', 'cuda', 'mps'):
        raise ValueError('Unknown observed device')


def run_worker(command, directory, timeout):
    log_path, result_path = directory / 'worker.log', directory / 'result.json'
    with log_path.open('xb') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log,
                                env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                                     'HF_HUB_DISABLE_TELEMETRY': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                if log_path.stat().st_size > MAX_BYTES or result_path.exists() and result_path.stat().st_size > MAX_BYTES:
                    raise ValueError('Inference worker exceeded output/log size limit')
                time.sleep(0.05)
            if log_path.stat().st_size > MAX_BYTES:
                raise ValueError('Inference worker exceeded log size limit')
            return proc.returncode
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def embed(args):
    if not 1 <= args.timeout <= 120 or not 1 <= args.threads <= 8:
        raise ValueError('Timeout must be 1–120 seconds and threads 1–8')
    outputs = [Path(args.output), Path(args.embedding_output)]
    if outputs[0].resolve() == outputs[1].resolve() or any(p.exists() for p in outputs):
        raise FileExistsError('Choose distinct new report and embedding paths; existing output is preserved')
    raw = read_small(args.input); sources = fasta(raw)
    root = verify_model(args.model_dir)
    request = {'records': sources, 'model_dir': str(root), 'device': args.device, 'threads': args.threads}
    with tempfile.TemporaryDirectory(prefix='esm-embedding-') as temp:
        directory = Path(temp); inp = directory/'request.json'; out = directory/'result.json'
        write_new(inp, request)
        returncode = run_worker([sys.executable, str(Path(__file__).resolve()), '_worker',
                                 '--request', str(inp), '--result', str(out)], directory, args.timeout)
        if returncode:
            detail = (directory/'worker.log').read_bytes()[-3000:].decode('utf-8', errors='replace')
            raise RuntimeError('Inference worker failed: ' + detail)
        result = json.loads(read_small(out)); validate_result(result, sources)
    write_new(args.embedding_output, result)
    artifact = Path(args.embedding_output)
    return {'status': 'computed', 'model': MODEL, 'revision': REVISION,
            'model_weights_sha256': FILES['model.safetensors'][1], 'input_sha256': sha(raw),
            'artifact': {'path': str(artifact.resolve()), 'sha256': sha(artifact.read_bytes())},
            'device_requested': args.device, 'device': result['device'], 'versions': result['versions'],
            'platform': platform.platform(), 'sequences': len(sources), 'dimension': 320,
            'pooling': result['pooling'], 'timeout_seconds': args.timeout, 'threads': args.threads,
            'scientific_validation': 'not_performed',
            'interpretation': 'Protein sequence representation only; not folding, affinity, function or noncanonical chemistry validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare-model')
    prepare.add_argument('--directory', required=True)
    prepare.add_argument('--allow-download', action='store_true')
    run = sub.add_parser('embed')
    for name in ('input', 'model-dir', 'output', 'embedding-output'):
        run.add_argument('--'+name, required=True)
    run.add_argument('--device', choices=('auto','cpu','cuda','mps'), default='cpu')
    run.add_argument('--threads', type=int, default=1)
    run.add_argument('--timeout', type=int, default=60)
    worker = sub.add_parser('_worker', help=argparse.SUPPRESS)
    worker.add_argument('--request', required=True); worker.add_argument('--result', required=True)
    args = parser.parse_args()
    try:
        if args.command == '_worker':
            write_new(args.result, compute(json.loads(read_small(args.request))))
            return 0
        result = prepare_model(args.directory, args.allow_download) if args.command == 'prepare-model' else embed(args)
        if args.command == 'embed':
            write_new(args.output, result)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (Exception,) as exc:
        failure = {'status': 'failed', 'executed_successfully': False, 'error': str(exc), 'error_type': type(exc).__name__}
        if args.command == 'embed' and not Path(args.output).exists():
            try: write_new(args.output, failure)
            except OSError: pass
        print(json.dumps(failure), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
