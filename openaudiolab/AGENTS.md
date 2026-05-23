# OpenAudiolab Agent Instructions

This file contains mandatory instructions for all human developers and AI development agents working on OpenAudiolab.

---

## Core Rules

Every agent and developer MUST:

1. Read `OPENAUDIOLAB_MASTER_PLAN.md` before making any changes.
2. Follow the current backend-first build priority.
3. Preserve the modular job pipeline.
4. Preserve remote worker support.
5. Preserve cloud GPU worker support.
6. Preserve storage abstraction.
7. Preserve default 7-day file retention.
8. Preserve model-pack abstraction.
9. Preserve lyric reasoning for AI-generated lyrics.
10. Preserve custom lyric pass-through behavior.
11. Do NOT build a polished final UI before backend orchestration works.
12. Do NOT hardcode a single model as the entire platform.
13. Do NOT assume local GPU availability.
14. Do NOT store generated files permanently.
15. Do NOT remove queue, worker, storage, security, or model-pack abstractions.
16. Do NOT ship unsafe default production credentials.
17. Append a task entry to `DEVELOPMENT_LOG.md` before considering the task complete.

---

## A task is not complete until DEVELOPMENT_LOG.md has been updated.

---

## Development Log Format

Every log entry in `DEVELOPMENT_LOG.md` must use this template:

```markdown
---

## YYYY-MM-DD HH:MM UTC — Task Title

**Developer/Agent:** Name or tool
**Task Type:** Planning / Backend / Worker / Frontend / Storage / Docs / Infra / Bugfix / Test
**Task Objective:** Brief explanation of what this task was meant to accomplish.

### Files Created

- `path/to/file`

### Files Modified

- `path/to/file`

### Files Deleted

- `path/to/file`

### Summary of Changes

- Clear bullet explaining what changed.
- Clear bullet explaining why it changed.

### Architecture / Pipeline Impact

- Describe whether this changed backend architecture, worker behavior, storage, pipeline stages, model packs, security, or frontend behavior.
- If no architecture impact, write: `None`.

### Tests / Checks Performed

- `command run`
- Result: passed / failed / not run

### Known Issues

- Any incomplete work, bugs, placeholders, or risks.
- If none, write: `None known`.

### Follow-Up Tasks

- Recommended next task.
- Required cleanup.
- Needed tests.

### Source-of-Truth Updates

- `OPENAUDIOLAB_MASTER_PLAN.md`: updated / not updated
- `AGENTS.md`: updated / not updated
- `openaudiolab.manifest.json`: updated / not updated

---
```

---

## Security Rules

- Never commit real API keys, storage credentials, or cloud provider tokens
- Never ship production credentials like admin@openaudiolab.io / admin123
- Passwords must be hashed (bcrypt/argon2); never stored plaintext
- Never log passwords
- Never expose password hashes
- Validate password length and reject common placeholders
- Minimum password: 12 characters
- Reject: admin123, password, changeme, test123, or similar placeholders
- Secrets loaded from environment only
- No stack traces or secrets exposed in production

---

## Lyric Rules

- Custom lyrics (`lyrics_mode=provided`) are preserved EXACTLY as submitted
- Do NOT rewrite, humanize, correct grammar, change rhymes, change section order, remove lines, add lines, replace words, improve cadence, change spelling, or sanitize style
- User-provided lyrics are intentional creative input
- Lyric reasoning runs for AI-generated and hybrid lyrics only (unless explicitly configured otherwise)
- Do NOT create misleading `lyrics_humanized.txt` for untouched custom lyrics

---

## Worker Rules

- Worker registration requires `WORKER_REGISTRATION_TOKEN`
- Do NOT allow anonymous workers to poll jobs
- Local and remote workers use the same protocol
- Workers support drain mode and update signaling

---

## Storage Rules

- Generated files are private by default
- No public directory browsing
- Signed/download-controlled access required
- Default retention: 7 days
- Storage is adapter-based

---

## Model Rules

- Backend must remain model-agnostic
- Do NOT hardcode a single model as the entire platform
- All models exposed through worker capabilities, model-pack manifests, registry entries, exact versions, license statuses, and VRAM requirements
- Official containers must NOT bundle model weights unless redistribution rights are verified
- Allowed license statuses: `verified`, `needs_review`, `not_allowed`, `user_supplied_only`

---

## Frontend Rules

- After job submission, frontend MUST redirect to `/jobs/{job_id}`
- Do NOT leave the user on the form after submission
- Setup page exists at `/setup`
- Login page supports authenticated login
- Job progress page shows stage-by-stage progress

---

## Setup Rules

- Setup can only be completed once
- After setup, `/api/setup/initialize` refuses to run again
- Additional admin creation requires authenticated admin action
- Production mode requires setup; dev-only credentials only if `APP_ENV=development` AND `SEED_DEV_ADMIN=true`
