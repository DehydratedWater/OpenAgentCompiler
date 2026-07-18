"""LLM judge clients implementing the JudgeClient protocol.

- StubJudge: deterministic responses driven by a {criteria: result} dict.
  Use in tests so they don't make real LLM calls.
- AnthropicJudge / OpenAIJudge: real wrappers around the respective
  SDKs, imported lazily. The SDK is NOT a runtime dep of the package —
  consumers install whichever one they want.
"""

from open_agent_compiler.testing.judges.stub import StubJudge

__all__ = ["StubJudge"]
