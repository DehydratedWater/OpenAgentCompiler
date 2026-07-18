"""Example handler: prints 'hello' and returns it as a string."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool


class HelloInput(BaseModel):
    pass


class HelloOutput(BaseModel):
    message: str = Field(description="The greeting message")


class Hello(ScriptTool[HelloInput, HelloOutput]):
    name = "hello"
    description = "Prints 'hello' and returns it as a string"

    def execute(self, input: HelloInput) -> HelloOutput:
        message = "hello"
        print(message)
        return HelloOutput(message=message)


if __name__ == "__main__":
    Hello.run()
