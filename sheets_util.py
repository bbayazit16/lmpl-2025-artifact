# This extracts **/results.csv to one single folder, and has nothing to do
# with the experiment's logic. Meant to be used as a standalone utility
# after the results are done.

from pathlib import Path
import shutil

LOGS_DIR = [Path('logs-hs-to-coq'), Path('logs-verdi')]
FINAL_DIR = Path('results')

FINAL_DIR.mkdir(exist_ok=True)


def copy(src: Path, dst: Path):
    shutil.copy(str(src), str(dst))


csv_files: dict[str, Path] = dict()
for experiment in LOGS_DIR:
    for results_csv in experiment.rglob('results.csv'):
        relative_path = results_csv.relative_to(experiment)
        folder_name = str(relative_path.parent).replace(
            '/', '_').replace('\\', '_')
        experiment_name = experiment.name
        csv_files[f'{experiment_name}/{folder_name}'] = results_csv

    csv_files[f'{experiment_name}/stats/original_proof_stats'] = Path(
        f'./{experiment.name}') / 'proof_stats.csv'

    for llm_stats_csv in experiment.rglob('llm_proof_stats.csv'):
        relative_path = llm_stats_csv.relative_to(experiment)
        model_folder_name = str(relative_path.parent).replace(
            '/', '_').replace('\\', '_')
        experiment_name = experiment.name
        csv_files[f'{experiment_name}/stats/{model_folder_name}'] = llm_stats_csv

for path_name in csv_files:
    dest_path = FINAL_DIR / f'{path_name}.csv'
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # Don't use .with_suffix, removes everything after the last dot!
    copy(csv_files[path_name], dest_path)
