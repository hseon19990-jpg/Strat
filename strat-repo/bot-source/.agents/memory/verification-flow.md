---
name: Verification completion flow
description: Completion callbacks may arrive after the original user interaction, so durable request context must be stored with the submission.
---

The rule: when a verification flow needs follow-up input after a callback, persist the request identifier and user-provided note with the submission rather than relying only on transient user-session state.

**Why:** Telegram callbacks and later messages can be separated by a session restart or a different entry point; database-backed context prevents lost notes and mismatched requests.

**How to apply:** Use the submission ID to validate ownership and status, then write the optional note transactionally with the owner notification.
