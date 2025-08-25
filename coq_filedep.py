import subprocess
from pathlib import Path
from typing import Optional


def run_coqdep(
    coqproject_filepath: Path,
    out_name: Optional[str] = None,
) -> Path:
    """
    Run coqdep on the given project (with coqproject_filepath) and return the
    generated .dot file.
    """
    parent_dir = coqproject_filepath.parent

    if out_name is None:
        out_name = parent_dir.name + '.dot'

    if not out_name.endswith('.dot'):
        out_name = out_name + '.dot'

    cmd = ['coqdep', '-f', coqproject_filepath.name, '-dumpgraph', out_name]

    proc = subprocess.run(
        cmd,
        text=True,
        cwd=parent_dir,
        stdout=subprocess.PIPE
    )

    created_file = parent_dir / out_name
    if not created_file.exists():
        raise RuntimeError(f"coqdep failed: {proc.stderr}")
    return created_file
