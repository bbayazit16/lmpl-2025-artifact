import sys
import tiktoken
from openai import OpenAI, RateLimitError
import time
import os
from dotenv import load_dotenv

from models import LLM
from serapi import coq_version

# Note about the prompt: Defined vs Qed doesn't matter; since it'll only be given the
# file up until that point, and nothing else can depend on it. The file should compile
# nonetheless.
def is_before_8_11(version_str):
    major, minor, *_ = map(int, version_str.split('.'))
    return (major, minor) < (8, 11)

coqc_ver = coq_version()
use_omega = ' Remember that this version uses `omega` instead of `lia`.' if is_before_8_11(coqc_ver) else ''
SYSTEM_PROMPT = f"""\
You are an expert Coq programmer, specifically experienced with Coq version {coqc_ver}.{use_omega}

You are provided:

* The current Coq file containing the theorem or lemma to be proved.
* The statement (signature) of the theorem or lemma, which you must prove.
* Relevant dependencies and notations useful for proving the theorem or lemma, if applicable. You may choose to use to use them or not.

Your task:

* Carefully read the provided context, dependencies, and notations.
* Generate a complete and correct proof for the given theorem or lemma.
* Your response should **only** include the complete proof body, wrapped explicitly between `Proof.` and `Qed.` statements. Do not include any other text, comments, or explanations.
* Do **not** include the theorem or lemma statement (signature) itself, explanations, or additional text outside the proof.
* You may not use Admitted or derivatives in your proof.
* The proof should be valid and compile successfully in Coq.

Example format of your response:

```
Proof.
  (* your complete proof here *)
Qed.
```
""".strip()


load_dotenv(override=True)
for arg in {'OPENAI_BASE_URL', 'OPENAI_API_KEY'}:
    if arg not in os.environ:
        print(f'Missing env variable: {arg}')
        if arg == 'OPENAI_BASE_URL':
            print(
                'Did you mean to use `https://api.openai.com/v1/` (or your Azure endpoint)?')
        sys.exit(1)


client = OpenAI(
    api_key=os.environ['OPENAI_API_KEY'],
    base_url=os.environ['OPENAI_BASE_URL'],
    default_query={'api-version': 'preview'},
)


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text)) if text else 0


def call_llm(
    prompt: str,
    model: LLM,
    max_tokens: int,
    temperature: float,
    debug_info: str = '',
) -> str:
    """
    Return the LLM response.

    To change the generation logic, all you have to do is pass a
    different LLM (see models.py) and modify the logic here if needed.

    The temperature is ignored for reasoning models that do not support the setting.
    `max_tokens` are replaced with `max_completion_tokens` for reasoning models.
    See `models.py`.
    """
    request_params = model.get_request_params(
        temperature, max_tokens, SYSTEM_PROMPT, prompt
    )

    wait_time = 10
    while True:
        try:
            response = client.chat.completions.create(**request_params)
            content = response.choices[0].message.content
            if not content:
                raise ValueError(f"Model returned empty content: {response}")
            return normalized(content)
        except RateLimitError:
            time.sleep(wait_time)
            wait_time = int(wait_time * 1.5)
            if wait_time > 35:
                wait_time = 35
        except Exception as e:
            if debug_info:
                print('call_llm debug for', debug_info)
            print(e)
            continue


def normalized(llm_result: str) -> str:
    """
    Extract the code only, removing wrappings around triple backticks,
    or triple backticks ```coq, or any other irrelavant formatting.
    """
    result = llm_result.strip()

    lines = result.split('\n')

    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            start_idx = i + 1
            break

    end_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped == '```' or stripped.startswith('```'):
            end_idx = i
            break

    if start_idx < end_idx:
        result = '\n'.join(lines[start_idx:end_idx])

    result = result.strip()

    # Also removing hs because the project is hs-to-coq; may hallucinate
    # with returning 'hs' in the response.
    prefixes_to_remove = ['```coq', '```ocaml', '```haskell', '```hs', '```']
    suffixes_to_remove = ['```']

    for prefix in prefixes_to_remove:
        if result.startswith(prefix):
            result = result[len(prefix):].strip()

    for suffix in suffixes_to_remove:
        if result.endswith(suffix):
            result = result[:-len(suffix)].strip()

    return result
