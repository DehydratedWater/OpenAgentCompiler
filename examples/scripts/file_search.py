"""Example handler: search files by pattern."""

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool


class SearchInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files")
    directory: str = Field(default=".", description="Root directory to search")


class SearchOutput(BaseModel):
    matches: list[str] = Field(default_factory=list)


class FileSearch(ScriptTool[SearchInput, SearchOutput]):
    name = "file_search"
    description = "Search files by glob pattern"

    def execute(self, input: SearchInput) -> SearchOutput:
        # Stub — real implementation would use pathlib.Path.glob
        return SearchOutput(matches=[])


if __name__ == "__main__":
    FileSearch.run()
