from __future__ import annotations
import os
from pathlib import Path
import subprocess
from typing import Literal
import sexpdata

from serapi import parse_sertop_responses

def _qmap_from_coqc_opts(
    opts: list[str],
    relative_project_dir: Path
) -> list[tuple[Path, str]]:
    """
    Turns something like ['-Q', 'base', "map"]
    into a tuple: [(Path(base), Path(map))]
    """
    qmap: list[tuple[Path, str]] = []
    i = 0
    while i < len(opts):
        tag = opts[i]
        if tag in {'-Q', '-R'}:
            if i + 2 >= len(opts):
                raise ValueError(
                    f"Expected two more args after {tag}, got {opts[i + 1:]}")
            phys = opts[i + 1]
            log = opts[i + 2]
            qmap.append(((relative_project_dir/phys), log))
            i += 3
        else:
            # This is just to skip anything else that is invalid that's not -Q or -R
            i += 1
    return qmap

def parse_coq_project_file(
        coq_project_file_path: Path,
        separation_mode: Literal['sercomp', 'coqtop']
) -> list[str]:
    """
    Parse the _CoqProject file (given by coq_project_file_path) and return the list
    of -Q/-R mappings as a command arg.
    """
    args: list[str] = []
    with open(coq_project_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('-Q') or line.startswith('-R'):
                tag, physical, logical = line.split()
                args.append(tag)

                if separation_mode == 'coqtop':
                    ns = '' if logical == '""' else logical
                    args.append(physical)
                    args.append(ns)
                else:
                    lg = '' if logical == '""' else logical
                    args.append(f"{physical},{lg}")
    return args

class CoqModuleResolver:
    # sertop: subprocess.Popen
    project_dir: Path
    cache: dict[str, Path]
    sertop_args: list[str]
    coqc_args: list[str]
    external_maps: dict[str, str]

    def __init__(
        self,
        sertop_args: list[str],
        coqc_args: list[str],
        project_dir: Path,
    ):
        self.sertop_args = sertop_args
        self.project_dir = _norm(project_dir)
        self.sertop_args = sertop_args
        self.coqc_args = coqc_args
        self.cache = {}

    def coq_module_to_path(
        self,
        module_name: str,
        sertop: subprocess.Popen | None = None,
        extern_maps: dict[str, str] = dict()
    ) -> Path | None:
        """
        Inverse of `to_coq_module`.

        Similarly raises a ValueError if module is not covered by any -Q/-R mapping.

        Here, the trick is to 'Add' the 'Require' import to sertop, from which
        we can extract the absolute location using the feedback response.
        """
        # Why? There could be multiple dots at the end.
        module_name = module_name.rstrip('.') + '.'

        if module_name in self.cache:
            return self.cache[module_name]
        
        if module_name in extern_maps:
            module_name = extern_maps[module_name]

        # We used not to spawn a new sertop instance for each call to this method.
        # But, it turned out to be unreliable, and especially bad as conflicts happened.
        # This is slower, but it's more reliable.
        cmd = ['sertop', *self.sertop_args,
               '--implicit', '--omit_loc', '--print0']

        created_sertop = sertop is None
        if sertop is None:
            sertop = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.project_dir,
                bufsize=1,
            )

        if sertop.stdout is None or sertop.stdin is None:
            raise RuntimeError("sertop produced no stdout or stdin")

        try:
            # Empty add so that we don't have to bother with
            # parsing initial feedbacks
            add_cmd = sexpdata.dumps(['Add', [], ''])
            sertop.stdin.write(add_cmd + '\n')
            sertop.stdin.flush()
            _ = parse_sertop_responses(sertop)

            add_lib_cmd = sexpdata.dumps(['Add', [], f'Require {module_name}'])
            sertop.stdin.write(add_lib_cmd + '\n')
            sertop.stdin.flush()

            add_lib_responses = parse_sertop_responses(sertop)

            try:
                path_to_vo = add_lib_responses[3][1][3][1][2]
            except:
                q_mappings = _qmap_from_coqc_opts(self.coqc_args, self.project_dir)
                old_impl = self.trace_implementation(
                    module_name,
                    q_mappings,
                )
                if old_impl is not None:
                    if '.opam' in old_impl.parts and 'user-contrib' not in old_impl.parts:
                        return None
                    self.cache[module_name] = old_impl
                    return old_impl

                if module_name != 'Coq.':
                    print('Could not resolve module:', module_name)
                return None

            if not isinstance(path_to_vo, str):
                # Check is done by .exists(), so this is safe to do.
                one_module_up = '.'.join(module_name.split('.')[:-2])
                if one_module_up == '':
                    q_mappings = _qmap_from_coqc_opts(self.coqc_args, self.project_dir)
                    old_impl = self.trace_implementation(
                        module_name,
                        q_mappings,
                    )
                    if old_impl is not None:
                        print('Attempted to recover:', module_name, '-->', old_impl)
                        self.cache[module_name] = old_impl
                        return old_impl
                    if module_name != 'Coq.':
                        # print(path_to_vo)
                        # print(add_lib_responses)
                        # from sys import exit
                        # exit(1)
                        print('Could not resolve module:', module_name)
                    return None
                return self.coq_module_to_path(one_module_up, extern_maps=extern_maps)

            have_path = Path(path_to_vo).with_suffix('.v')
            result = Path(os.path.relpath(have_path, _norm(self.project_dir)))

            self.cache[module_name] = result

            if sertop.stdin is not None:
                sertop.stdin.close()
                sertop.terminate()
                sertop.wait(timeout=5)

            # We return None for coq standard library files
            if '.opam' in result.parts and 'user-contrib' not in result.parts:
                return None
            return result
        finally:
            if created_sertop and sertop.stdin is not None:
                sertop.stdin.close()
                sertop.terminate()
                sertop.wait(timeout=5)


    # ORIGINAL IMPLEMENTATION for coq_module_to_path:
    def trace_implementation(self, module_name: str, q_mappings: list[tuple[Path, str]]) -> Path | None:
        mod_parts = module_name.split(".")
        best_match = None

        # module_name = module_name.rstrip('.')
        # mod_parts = module_name.split(".") if module_name else []

        best_match = None

        for phys_dir, logical in q_mappings:
            logical_clean = logical.strip('"').strip().rstrip(".")
            if logical_clean in ("", "."):
                prefix_len = 0
                matches = True
            else:
                logical_parts = logical_clean.split(".")
                matches = mod_parts[:len(logical_parts)] == logical_parts
                prefix_len = len(logical_parts)

            if matches:
                if best_match is None or prefix_len > best_match[0]:
                    best_match = (prefix_len, phys_dir, logical_clean)

        if best_match is None:
            # raise ValueError(f"Module '{module_name}' is not covered by any -Q/-R mapping")
            return None

        prefix_len, phys_dir, logical_clean = best_match

        rel_mod_parts = mod_parts[prefix_len:] if logical_clean not in (
            '', '.') else mod_parts

        if not rel_mod_parts or rel_mod_parts == ['']:
            abs_path = _norm(phys_dir)
            if abs_path.is_dir():
                # If a directory --> remove mapping and look back again
                new_mappings = q_mappings.copy()
                new_mappings.remove((phys_dir, logical_clean))
                # print(f'{module_name} --> {coq_module_to_path(module_name, new_mappings, project_dir)}')
                return self.trace_implementation(module_name, new_mappings)
            # print(f'{module_name} --> {Path(os.path.relpath(abs_path, _norm(project_dir)))}')
            return Path(os.path.relpath(abs_path, _norm(self.project_dir)))

        # This could be refactored better, it's here because it's useful for debugging.
        # Last as file = If something like Hello.Xyz.Abc is given,
        # if last_as_file is True then we're looking at the file Abc.v, otherwise
        # we are looking at the import 'abc' from Hello.Xyz.
        last_as_file = False
        if rel_mod_parts:
            potential_file = _norm(phys_dir) / Path(*rel_mod_parts).with_suffix('.v')
            if potential_file.exists():
                last_as_file = True

        if not last_as_file and len(rel_mod_parts) > 0:
            rel_mod_parts = rel_mod_parts[:-1]

        rel_path = Path(*rel_mod_parts).with_suffix('.v')

        abs_path = _norm(phys_dir) / rel_path

        result = _norm(abs_path)
        if result.exists() and result.is_file():
            return Path(os.path.relpath(abs_path, _norm(self.project_dir)))
        else:
            def search_in_dir(dir: Path) -> Path | None:
                for child in dir.iterdir():
                    if child.is_file() and child.name == rel_path.name:
                        return Path(os.path.relpath(child, _norm(self.project_dir)))
                    elif child.is_dir():
                        possible_result = search_in_dir(child)
                        if possible_result is not None:
                            return possible_result

            curr_dir = result if result.is_dir() else result.parent
            return search_in_dir(curr_dir)


