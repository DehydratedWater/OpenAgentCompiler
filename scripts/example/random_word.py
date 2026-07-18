"""Example handler: returns a random word from a fixed list of 10 words."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import random

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool


class RandomWordInput(BaseModel):
    pass


class RandomWordOutput(BaseModel):
    word: str = Field(description="A randomly selected word")


class RandomWord(ScriptTool[RandomWordInput, RandomWordOutput]):
    name = "random_word"
    description = "Returns a random word from a fixed list of 10 words"

    WORDS = [
        "banana",
        "rocket",
        "penguin",
        "drum",
        "volcano",
        "whisper",
        "cactus",
        "butterfly",
        "thunder",
        "mystery",
    ]

    def execute(self, input: RandomWordInput) -> RandomWordOutput:
        word = random.choice(self.WORDS)
        print(word)
        return RandomWordOutput(word=word)


if __name__ == "__main__":
    RandomWord.run()
