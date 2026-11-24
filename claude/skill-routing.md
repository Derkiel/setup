# Skill routing: pick skills yourself, don't wait for /commands

The user does not want to remember skill names. When a situation below matches, invoke the skill with the Skill tool before starting the work, and say in one line which skill you are using. Use at most one workflow skill per step; do not chain skills the task does not need. A small, obvious change needs no skill at all.

Everything named here is installed by `install.sh` in the setup repo. Plugin skills are called as `<plugin>:<name>` (for example `mattpocock-skills:tdd`).

## Deciding what to build

- Vague or large request, or a plan with unresolved branches: `mattpocock-skills:grill-me`. If the repo has docs or ADRs: `mattpocock-skills:grill-with-docs`.
- A discussion that produced decisions: `mattpocock-skills:to-spec`. A spec that needs breaking down: `mattpocock-skills:to-tickets`.
- Work too big for one session: `mattpocock-skills:wayfinder`.
- A question that needs facts from primary sources before deciding: `mattpocock-skills:research`.
- A design question that needs a throwaway build to answer: `mattpocock-skills:prototype`.

## Building and fixing

- New behaviour with tests, or a bug fix that should stay fixed: `mattpocock-skills:tdd`.
- Hard bug, flaky test, performance regression: `mattpocock-skills:diagnosing-bugs`.
- Reviewing a diff or branch: the built-in `/code-review`, or `mattpocock-skills:code-review` when the repo has written coding standards or a spec to check against.
- Writing a PR body: `mattpocock-skills:pr`.
- Designing a module's interface or deciding where a seam goes: `mattpocock-skills:codebase-design`. Naming things, glossary, ADRs: `mattpocock-skills:domain-modeling`.
- Steps only the human can do (credentials, dashboards, one-off cutovers): `mattpocock-skills:wizard`.
- Library or framework API you are not sure about: the context7 MCP tools, not memory.

## Frontend

- Any UI building: `frontend-design:frontend-design`. Polish details: `emil-design-eng`.
- Several UI variants to compare: `prototype` (the user-level one, from Emil Kowalski), then show them with `ask-ui`.
- Motion: `animate` to build it, then `review-animations`; jank or dropped frames: `animation-performance`. Gesture-driven or Apple-style interaction: `apple-design`.
- UI review: `web-design-guidelines`. Edge-case stress test: `break-ui`.
- React or Next.js performance: `vercel-react-best-practices`. Component API shape: `vercel-composition-patterns`.

## Asking the user and showing work

- Anything the user must choose by looking (design directions, variants, A/B picks, audit findings to fix), or more than a few fields of input: `ask-ui`, with the recommended option preselected. Plain text only for open-ended questions.
- The user says "what?" or did not get your last message: `mattpocock-skills:wait-what`.
- The user wants to learn something over time: `mattpocock-skills:teach`.

## Browser

- Checking a page you built, taking screenshots, reading a page that needs a real browser: the Playwright MCP tools (`mcp__playwright__*`).
- Long scripted flows, Electron apps, or when the Playwright MCP is not connected: `agent-browser`. Its own description says to prefer it over built-in browser tools; this file overrides that.

## Session and project upkeep

- Session is long or about to end with work unfinished: `mattpocock-skills:handoff`.
- CLAUDE.md is messy or out of date: `claude-md-management:revise-claude-md`. Writing or editing a skill or agent instructions: `mattpocock-skills:writing-for-agents`; building a new skill: `skill-creator:skill-creator`.
- A question about Claude Code itself: the `claude-code-guide` agent.

## Only when the user asks

`mattpocock-skills:improve-codebase-architecture`, `to-questionnaire`, `implement`, `implement-spec`, `triage`, `retro`, `setup-matt-pocock-skills`, and everything under the plugin's `misc/`.

## Always on, nothing to invoke

caveman (terse replies) and ponytail (smallest complete change) are switched on by their session-start hooks. rtk rewrites Bash commands through a hook to shorten their output; if a command's output looks cut where you need the detail, run it as `rtk bypass <command>` to see it whole.
