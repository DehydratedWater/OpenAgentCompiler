# 33 sqlite-resources — ScriptTool.execute(input, resources)

Demonstrates Phase 15's typed resource path. A ScriptTool whose
`execute()` declares `(input, resources)` receives a dict of
`ResourceHandle` keyed by the symbolic resource names it declared
in `requires_resources` (or any name the active AccessProfile
binds).

The framework reads `OAC_RESOURCES_JSON` from the environment at
script start, parses it, and constructs the handles. In a real
deployment the compile pipeline sets this env var per-invocation
based on the active AccessProfile; for direct invocation you set
it yourself.

## Try it

```bash
RESOURCES='{"notes_db":{"kind":"sqlite","config":{"path":"/tmp/oac_demo.db"}}}'

# Add a note
OAC_RESOURCES_JSON="$RESOURCES" \
  uv run python examples/33_sqlite_resources/scripts/notes_db.py \
  --mode add --content "first note from the demo"

# List notes
OAC_RESOURCES_JSON="$RESOURCES" \
  uv run python examples/33_sqlite_resources/scripts/notes_db.py \
  --mode list

# Mock the resource (no real DB needed)
OAC_RESOURCES_JSON='{}' \
  uv run python examples/33_sqlite_resources/scripts/notes_db.py --mode list
```

Output (third case):
```json
{"ok": false, "rows": [], "note": "notes_db resource not bound"}
```

## Wiring into agents.py

```python
PROFILES = [
    AccessProfile(name="prod", bindings={
        "notes_db": ResourceBinding(kind="sqlite", config={"path": "data/notes.db"}),
    }),
    AccessProfile(name="ci", bindings={
        "notes_db": ResourceBinding(kind="sqlite", config={"path": ":memory:"}),
    }),
]
```

Tests under the `ci` profile use the in-memory binding so they're
isolated and fast. Production gets the on-disk path.

## Backwards-compatibility

Existing tools with `def execute(self, input)` keep working
unchanged — the runtime inspects the signature and only passes
`resources=...` when the subclass opts in. See the `authoring-tools`
skill for the migration story.
