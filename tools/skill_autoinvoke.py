#!/usr/bin/env python3
"""Make selected plugin skills model-invocable (runs at SessionStart; idempotent).

Plugin skills shipped with `disable-model-invocation: true` are invisible to Claude
(their descriptions are not loaded). For the skills listed below we flip that flag so
Claude can pick them up automatically. Plugin updates overwrite the cache, so this runs
every session.
"""
import glob
import os
import re
import sys

ALLOW = {
    "grill-me", "grill-with-docs", "teach", "handoff", "wait-what",
    "to-spec", "to-tickets", "improve-codebase-architecture", "ask-matt", "wayfinder",
}
ROOTS = [os.path.expanduser("~/.claude/plugins/cache/*/mattpocock-skills/*/skills/*/*/SKILL.md")]

changed = []
for pattern in ROOTS:
    for path in glob.glob(pattern):
        name = os.path.basename(os.path.dirname(path))
        if name not in ALLOW:
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        head, sep, rest = text.partition("\n---")
        if not sep:
            continue
        new_head = re.sub(r"^disable-model-invocation:\s*true\s*$", "disable-model-invocation: false", head, flags=re.M)
        if new_head != head:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_head + sep + rest)
            changed.append(name)
if changed and "--quiet" not in sys.argv:
    print("skill_autoinvoke: enabled model invocation for " + ", ".join(sorted(changed)), file=sys.stderr)
