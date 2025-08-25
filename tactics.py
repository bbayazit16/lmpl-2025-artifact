from serapi import parse_sertop_responses
from coqobject import CoqObject

from pathlib import Path
import subprocess
from typing import Any
import sexpdata
from sexpdata import Symbol
import re


def extract_tactics(coq_object: CoqObject, proof_body: str, coq_project_path: Path, sercomp_args: list[str]) -> list[str]:
    """
    Return the number of tactics in the original proof of coq_object.
    0 if the coq_object is not a proof.
    """
    if not coq_object.is_proof():
        return []

    cmd = ['sertop', *sercomp_args, '--implicit', '--omit_loc', '--print0']

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=coq_project_path.parent,
        bufsize=1,
    )

    try:
        if proc.stdout is None or proc.stdin is None:
            raise RuntimeError('sertop produced no stdout or stdin')

        coq_code = coq_object.coqtop_input(
            with_answer=False
        )

        add_cmd = sexpdata.dumps(['Add', [], coq_code])

        proc.stdin.write(add_cmd + '\n')
        proc.stdin.flush()

        add_responses = parse_sertop_responses(proc)

        last_sid = -1
        for response in add_responses:
            if isinstance(response, list) and len(response) > 2:
                nested = response[2]
                if isinstance(nested, list) and len(nested) > 1 and nested[0] == sexpdata.Symbol('Added'):
                    sid = nested[1]
                    if isinstance(sid, int) and sid > last_sid:
                        last_sid = sid
                if isinstance(nested, list) and len(nested) > 0 and nested[0] == sexpdata.Symbol('CoqExn'):
                    # Then we couldn't add the original items? This is a fatal error.
                    # (Never happened in our evaluations)
                    print('Error: Couldn\'t add the original items:', nested)
                    return []

        proof_start_line = last_sid + 1
        add_cmd = sexpdata.dumps(['Add', [], proof_body])
        # print()
        # print(add_cmd)
        # print()

        proc.stdin.write(add_cmd + '\n')
        proc.stdin.flush()

        add_responses = parse_sertop_responses(proc)

        last_sid = -1
        for response in add_responses:
            if isinstance(response, list) and len(response) > 2:
                nested = response[2]
                if isinstance(nested, list) and len(nested) > 1 and nested[0] == sexpdata.Symbol('Added'):
                    sid = nested[1]
                    if isinstance(sid, int) and sid > last_sid:
                        last_sid = sid
                if isinstance(nested, list) and len(nested) > 0 and nested[0] == sexpdata.Symbol('CoqExn'):
                    # Then we couldn't add the original items? This is a fatal error.
                    # (Never happened in our evaluations)
                    if proof_body.strip() == coq_object.body:
                        print('Error: Couldn\'t add the original items:', nested)
                    return []

        proof_end_line = last_sid

        # We want to skip proof_start_line (Proof.)
        # We also want to exclude proof_end_line (end.)
        all_tactics = []
        for line in range(proof_start_line + 1, proof_end_line):
            ast_query = sexpdata.dumps(['Query', [('sid', line)], 'Ast'])
            proc.stdin.write(ast_query + '\n')
            proc.stdin.flush()

            ast_query_responses = parse_sertop_responses(proc)
            answer = ast_query_responses[1][2]

            for item in answer:
                if isinstance(item, list):
                    all_tactics.extend(_extract_tactics_ast(item))

        return all_tactics
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)


