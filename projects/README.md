# Durable per-project work checkpoints

**CHECKS PENDING:** Folder convention only, not automatically read by scheduled ChatGPT tasks or installed into HA's runtime. Do not put credentials, private conversation identifiers, protected evaluator cases, unauthorized source text, or complete RE-Wizard textbooks in this public repository.

Create one **projects/<slug>/** directory per separately authorized project, containing README.md (mission, acceptance criteria, resources, safety and permissions); state/current.json (compact authoritative milestone and revision); state/handoff.md (only latest changed outputs, blockers and next action); state/automations.json (allowlisted task identifiers/roles/permissions, with no unapproved private data); decisions.md (consequential durable decisions); evidence/ (source-pinned tests/check results). Use archives for old state, but do not inject them into every new chat.

**Read sequence per scheduled run:** exact task prompt (immutable rules) → project README → current.json → handoff.md → only the evidence and source sections required for the next milestone. A GitHub update does not force scheduled tasks to reread it; prompts must explicitly request retrieval using actually connected, authorized tools. If that fails, mark the work blocked rather than invent a state.

Check project writer leases/revisions before modifying shared state. For multi-worker work use a single integrator or separate branches/PRs; do not allow last writer wins. Track exact source commit and run IDs privately as needed for task coordination, never blindly expose account identifiers in public Git.

**Starter project:** [Hivemind Assembly](hivemind-assembly/README.md). Broader policy: [Conductor](../dev/continuous_execution/CONDUCTOR.md), [Chat Mode skill](../skills/chatmode-scheduled-orchestration/SKILL.md).
