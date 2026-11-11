#!/usr/bin/env python3
"""Run one ELF pair with the measured 2026-11-11 configuration.

Packaging adapter for compiler_wrongcode/run1. It does not read benchmark
labels or known witnesses, compile programs, retry, or change proof rules.
"""
import argparse
import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from binary_identity import build_task_artifact_identity
from input_domain_contract import build_contract, load_profile, schema_from_signature

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, payload):
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


def limited_process(command, directory, stem, timeout, memory_gib):
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (memory_gib * 1024**3,) * 2)
    start = time.monotonic()
    with (directory / (stem + '.stdout.txt')).open('w') as out, \
            (directory / (stem + '.stderr.txt')).open('w') as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err,
                                   start_new_session=True, preexec_fn=limits)
        try:
            code = process.wait(timeout=timeout)
            status = 'completed' if code == 0 else 'error'
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
            status = 'timeout'
    result = dict(command=command, status=status, returncode=code,
                  seconds=time.monotonic() - start, memory_gib=memory_gib,
                  outer_timeout_seconds=timeout)
    write(directory / (stem + '.process.json'), result)
    if status != 'completed':
        raise RuntimeError(f'{stem}: {status}; see {directory}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for side in ('old', 'new'):
        parser.add_argument(f'--{side}-binary', type=Path, required=True)
        parser.add_argument(f'--{side}-source', type=Path, required=True)
        parser.add_argument(f'--{side}-compiler', required=True,
                            help='Actual compiler/version and build flags, recorded verbatim.')
    parser.add_argument('--signature', required=True, help='For example: int(int)')
    parser.add_argument('--domain-profile-json', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True, help='Must not exist.')
    parser.add_argument('--pair-id', default='binary_pair')
    args = parser.parse_args()
    profile = load_profile(args.domain_profile_json.resolve())
    schema = schema_from_signature(args.signature)
    sources = {side: getattr(args, side + '_source').resolve() for side in ('old', 'new')}
    binaries = {side: getattr(args, side + '_binary').resolve() for side in ('old', 'new')}
    for path in [*sources.values(), *binaries.values()]:
        if not path.is_file():
            parser.error(f'Missing file: {path}')
    attempt = args.out_dir.resolve()
    attempt.mkdir(parents=True, exist_ok=False)
    paths = attempt / 'paths'
    paths.mkdir()
    profile_path = attempt / 'domain_profile.json'
    contract_path = attempt / 'input_contract.json'
    write(profile_path, profile)
    write(contract_path, build_contract(schema, profile=profile, pair_id=args.pair_id,
                                       source=str(sources['old'])))
    build = {'task_uid': args.pair_id, 'build_status': 'completed',
             'compiler_profile': f'{args.old_compiler} versus {args.new_compiler}',
             'optimization': 'See explicit compiler/build descriptions',
             'artifact_origin': 'caller_supplied_prebuilt_ELFs'}
    se_rows = []
    method = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'scripts').glob('*.py')}
    write(attempt / 'method.json', method)
    for side in ('old', 'new'):
        binary = attempt / f'symbolic_{side}V'
        shutil.copy2(binaries[side], binary)
        binary.chmod(0o755)
        build.update({f'expected_{side}_binary': str(binary), f'{side}_binary': str(binary),
                      f'{side}_binary_sha256': sha(binary), f'{side}_source': str(sources[side]),
                      f'{side}_source_sha256': sha(sources[side])})
        se_rows.append(dict(task_uid=args.pair_id, side=side, binary=str(binary),
                            source=str(sources[side]), paths_dir=str(paths)))
        limited_process([
            sys.executable, str(ROOT / 'scripts/se_script_improved.py'),
            '--binary', str(binary), '--signature', args.signature,
            '--output-prefix', str(paths / f'symbolic_{side}V'),
            '--timeout', '60', '--loop-bound', '30', '--max-paths', '128',
            '--domain-profile-json', str(profile_path), '--input-schema-json', json.dumps(schema),
            '--fixed-math-runtime', '--initialized-entry', '--model-query-timeout-ms', '500',
        ], attempt, 'se_' + side, 75, 5)
    identity = build_task_artifact_identity(
        run_root=attempt, project_root=ROOT, build_row=build, se_rows=se_rows,
        contract_path=contract_path, profile_path=profile_path,
        expected_profile_id=profile['profile_id'])
    identity_path = attempt / 'artifact_identity.json'
    write(identity_path, identity)
    write(attempt / 'build_manifest.json', build)
    report = attempt / 'verification_report.json'
    limited_process([
        sys.executable, str(ROOT / 'scripts/verify_ranked_path_equivalence.py'),
        '--paths-dir', str(paths), '--out', str(report), '--pair-id', args.pair_id,
        '--attempt-uid', attempt.name + ':' + args.pair_id,
        '--entry-signature', args.signature, '--input-schema-json', json.dumps(schema),
        '--domain-profile-json', str(profile_path),
        '--artifact-identity-json', str(identity_path), '--require-artifact-identity',
        '--old-binary', str(attempt / 'symbolic_oldV'),
        '--new-binary', str(attempt / 'symbolic_newV'),
        '--solver-strategy', 'B10Z50', '--timeout-ms', '5000',
        '--static-only', '--naive', '--smt-audit-all-queries',
    ], attempt, 'verifier', 120, 4)
    if any(sha(ROOT / p) != digest for p, digest in method.items()):
        raise RuntimeError('Method changed during execution')
    result = json.loads(report.read_text())
    print(json.dumps({'verdict': result['verdict'], 'report': str(report)}))


if __name__ == '__main__':
    main()
