# SKILL.md Authoring Guide — How to Write Instructions That LLMs Actually Follow

## Core Principle
LLMs skip steps, take shortcuts, and assume success. Your SKILL.md must be written defensively — assume the agent will try to do the minimum unless explicitly prevented.

## 1. Verification Over Assumption
Never write "install X, then continue." Write "install X, verify it works (run: command), do NOT continue until verification passes."
- Bad: "Run palaia init. Done."
- Good: "Run palaia init. Then run palaia status. Check that it shows your agent name. If it does not, stop and troubleshoot."
- Agents will say "setup complete" without checking. The word "mandatory" is not enough — you need a concrete verification command and a pass/fail criterion.

## 2. Step-by-Step Communication Requirements
Agents go silent during multi-step operations. Users think it crashed.
- Require status messages after each step: "After each major step, send a brief status message."
- Give example pacing: "Installing... Done. Configuring... Done. Warming up (15s)... Ready."
- Explicitly forbid batching: "Do not batch all steps and report at the end."

## 3. Troubleshooting Sections for Every Failure Mode
If something CAN fail, write the fix into the SKILL.md. Agents cannot Google solutions.
- pip not found? Give 4 fallback options in order.
- Permission denied? Give the --break-system-packages flag.
- Provider slow? Explain why and give the alternative.
- Each troubleshooting block: symptom, cause, fix command. No prose.

## 4. Explicit "Do Not Skip" Markers
Agents treat unlabeled steps as optional. Mark critical steps:
- "(mandatory — do not skip)"
- "(REQUIRED — do not skip)"
- "do NOT proceed until..."
- Steps without these markers WILL be skipped by low-reasoning models.

## 5. Self-Healing Hooks
postInstall/postUpdate commands must handle missing tools gracefully:
- Bad: "npm install -g package && palaia doctor"
- Good: "(npm install -g package 2>/dev/null || true) && palaia doctor"
- If one part fails, the rest must still run. Agents on unknown hosts have unknown tools.

## 6. The Universal Install Prompt Pattern
Write ONE prompt that works for both first install and update:
- "Install or update X to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run [init command], then [health check] and resolve all warnings — do not stop until [health check] is clean."
- This prompt goes in the README and is the primary onboarding path.
- It must work when copy-pasted by a human who does not understand the tool.

## 7. Show Bad Examples, Not Just Good Ones
Agents learn from contrast. Show what NOT to do:
- Bad: "palaia write Working on the API"
- Good: "palaia write API auth module: implementing JWT refresh, blocked on race condition, next: add mutex --project myapp --tag active-work"
- The bad example prevents the most common mistake. Without it, agents default to the lazy version.

## 8. Auto-Check on Load
Add an instruction block at the top of SKILL.md that runs a health check every time the skill is loaded:
- "Before doing anything else with [tool], run [doctor command] silently. If it reports ANY warnings, address them immediately."
- This catches version mismatches, stale configs, and broken setups before they cause problems downstream.

## 9. Multi-Component Update Awareness
If your tool has multiple installable parts (CLI, plugin, skill file), document ALL update paths in one place:
- Agents update what they know about and ignore the rest.
- "Update ALL of them — they version independently" with numbered steps.
- postUpdate hooks should cover as many components as possible.

## 10. Provider/Platform-Specific Warnings
Different environments behave differently. Call out gotchas explicitly:
- "uv removes packages not in the dependency spec on upgrade. Always use [full spec]."
- "sentence-transformers on CPU takes 16s per embedding. Use fastembed instead."
- "On Debian 12+, pip fails with PEP 668 error. Use --break-system-packages."
- Agents cannot infer these — they must be stated.

## 11. Session Continuity Instructions
Tell agents what to do at session start and end:
- Start: "Run health check, query for active work, check inbox"
- End: "Write current state with exact step, blocker, next action"
- Without this, agents start fresh every session and lose continuity.

## 12. Defensive Defaults
Assume the worst about the environment:
- pip might not exist. Provide alternatives.
- npm might not exist. Make it optional.
- Internet might be slow. Support offline fallbacks.
- The agent might be GPT on low thinking. Keep instructions atomic and unambiguous.

## Meta-Rule
If an instruction requires interpretation, it will be interpreted wrong by at least one model. Make everything concrete, testable, and binary (pass/fail). Prose is for humans. SKILL.md is for machines that pretend to be humans.