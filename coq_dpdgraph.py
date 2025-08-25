import subprocess
import shutil
from pathlib import Path
from typing import Optional
import textwrap
from coq_modules import _qmap_from_coqc_opts, to_coq_module


def run_coq_dpdgraph(
    coqc_opts: list[str],
    coqproject_filepath: Path,
    coq_file_relative_to_coqproject_path: Path,
    out_name: Optional[str] = None,
) -> Path:
    """
    Generate a dpdgraph file (.dpd) for `coq_file_relative_to_coqproject_path`.

    Returns the absolute path to the .dpd file.
    """
    if out_name is None:
        out_name = coq_file_relative_to_coqproject_path.name.split('.')[
            0] + '.dpd'

    if not out_name.endswith('.dpd'):
        out_name = out_name + '.dpd'

    coqproject_dir = coqproject_filepath.parent

    qmap = _qmap_from_coqc_opts(coqc_opts, coqproject_dir)

    mod_name = to_coq_module(
        coq_file_relative_to_coqproject_path,
        qmap,
        coqproject_dir
    )

    coq_script = textwrap.dedent(f"""\
        Require dpdgraph.dpdgraph.
        Require {mod_name}.

        Set DependGraph File "{out_name}".
        Print FileDependGraph {mod_name}.
    """)

    cmd = ['coqtop', *coqc_opts]

    proc = subprocess.run(
        cmd,
        input=coq_script,
        text=True,
        cwd=coqproject_dir,
        capture_output=True,
    )

    # Dont do this, warnings may pop up.
    # Checking by exit code is not good either, doesn't work
    # if proc.stderr != '':
    #     raise RuntimeError(f"coqtop execution failed: {proc.stderr}")
    created_file = coqproject_dir / out_name
    if not created_file.exists():
        raise RuntimeError(f"coqtop failed: {proc.stderr}")
    return created_file


def dpd_to_dot(
    dpd_filepath: Path,
    output: Optional[Path] = None,
) -> Path:
    """
    Convert `dpd_filepath` (that is .dpd) into a .dot file.
    Return the new dot file location.
    """
    dpd_filepath = Path(dpd_filepath)
    if not shutil.which("dpd2dot"):
        raise FileNotFoundError("`dpd2dot` not found in $PATH")

    if output is None:
        output = dpd_filepath.with_suffix(".dot")

    # There is a bug with the dotfile generation.
    # Having paths in the dot file such as `digraph /home/path/filename'
    # is not valid, but dpd to dot produces such files.
    # To fix that, one workaround is to directly execute this command from
    # the directory where the dot file is.
    parent_dir = dpd_filepath.parent
    file_name = dpd_filepath.name
    # '-keep-trans' -> add transitive deps. as well
    cmd = ['dpd2dot', '-o', output, file_name]

    result = subprocess.run(
        cmd,
        check=True,
        cwd=parent_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if not Path(output).exists():
        raise RuntimeError(
            f"dpd2dot failed: {result.stdout}, stderr:{result.stderr}\n"
        )
    return output


def dot_to_svg(
    dot_filepath: Path,
    output: Optional[Path] = None,
) -> Path:
    """
    Convert `dot_filepath` (that is .dot) into a .svg file.
    Return the new svg file location.
    """
    dot_filepath = Path(dot_filepath)
    if not shutil.which("dot"):
        raise FileNotFoundError("Graphviz `dot` not found in $PATH")

    if output is None:
        output = dot_filepath.with_suffix(".svg")

    cmd = ["dot", "-Tsvg", str(dot_filepath), "-o", str(output)]

    subprocess.run(cmd, check=True)
    return output
