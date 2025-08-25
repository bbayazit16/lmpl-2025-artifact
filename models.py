from openai import OpenAI
from abc import abstractmethod
from typing import Literal, Optional


class LLM:
    model_name: str

    def __init__(self, model_name: str):
        self.model_name = model_name

    @abstractmethod
    def get_request_params(self, temperature: float, max_tokens: int, system_prompt: str, prompt: str) -> dict:
        raise NotImplementedError()

    @abstractmethod
    def display_name(self) -> str:
        return self.model_name

    def __str__(self) -> str:
        return self.display_name()


class DefaultLLM(LLM):
    def __init__(self, model_name: str):
        super().__init__(model_name)

    def get_request_params(self, temperature: float, max_tokens: int, system_prompt: str, prompt: str) -> dict:
        return {
            'model': self.model_name,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': temperature,
            'max_tokens': max_tokens
        }


class OpenAIReasoning(LLM):
    reasoning_effort: Optional[Literal['low', 'medium', 'high']]
    supports_system_prompt: bool

    def __init__(
        self,
        model_name: str,
        reasoning_effort: Optional[Literal['low', 'medium', 'high']],
        supports_system_prompt: bool = True
    ):
        super().__init__(model_name)
        self.reasoning_effort = reasoning_effort
        self.supports_system_prompt = supports_system_prompt

    def get_request_params(
        self,
        temperature: float,  # temperature
        max_tokens: int,
        system_prompt: str,
        prompt: str
    ) -> dict:
        params = {
            'model': self.model_name,
            'max_completion_tokens': max_tokens,
        }
        if not self.supports_system_prompt:
            params['messages'] = [
                {'role': 'user', 'content': system_prompt + '\n' + prompt}
            ]
        else:
            params['messages'] = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ]

        if self.reasoning_effort:
            params['reasoning_effort'] = self.reasoning_effort

        return params

    def display_name(self) -> str:
        if self.reasoning_effort:
            return f'{self.model_name}-{self.reasoning_effort}'
        return self.model_name
