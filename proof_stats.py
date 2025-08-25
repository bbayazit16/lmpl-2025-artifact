from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from pathlib import Path
from typing import cast

from tqdm import tqdm
from coq_sercomp import iter_sentences
from coq_modules import parse_coq_project_file
from coqobject import CoqObject
from models import LLM
from tactics import extract_tactics
from eval import model_log_dir


def get_all_llm_stats(
    models: list[LLM],
    objects: list[CoqObject],
    coq_project_file_path: Path,
    logs_dir: Path,
    threads: int,
    no_dependencies: bool,
    no_lines_before: bool,
    max_tokens: int,
    temperature: float,
):
    proof_objs = [obj for obj in objects if obj.is_proof()]

    sercomp_args = parse_coq_project_file(coq_project_file_path, 'sercomp')

    for model in models:
        output_csv_path = model_log_dir(
            logs_dir,
            no_dependencies,
            no_lines_before,
            model,
            max_tokens,
            temperature
        ) / 'llm_proof_stats.csv'

        if output_csv_path.exists():
            continue

        stats_results: list[
            list[str]
            | None
        ] = [None] * len(proof_objs)

        def _worker(idx_and_obj: tuple[int, CoqObject]) -> tuple[int, list[str]]:
            idx, obj = idx_and_obj
            try:
                logfile_path = model_log_dir(
                    logs_dir,
                    no_dependencies,
                    no_lines_before,
                    model,
                    max_tokens,
                    temperature
                ) / obj.log_name()

                if not logfile_path.exists():
                    return idx, []

                llm_response = logfile_path.read_text().strip()

                tactics = extract_tactics(
                    obj, llm_response, coq_project_file_path, sercomp_args
                )
                return idx, tactics
            except Exception as e:
                print(f"STATS ERROR: {obj.name} (model {model}): {e}")
                return idx, []

        indexed = list(enumerate(proof_objs))
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {executor.submit(_worker, item): item for item in indexed}

            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Gathering proof stats for {model}",
                unit="obj"
            ):
                idx, result = future.result()
                stats_results[idx] = result

        # Even with assert, the type was not inferred correctly
        result = cast(list[list[str]], stats_results)

        output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with output_csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(
                ['name', 'file', 'tactics_count', 'tactics']
            )
            for obj, tactics in zip(proof_objs, result):
                tactics_str = ';'.join(tactics)
                writer.writerow([
                    obj.name,
                    obj.in_relative_file,
                    len(tactics),
                    tactics_str,
                ])


def get_all_stats(
    objects: list[CoqObject],
    coq_project_file_path: Path,
    logs_dir: Path,
    threads: int
) -> list[tuple[list[str], int]]:
    """Return a list of tuple <tactics used, number of theorems before the theorem in the file>"""
    proof_stats_log = logs_dir / 'proof_stats.csv'
    if proof_stats_log.exists():
        return []

    sercomp_args = parse_coq_project_file(coq_project_file_path, 'sercomp')

    proof_objs = [obj for obj in objects if obj.is_proof()]

    stats_results: list[tuple[list[str], int]
                        | None] = [None] * len(proof_objs)

    def _worker(idx_and_obj: tuple[int, CoqObject]) -> tuple[int, tuple[list[str], int]]:
        idx, obj = idx_and_obj
        try:
            tactics = extract_tactics(
                obj, obj.body, coq_project_file_path, sercomp_args)
            count_before = _extract_theorem_count_before(
                obj, coq_project_file_path, sercomp_args)
            return idx, (tactics, count_before)
        except Exception as e:
            print(f"STATS ERROR: {obj.name}: {e}")
            return idx, ([], 0)

    indexed = list(enumerate(proof_objs))
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(_worker, item): item for item in indexed}

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Gathering proof stats",
            unit="obj"
        ):
            idx, result = future.result()
            stats_results[idx] = result

    # Even with assert, the type was not inferred correctly
    result = cast(list[tuple[list[str], int]], stats_results)

    logs_dir.mkdir(parents=True, exist_ok=True)
    with proof_stats_log.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(
            ['name', 'file', 'theorems_before_count', 'tactics_count', 'tactics']
        )
        for obj, (tactics, count_before) in zip(proof_objs, result):
            tactics_str = ';'.join(tactics)
            writer.writerow([
                obj.name,
                obj.in_relative_file,
                count_before,
                len(tactics),
                tactics_str,
            ])

    return result


def _extract_theorem_count_before(
    obj: CoqObject,
    coq_project_file_path: Path,
    sercomp_args: list[str]
) -> int:
    """
    Return the number of lemmas/theorems/etc. that come before the proof in the file.
    """

    total_proofs = 0
    for name, _, body, _, _ in iter_sentences(
        sercomp_args, coq_project_file_path, obj.in_relative_file
    ):
        if name == obj.name:
            break

        # If body exists: += 1
        total_proofs += bool(body != '')

    return total_proofs
