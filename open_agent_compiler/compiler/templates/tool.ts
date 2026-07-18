import { tool } from "@opencode-ai/plugin"
import path from "path"

export default tool({
  description: "{{description}}",
  args: {
{{args}}
  },
  async execute(args, context) {
    const script = path.join(context.worktree, "{{script_path}}")
    const result = await Bun.stdin(JSON.stringify(args)).$`uv run ${script} --json`.text()
    return result.trim()
  },
})
