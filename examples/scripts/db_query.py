"""Example handler: execute READ-ONLY SQL queries."""

from pydantic import BaseModel, Field

from open_agent_compiler.runtime import ScriptTool, StreamFormat


class QueryInput(BaseModel):
    sql: str = Field(description="SQL query to execute")
    timeout: int = Field(default=60, description="Timeout in seconds")


class QueryOutput(BaseModel):
    success: bool = True
    rows: list[dict[str, object]] = Field(default_factory=list)


class DbQuery(ScriptTool[QueryInput, QueryOutput]):
    name = "db_query"
    description = "Execute READ-ONLY SQL queries"
    stream_format = StreamFormat.TEXT
    stream_field = "sql"

    def execute(self, input: QueryInput) -> QueryOutput:
        # Stub — real implementation would connect to a database
        return QueryOutput(success=True, rows=[{"result": input.sql}])


if __name__ == "__main__":
    DbQuery.run()
