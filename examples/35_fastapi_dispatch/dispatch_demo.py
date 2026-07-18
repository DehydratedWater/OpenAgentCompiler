"""Phase 23 — FastAPI dispatch: three calling modes + variants + retries.

The scaffold (`oac init --template=full`) generates a FastAPI service
whose POST /agents/{name}/run accepts three calling modes and a
composable RetryPolicy. This demo:

  1. Builds example AgentRunRequest payloads for sync / async /
     fire_and_forget calling modes.
  2. Constructs RetryPolicy chains the scaffold's dispatcher would
     walk: simple variant pick, linear fast→smart→external chain,
     hand-rolled per-step when conditions.
  3. Simulates the dispatcher's retry walk against a stub run_fn
     so you can see fallback_chain accumulate exactly as it would
     in the real service.

Run:

    uv run python examples/35_fastapi_dispatch/dispatch_demo.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import BaseModel, Field  # noqa: E402


# ----- Pydantic models mirroring what app/models.py emits ------------

class RetryStep(BaseModel):
    variant: str | None = None
    timeout_s: float = 60.0
    when: str = "on_failure"  # always | on_failure | on_timeout
    note: str | None = None


class RetryPolicy(BaseModel):
    steps: list[RetryStep] = Field(default_factory=list)

    @classmethod
    def linear(cls, variants: list[str | None]) -> "RetryPolicy":
        return cls(steps=[
            RetryStep(
                variant=v,
                when="always" if i == 0 else "on_failure",
            )
            for i, v in enumerate(variants)
        ])


class AgentRunRequest(BaseModel):
    prompt: str
    mode: str = "sync"  # sync | async | fire_and_forget
    variant: str | None = None
    retry: RetryPolicy | None = None
    callback_url: str | None = None
    timeout_s: float = 300.0


# ----- Stubbed run_fn: returns success/failure based on variant ------

@dataclass
class _StubResult:
    status: str
    variant: str | None
    return_code: int | None = None
    error: str | None = None
    fallback_chain: list[dict] = field(default_factory=list)


# Configurable: which variants succeed in this scenario.
_SUCCEED_ON = {"smart", "external-api"}


def _stub_run(name: str, req: AgentRunRequest) -> _StubResult:
    """Simulate a run. The 'fast' variant fails; 'smart' / 'external-api' succeed."""
    if req.variant in _SUCCEED_ON or req.variant is None:
        return _StubResult(
            status="completed", variant=req.variant,
            return_code=0,
        )
    return _StubResult(
        status="failed", variant=req.variant,
        return_code=1, error=f"variant {req.variant!r} failed in this scenario",
    )


# ----- Simulated dispatcher (mirrors app/dispatch.py) ---------------

def _step_applies(step: RetryStep, index: int, last_status: str) -> bool:
    if index == 0:
        return True
    if step.when == "always":
        return True
    if step.when == "on_failure":
        return last_status in ("failed", "timeout", "unreachable")
    if step.when == "on_timeout":
        return last_status == "timeout"
    return False


def dispatch_run(name: str, req: AgentRunRequest) -> _StubResult:
    """Simulate the scaffold's dispatch_run for sync mode."""
    if req.retry is None or not req.retry.steps:
        return _stub_run(name, req)
    chain: list[dict] = []
    last: _StubResult | None = None
    last_status = "pending"
    for i, step in enumerate(req.retry.steps):
        if not _step_applies(step, i, last_status):
            chain.append({
                "variant": step.variant, "status": "skipped",
                "note": step.note or f"when={step.when} did not match",
            })
            continue
        attempt_req = req.model_copy(update={
            "variant": step.variant, "timeout_s": step.timeout_s,
            "retry": None,
        })
        result = _stub_run(name, attempt_req)
        chain.append({
            "variant": step.variant,
            "status": result.status,
            "return_code": result.return_code,
            "error": result.error,
            "note": step.note,
        })
        last = result
        last_status = result.status
        if result.status == "completed":
            result.fallback_chain = chain
            return result
    if last is not None:
        last.fallback_chain = chain
        return last
    return _StubResult(
        status="failed", variant=None,
        error="all retry steps skipped",
        fallback_chain=chain,
    )


# ----- Demos ---------------------------------------------------------

def _print_section(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}\n")


def demo_three_modes() -> None:
    _print_section("Mode 1 — sync (block, return result inline)")
    req = AgentRunRequest(prompt="summarise X")
    print("REQUEST:")
    print(req.model_dump_json(indent=2))
    result = dispatch_run("research", req)
    print(f"\nRESULT: status={result.status} variant={result.variant!r}")

    _print_section("Mode 2 — async (return run_id + poll_url immediately)")
    req = AgentRunRequest(prompt="summarise X", mode="async", variant="fast")
    print("REQUEST:")
    print(req.model_dump_json(indent=2))
    print(
        "\n(In production the FastAPI returns immediately with"
        " status='running' + poll_url='/runs/<run_id>/await'.\n"
        " The caller GETs that URL when they want the result.)"
    )

    _print_section("Mode 3 — fire_and_forget (detached + optional callback)")
    req = AgentRunRequest(
        prompt="summarise X", mode="fire_and_forget",
        callback_url="https://my-app.example/results",
    )
    print("REQUEST:")
    print(req.model_dump_json(indent=2))
    print(
        "\n(FastAPI runs the agent detached. When it terminates the\n"
        " server POSTs the final AgentRunResult to callback_url.\n"
        " No polling required from the caller.)"
    )


def demo_variant_routing() -> None:
    _print_section("Variant routing — one logical name → many compiled trees")
    for variant in (None, "fast", "smart"):
        req = AgentRunRequest(prompt="summarise X", variant=variant)
        label = req.variant or "<default>"
        print(f"  variant={label!r:<14} → expected file: "
              f"build/.opencode/agents/research"
              + (f"-{variant}.md" if variant else ".md"))


def demo_retry_chain() -> None:
    _print_section("Retry policy — composable escalation chain")
    policy = RetryPolicy.linear(["fast", "smart", "external-api"])
    req = AgentRunRequest(prompt="hard task", retry=policy)
    print("REQUEST.retry (RetryPolicy.linear shorthand):")
    print(policy.model_dump_json(indent=2))
    result = dispatch_run("research", req)
    print(f"\nFINAL: status={result.status} variant={result.variant!r}")
    print("\nfallback_chain (every attempt):")
    print(json.dumps(result.fallback_chain, indent=2))


def demo_hand_rolled_chain() -> None:
    _print_section("Hand-rolled chain with per-step `when` conditions")
    policy = RetryPolicy(steps=[
        RetryStep(variant="fast", when="always", timeout_s=10,
                  note="cheap first attempt"),
        RetryStep(variant="smart", when="on_failure", timeout_s=60,
                  note="local stronger model"),
        RetryStep(variant="external-api", when="on_failure", timeout_s=180,
                  note="last resort — bills external"),
    ])
    req = AgentRunRequest(prompt="hard task", retry=policy)
    result = dispatch_run("research", req)
    print(f"FINAL: status={result.status} variant={result.variant!r}\n")
    print("fallback_chain:")
    print(json.dumps(result.fallback_chain, indent=2))


def main() -> None:
    demo_three_modes()
    demo_variant_routing()
    demo_retry_chain()
    demo_hand_rolled_chain()
    print("\n" + "=" * 60)
    print("All four demos finished. In a real scaffold the same payloads")
    print("hit POST /agents/{name}/run on the generated FastAPI service.")
    print("=" * 60)


if __name__ == "__main__":
    main()
