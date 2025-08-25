from pathlib import Path
import subprocess
from typing import Optional
import sexpdata


def _read_sertop_response(proc: subprocess.Popen) -> Optional[str]:
    """Reads from sertop until it encounters null byte"""
    if proc.stdout is None:
        raise RuntimeError("sertop produced no stdout")

    response_str = ''
    while True:
        char = proc.stdout.read(1)
        if char == '\0':
            break
        if not char:
            return None
        response_str += char
    return response_str


def parse_sertop_responses(proc: subprocess.Popen):
    """Parse all responses from sertop until encountering 'Completed'."""
    responses = []
    while True:
        response_str = _read_sertop_response(proc)

        if response_str is None:
            break

        response_sexpdata = sexpdata.loads(response_str)
        if isinstance(response_sexpdata, list) and len(response_sexpdata) > 2:
            if response_sexpdata[2] == sexpdata.Symbol('Completed') or response_sexpdata[0] == sexpdata.Symbol('Of_sexp_error'):
                break

        responses.append(sexpdata.loads(response_str))
    return responses


def coq_version() -> str:
    """Returns the current coqtop version."""
    proc = subprocess.run(
        ['coqtop', '-v'],
        stdout=subprocess.PIPE,
    )
    if not proc.stdout:
        from sys import exit
        print('Coqtop not found')
        exit(1)
    return proc.stdout.decode().split('version')[1].split()[0]