def _norm(p: Path) -> Path:
    """Returns a syntactic-only absolute path.
    Only collapses .. / . etc, does not resolve symlinks.

    This is needed because of Symlinks. If there are mappings to Symlinks
    in _CoqProject then things break when we call .resolve() on the path.
    Calling .absolute() on the path does not properly collapse .. / . either.
    """
    return Path(os.path.abspath(p))


def to_coq_module(
    coq_file_relative_to_coqproject_path: Path,
    q_mappings: list[tuple[Path, str]],
    project_dir: Path,
) -> str:
    """
    Converts a path of some Coq file (that is given relative to the _CoqProject directory)
    into a Coq module name, respecting -Q/-R in _CoqProject.

    Handles symlinks properly. Raises ValueError if the mapping is missing.
    """
    # print(f'coq_file_relative_to_coqproject_path={coq_file_relative_to_coqproject_path}')
    # print(f'q_mappings={q_mappings}')
    # print(f'project_dir={project_dir}')
    file_abs = _norm(project_dir / coq_file_relative_to_coqproject_path)

    best_match = None
    for phys_dir, logical in q_mappings:
        try:
            rel = file_abs.relative_to(phys_dir.resolve())
        except ValueError:
            continue

        if best_match is None or len(str(phys_dir)) > len(str(best_match[0])):
            best_match = (phys_dir, logical, rel)

    if best_match is None:
        raise ValueError(
            f"{coq_file_relative_to_coqproject_path} is not covered by any -Q/-R mapping"
        )

    _, logical_prefix, rel = best_match
    rel_mod = ".".join(rel.with_suffix("").parts)

    logical_prefix = logical_prefix.strip('"').strip()
    if logical_prefix in ("", "."):
        return rel_mod
    return f"{logical_prefix.rstrip('.')}.{rel_mod}"


def run_coq_makefile(
    coq_project_file_path: Path,
) -> Path:
    """
    Runs coq_makefile to generate a Makefile for the given Coq file.
    Return the Makefile path.
    """
    coqproject_dir = coq_project_file_path.parent

    cmd = ['coq_makefile', '-f', coq_project_file_path.name, '-o', 'Makefile']

    proc = subprocess.run(
        cmd,
        check=True,
        text=True,
        cwd=coqproject_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    makefile = coqproject_dir / 'Makefile'
    if not makefile.exists():
        raise RuntimeError(
            f'Makefile was not created: stdout={proc.stdout.strip()} stderr={proc.stderr.strip()}')

    return makefile
