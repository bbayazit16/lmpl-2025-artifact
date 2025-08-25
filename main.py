#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from proof_stats import get_all_llm_stats, get_all_stats
from eval import estimate_eval_input_tokens, estimate_eval_output_tokens, eval_coq_objects
from coqobject import CoqObject, build_coq_objects, pretty_print
import sys
import os
from llm import count_tokens

from models import DefaultLLM, OpenAIReasoning, LLM

# To extend, all you have to do is add more models here.
# Also see: models.py,
MODELS: list[LLM] = [
    DefaultLLM('gpt-4o-mini'),
    DefaultLLM('gpt-4o'),
    OpenAIReasoning('o4-mini', 'medium'),
    DefaultLLM('deepseek/deepseek-prover-v2'),
    DefaultLLM('deepseek/deepseek-r1-0528:free'),

    # DefaultLLM('deepseek/deepseek-r1-0528'),

    # OpenAIReasoning('o4-mini', 'low'),
    # OpenAIReasoning('o4-mini', 'high'),

    # OpenAIReasoning('o1-mini', None, supports_system_prompt=False),

    # OpenAIReasoning('o3-mini', 'medium'),
    # OpenAIReasoning('o3-mini', 'high'),

    # OpenAIReasoning('o1', 'low'),
    # OpenAIReasoning('o1', 'medium'),
    # OpenAIReasoning('o1', 'high'),

    # OpenAIReasoning('o3', 'low'),
    # OpenAIReasoning('o3', 'medium'),
    # OpenAIReasoning('o3', 'high'),
]

MODEL_NAMES: dict[str, LLM] = {m.display_name(): m for m in MODELS}