def _extract_tactics_ast(ast: Any):
    """
    Return a list of tactics in the AST
    """
    tactics = []

    def sanitize(name: str) -> str:
        base = name.split('/', 1)[0]
        base = re.sub(r'_[#].*$', '', base)
        base = re.sub(r'_[0-9A-F]+$', '', base)
        return base

    def recurse(node):
        if not isinstance(node, list) or not node:
            return

        head = node[0]
        if isinstance(head, Symbol):
            hv = head.value()

            if hv == 'TacAlias':
                name = _find_kername(node)
                if name and not name.startswith('by_'):
                    tactics.append(sanitize(name))

            elif hv == 'TacAtom':
                try:
                    inner = node[1][0][1]
                except Exception:
                    inner = None

                if isinstance(inner, list) and inner:
                    tag = inner[0].value()

                    if tag == 'TacIntroPattern':
                        tactics.append('intros')

                    elif tag == 'TacInductionDestruct':
                        flag = (
                            inner[1].value()
                            if len(inner) > 1 and isinstance(inner[1], Symbol)
                            else 'true'
                        )
                        tactics.append(
                            'induction' if flag == 'true' else 'destruct')

                    elif tag == 'TacReduce':
                        strat = None
                        if len(inner) > 1 and isinstance(inner[1], list) and inner[1]:
                            first = inner[1][0]
                            if isinstance(first, Symbol):
                                strat = first.value()

                        if strat is not None:
                            tactics.append(strat.lower())
                            # Switched to above from this:
                            # if strat == 'Unfold':
                            #     tactics.append('unfold')
                            # elif strat == 'Red':
                            #     tactics.append('red')
                            # else:
                            #     tactics.append('simpl')
                        else:
                            print('WARNING: Strat is none!')

                    elif tag == 'TacApply':
                        tactics.append('apply')

                    elif tag == 'TacRewrite':
                        tactics.append('rewrite')

                    elif tag == 'TacInversion':
                        tactics.append('inversion')

                    elif tag == 'TacCase':
                        tactics.append('case')

                    elif tag == 'TacElim':
                        tactics.append('elim')

                    elif tag == 'TacRed':
                        print('red tac')
                        tactics.append('red')

                    elif tag == 'TacConstructor':
                        tactics.append('exists')

                    elif tag.startswith('TacAssert'):
                        tactics.append('assert')

                    elif tag == 'TacChange':
                        tactics.append('change')

                    elif tag == 'TacLetTac':
                        # We explicitly pass this so that
                        # it doesn't fall to the branch below
                        pass

                    elif tag == 'TacGeneralize':
                        tactics.append('generalize')

                    elif tag.startswith('Tac'):
                        print('Uncaught:', tag)

            elif hv == 'TacRepeat':
                tactics.append('repeat')

            elif hv == 'TacCall':
                name = _find_qualid_id(node)
                if name:
                    s = sanitize(name)
                    if s.startswith('unfold'):
                        tactics.append('unfold')
                    elif s.startswith('rewrite'):
                        tactics.append('rewrite')
                    else:
                        tactics.append(s)

            # For rewrite -> H
            elif hv == 'TacGeneric':
                name = _find_qualid_id(node)
                if name:
                    if name.startswith('rewrite'):
                        tactics.append('rewrite')
                    elif name.startswith('unfold'):
                        tactics.append('unfold')

            elif hv == 'TacUnfold':
                tactics.append('unfold')

        for child in node:
            recurse(child)

    def _find_kername(node):
        if not isinstance(node, list):
            return None
        if (
            node and isinstance(node[0], Symbol)
            and node[0].value() == 'KerName'
            and len(node) >= 3
            and isinstance(node[2], list)
            and isinstance(node[2][1], Symbol)
        ):
            return node[2][1].value()
        for c in node:
            out = _find_kername(c)
            if out:
                return out
        return None

    def _find_qualid_id(node):
        """
        Find Ser_Qualid --> retur name
        """
        if not isinstance(node, list):
            return None
        for c in node:
            if (
                isinstance(c, list) and c
                and isinstance(c[0], Symbol)
                and c[0].value() == 'Ser_Qualid'
            ):
                for part in c:
                    if (
                        isinstance(part, list)
                        and len(part) == 2
                        and isinstance(part[0], Symbol)
                        and part[0].value() == 'Id'
                    ):
                        if isinstance(part[1], Symbol):
                            return part[1].value()
                        elif isinstance(part[1], str):
                            return part[1]
            else:
                found = _find_qualid_id(c)
                if found:
                    return found
        return None

    recurse(ast)
    return tactics
