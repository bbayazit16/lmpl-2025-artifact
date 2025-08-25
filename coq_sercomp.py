import re
from typing import Any
import sexpdata
from pathlib import Path
import subprocess
import shutil
import sys

DPDGRAPH_INCLUDE_REGEX = re.compile(
    r"""^\s*
        (?:Program\s+)?
        (?:Local\s+)?
        (?:Definition|Fixpoint|Lemma|Theorem|Remark|Fact|Corollary|
           Proposition|Inductive|Record|Class|Instance|Axiom|
           Program(?:\s+\w+)*|
        #  Ltac|Tactic\s+Notation|Hint(?:\s+\w+)*|
           Add\s+Parametric\s+Relation)
        # \b\s+([^\s(:]+)
        \b\s+([^\s({:]+)
    """, re.X | re.S,
)

NOTATION_RE = re.compile(
    r"""^\s*
        (?:Notation|Infix|Prefix|Declare\s+Custom\s+Entry)
        \s+
        # (["'`][^"'`]+["'`]|[^\s:]+)?                       
        .*                                      
    """, re.X | re.S,
)

PROOF_TERMINATION_RE = re.compile(r'\b(Qed|Defined|Admitted|Abort)\s*\.')


def collect_qualids(node) -> set[str]:
    """
    Returns a list of qualids in the node.
    """
    out: set[str] = set()
    if (isinstance(node, list)
            and len(node) == 3
            and node[0] == sexpdata.Symbol('Ser_Qualid')
            and isinstance(node[1], list)
            and node[1] and node[1][0] == sexpdata.Symbol('DirPath')
            and isinstance(node[2], list)
            and node[2][0] == sexpdata.Symbol('Id')):

        modules = [elt[1] for elt in reversed(node[1][1])]
        ident = node[2][1]
        if not isinstance(ident, str):
            return out
        if modules:
            qualified_name = '.'.join(modules + [ident])
            if not qualified_name.startswith(('Coq.', 'N.', 'Z.')):
                out.add(qualified_name)
        elif isinstance(ident, str) and ident:
            # We still have to convert to str!!
            # Symbol('Id') passes isinstance(str) check,
            # but it is not a string.
            out.add(str(ident))
        return out

    if isinstance(node, list):
        for sub in node:
            out |= collect_qualids(sub)
    return out


def find_key_from_tree(tree: Any, key: Any):
    """
    Given something like:
    (loc
        ((fname (InFile GHC/Base.v))
        (line_nb 52) (bol_pos 1378)(line_nb_last 52)(bol_pos_last 1378)
        (bp 1378)(ep 1440)
    ))

    Find the value corresponding to the key.
    For example, the call with key='bp' would return 1378.
    """
    if isinstance(tree, list):
        if len(tree) == 2 and tree[0] == key and isinstance(tree[1], int):
            return tree[1]
        for sub in tree:
            try:
                return find_key_from_tree(sub, key)
            except KeyError:
                pass
    raise KeyError


def iter_sentences(
    sercompt_opts: list[str],
    coqproject_filepath: Path,
    coq_file_relative_to_coqproject_path: Path,
):
    """
    Returns <name, signature, proof_body, deps, notation> in order.

    proof_body can be empty for things containing only signatures. proof_body only accounts
    for proof/theorem bodies. Everything else is considered a signature.

    Returns proofs and signatures in separate runs (you'd have to call the generator a second time).

    Signature is empty if notation is matched.

    Name and proof_body can be both empty for anything not matched by DPDGRAPH_INCLUDE_REGEX,
    which includes Hints, Tactics, Ltac, Import, etc. In that case, only the
    signature is returned.
    """
    coqproject_dir = coqproject_filepath.parent

    if not shutil.which("sercomp"):
        sys.exit(
            "sercomp not in $PATH (opam install coq-serapi). Make sure you are in the correct opam switch."
        )

    cmd = ["sercomp", "--mode=sexp", *sercompt_opts,
           str(coq_file_relative_to_coqproject_path)]

    sercomp_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        text=True,
        cwd=coqproject_dir
    )

    if sercomp_proc.stdout is None:
        raise RuntimeError("sercomp produced no stdout")

    source_bytes = Path(
        coqproject_dir / coq_file_relative_to_coqproject_path
    ).read_bytes()

    # If we are inside some Proof ... Qed/Defined. block, then
    # collect = True, so the next line is marked for collection for the body.
    collect = False
    cur_name = ''
    cur_sig = ''
    proof_lines = []
    cur_deps: set[str] = set()

    try:
        for line in sercomp_proc.stdout:
            if not line.strip():
                continue

            sexp = sexpdata.loads(line)
            loc = next(x for x in sexp if isinstance(x, list)
                        and x and x[0] == sexpdata.Symbol("loc"))
            begin_point = find_key_from_tree(loc, sexpdata.Symbol("bp"))
            end_point = find_key_from_tree(loc, sexpdata.Symbol("ep"))
            src = source_bytes[begin_point:end_point].decode("utf-8").rstrip()

            if not collect and (re.fullmatch(r"\s*Proof\.", src) or re.fullmatch(r"\s*Proof(?:\s+using\b.*)?\.", src)):
                collect = True
                # It begins with <src> because we want to include the "Proof." line
                # in the proof body
                proof_lines = [src]
                cur_deps = set()
                continue

            deps_here = collect_qualids(sexp)
            if collect:
                proof_lines.append(src)
                cur_deps |= deps_here
                if PROOF_TERMINATION_RE.search(src):
                    body = "\n".join(proof_lines).strip()

                    if cur_sig.split(' ')[0] == 'Definition':
                        # Then it's a proof under a definition which we don't
                        # want to include in the body. This is by design;
                        # we consider it a part of the signature.
                        cur_sig += '\n' + body
                        body = ''

                    yield cur_name, cur_sig, body, cur_deps, ''
                    collect = False
                    cur_name = ''
                    cur_sig = ''
                    proof_lines, cur_deps = [], set()
                continue

            if m := DPDGRAPH_INCLUDE_REGEX.match(src):
                # This is str | Any. Do we need to handle the other case,
                # or trust the output of serapi is correct?
                ident = m.group(1)

                if src.lstrip().startswith("Add Parametric Relation"):
                    as_m = re.search(r"\bas\s+([^\s.]+)\.", src, re.S)
                    if as_m:
                        ident = as_m.group(1)

                # src.lstrip().startswith("Next Obligation")
                # or "VernacInstance" in line

                cur_name = ident
                cur_sig = src
                # if "VernacStartTheoremProof" in line or re.match(r"^\s*Proof\.\s*$", src):
                #     collect = True
                #     cur_name = ident
                #     cur_sig = src
                #     proof_lines = []
                #     cur_deps = deps_here
                # else:
                yield ident, src, '', deps_here, ''
            elif not collect:
                if NOTATION_RE.match(src):
                    # If a notation is matched this yields the line directly
                    # as the line is anyways small enough.
                    yield '', '', '', deps_here, src
                else:
                    # print('not matched:', src)
                    # print('not matched:', src, 'deps=', deps)
                    yield '', src, '\n'.join(proof_lines).strip(), deps_here, ''
    finally:
        try:
            sercomp_proc.terminate()
            sercomp_proc.wait(timeout=2)
        except Exception:
            pass
