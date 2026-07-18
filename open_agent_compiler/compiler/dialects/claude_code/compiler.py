"""Claude Code compiler — writes to .claude/ instead of .opencode/."""

from __future__ import annotations

import shutil
from typing import ClassVar

from open_agent_compiler.compiler.dialects.opencode.compiler import OpenCodeCompiler


class ClaudeCodeCompiler(OpenCodeCompiler):
    dialect_name: ClassVar[str] = "claude"

    def compile(self) -> None:
        # Compile to a temp subdir using the OpenCode shape, then move the
        # resulting .opencode/ tree to .claude/. Bundled scripts copy is
        # path-independent so it lands in the same `scripts/` directory.
        super().compile()
        src_dir = self.target / ".opencode"
        dst_dir = self.target / ".claude"
        if not src_dir.exists():
            return
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.move(str(src_dir), str(dst_dir))