def simulate(
    project_path: Path,
    logs_dir: Path,
    dry_run: bool,
    count: bool,
    count_llm: bool,
    pretty_print_objects: bool,
    reconstruct_objects: bool,
    no_dependencies: bool,
    no_lines_before: bool,
    thread_count: int,
    models: list[LLM],
    temperature: float,
    max_tokens: int
):
    try:
        if project_path.is_dir():
            project_path = project_path / '_CoqProject'

        add_samefile_deps = no_lines_before and not no_dependencies

        coq_objects = []
        proofs = []
        if add_samefile_deps:
            objects_dir = logs_dir / 'objects-same-file-dependencies'
        else:
            objects_dir = logs_dir / 'objects'

        objects_dir_exists = objects_dir.exists() and objects_dir.is_dir() and \
            len(list(objects_dir.glob('*.log'))) > 0

        if not objects_dir_exists or reconstruct_objects:
            coq_objects = build_coq_objects(
                project_path=project_path,
                logs_dir=logs_dir,
                add_samefile_deps=add_samefile_deps
            )
            proofs = [obj for obj in coq_objects if obj.is_proof()]
        else:
            # objects_dir_exists and not reconstruct_objects
            for obj_file in objects_dir.glob('*.log'):
                coq_object = CoqObject.from_dict(
                    json.loads(obj_file.read_text().strip()))
                coq_objects.append(coq_object)
                if coq_object.is_proof():
                    proofs.append(coq_object)

        if count_llm:
            get_all_llm_stats(
                models,
                proofs,
                project_path,
                logs_dir,
                thread_count,
                no_dependencies,
                no_lines_before,
                max_tokens,
                temperature
            )
        if count:
            get_all_stats(proofs, project_path, logs_dir, thread_count)
            mean = sum(
                count_tokens(obj.llm_prompt(
                    no_dependencies=no_dependencies,
                    no_lines_before=no_lines_before
                )) for obj in proofs) / len(proofs) if proofs else 0
            print(f'Mean LLM prompt token count: {mean:_}')

            median = sorted(
                count_tokens(obj.llm_prompt(
                    no_dependencies=no_dependencies,
                    no_lines_before=no_lines_before
                )) for obj in proofs)[len(proofs) // 2] if proofs else 0
            
            print(f'Median LLM prompt token count: {median:_}')
            max_amt = max(
                count_tokens(obj.llm_prompt(
                    no_dependencies=no_dependencies,
                    no_lines_before=no_lines_before
                )) for obj in proofs) if proofs else 0
            
            print(f'Max LLM prompt token count: {max_amt:_}')

        print(
            f'Total input token count estimate: {estimate_eval_input_tokens(
                proofs,
                no_dependencies=no_dependencies,
                no_lines_before=no_lines_before
            ):_}'
        )
        print(
            f'Lower bound estimate for output tokens: {estimate_eval_output_tokens(proofs, max_tokens, 'lower'):_}'
        )
        print(
            f'Upper bound estimate for output tokens: {estimate_eval_output_tokens(proofs, max_tokens, 'upper'):_}'
        )

        if pretty_print_objects:
            pretty_print(coq_objects)

        overall_results: dict[str, str] = {}
        for model in models:
            if not dry_run:
                print('Evaluating for:', model.display_name())

            if dry_run:
                continue

            results = eval_coq_objects(
                proofs,
                project_path,
                logs_dir,
                no_dependencies=no_dependencies,
                no_lines_before=no_lines_before,
                model=model,
                thread_count=thread_count,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            true_count = results.count(True)
            false_count = len(results) - true_count

            model_separator_str = '=' * 8 + \
                ' Model: ' + str(model) + ' ' + '=' * 8
            print()
            print(model_separator_str)
            print(f'Proof count: {len(results)}')
            print(f'Successes: {true_count}')
            print(f'Failures: {false_count}')
            success_rate = true_count / len(results)
            print(f'Success rate: {success_rate:.2%}')
            print(f"{'=' * len(model_separator_str)}\n")

            overall_results[
                str(model)
            ] = f'Successes: {true_count}, Failures: {false_count}, success_rate: {success_rate:.2%}'

        if not dry_run:
            print('\nResults:')
        for model, result in overall_results.items():
            print(f'{model}: {result}')

    except KeyboardInterrupt:
        print('\n\nExiting...')
        print(
            'When running again, the previous LLM responses will be read from the log file.')


def main():
    parser = argparse.ArgumentParser(description='Run LLMs on Coq projects.')
    parser.add_argument(
        'project_path',
        type=Path,
        help='Path to Coq project directory or _CoqProject file'
    )
    parser.add_argument(
        '--logs-dir',
        type=Path,
        default='./logs',
        help='Directory to store log files (default: ./logs)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without executing the evaluations. Prints the token cost and attempts to parse the project'
    )
    parser.add_argument(
        '--print-objects',
        action='store_true',
        help='Print generated objects'
    )
    parser.add_argument(
        '--reconstruct-objects',
        action='store_true',
        help='Reconstructs the Coq objects, even if the log directory exists. ' +
        'Pass this flag to force the re-construction of Coq proofs from the file. '
        + 'Note that LLM evaluation will still be cached from the logs even without this option present. (default: False)'
    )
    parser.add_argument(
        '--threads',
        type=int,
        default=os.cpu_count() or 1,
        help=f'Thread count. (default: {os.cpu_count() or 1})'
    )
    parser.add_argument(
        '--models',
        nargs='*',
        default=MODEL_NAMES.keys(),
        help=f'Space-delimited list of models to use for evaluation. (default: {", ".join(MODEL_NAMES.keys())})'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.1,
        help='Temperature for LLM responses. Ignored for reasoning models that do not support temperature. (default: 0.1)'
    )
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=16_384,
        help='Maximum tokens for LLM responses. Used as max_completion_tokens for reasoning models. (default: 16_384)'
    )
    parser.add_argument(
        '--no-dependencies',
        action='store_true',
        help='Does not pass the likely-dependent objects to the LLM. (default: false).'
    )
    parser.add_argument(
        '--no-lines',
        action='store_true',
        help='Does not pass the lines before the theorem to the LLM. (default: false).'
    )
    parser.add_argument(
        '--count',
        action='store_true',
        help='Counts the number of tactics for each proof (default: false).'
    )
    parser.add_argument(
        '--count-llm',
        action='store_true',
        help='Counts the number of tactics for each LLM proof. Requires the responses to exist already (default: false).'
    )

    args = parser.parse_args()
    project: Path = args.project_path.resolve()
    logs: Path = args.logs_dir.resolve()

    if not project.exists():
        print(f'Path to project {project} does not exist.')
        sys.exit(1)

    # Make sure all models are in the default models list
    models = []
    for model in args.models:
        if model not in MODEL_NAMES:
            print(
                f'Model {model} is not supported. Supported models: {", ".join(MODEL_NAMES.keys())}'
            )
            sys.exit(1)
        else:
            models.append(MODEL_NAMES[model])

    simulate(
        project,
        logs,
        dry_run=args.dry_run,
        count=args.count,
        count_llm=args.count_llm,
        pretty_print_objects=args.print_objects,
        reconstruct_objects=args.reconstruct_objects,
        no_dependencies=args.no_dependencies,
        no_lines_before=args.no_lines,
        thread_count=args.threads,
        models=models,
        temperature=args.temperature,
        max_tokens=args.max_tokens
    )


if __name__ == "__main__":
    main()
