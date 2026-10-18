from abc import ABC, abstractmethod


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def ask(self, prompt: str) -> str:
        """Send a prompt to the provider and return its response."""
        raise NotImplementedError
