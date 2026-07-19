# Retrieval testing — graded QA over a seeded corpus

How to autoloop-test (and therefore auto-improve) any retrieval capability:
an agent, a tool chain, or a whole multi-agent workflow whose job is
"find the right information and surface it".

## The problem with judging retrieval

An LLM judge can grade *phrasing* but cannot know whether `7351` really is
the user's bike lock code — so judge-only retrieval suites either pass
confident hallucinations or fail correct answers. Retrieval needs **exact
ground truth**, and the way to get it at scale is to *control the corpus*.

## The canary method

1. **Seed a large, realistic haystack.** Copy real historical data into the
   test database (the consumer decides what "real" means — chat history,
   documents, transcripts). Size matters: ranking and recall problems do not
   reproduce on 200 rows. Aim for the production order of magnitude.
2. **Plant canaries.** Insert a small number of synthetic records whose key
   facts are globally unique in the corpus (`X9-KITE-42`, `NF-A12x25`,
   `LO1923`). Each canary records its *question* and its *facts* next to the
   payload — one source of truth for both seeding and testing.
3. **Probe with `FactRecallEvaluator`.** Ask the canary question; the
   evaluator scores `recalled_facts / total_facts` and **zeroes the score if
   any `forbidden` string appears** (refusal boilerplate, fabricated values).
   Because the fact is unique in the corpus, recall is unambiguous: the agent
   either found the needle or it didn't.
4. **Cross-source canaries.** Plant needles in *different* stores (a chat
   message AND a document/transcript) and ask one question needing both —
   this is the only honest test of multi-source synthesis.

## The evaluator

```python
from open_agent_compiler import AgentTest, FactRecallEvaluator, FactSpec

AgentTest(
    name="retrieval:exact:bike_lock",
    prompt="What is my bike lock code?",
    evaluators=(
        FactRecallEvaluator(
            facts=(FactSpec(any_of=("7351",)),),       # aliases of ONE fact
            forbidden=("as an ai", "i cannot access"), # hallucination/refusal guard
            pass_threshold=1.0,                        # graded: recalled/total
        ),
    ),
)
```

- `FactSpec.any_of` holds surface forms of the same fact ("36mg", "36 mg") —
  any one counts as recall.
- `forbidden` is a hard gate: a retrieval answer that fabricates or refuses
  scores 0.0 regardless of recall.
- Empty `facts` + non-empty `forbidden` = a pure no-hallucination probe.
- The score is continuous, so the `score_floor` / `score_mean` criteria and
  per-test `score_floor:by_name:<test>` metrics work unchanged — retrieval
  suites plug into `IterativeLoop` / `optimize_callable` like any other.

## Mixing graded categories

A full retrieval suite is layered; each layer catches what the previous
can't:

| category   | ground truth            | evaluators |
|------------|-------------------------|-----------|
| exact      | canary facts            | `FactRecallEvaluator` |
| open-ended | corpus themes           | `LLMJudgeEvaluator` (groundedness rubric) + `FactRecallEvaluator(forbidden=…)` |
| store-specific | canary planted in ONE store | `FactRecallEvaluator` (forces that store's search path) |
| live-infra | external service        | judge, tolerant of "empty but checked", intolerant of "didn't check" |
| self-exam  | canary + its planted timestamp | `FactRecallEvaluator` with a date-alias fact |

For end-to-end workflows (planner/executor loops), run the whole workflow,
concatenate every persisted output/log, and evaluate that blob with
`FactRecallEvaluator` — a smoke-level fact-recall pack over the full workflow
is the reference shape.

## Reference implementation

assistant_project:
- `backend/app/agents/retrieval_corpus.py` — seeder (20k messages, canaries,
  transcript canary, prod-encoder embeddings, `_autoloop`-only safety guard).
- `backend/app/agents/retrieval_probes.py` — the five-category suite.
- `backend/app/agents/workflow_smoke.py` — full-workflow cross-source probe.
