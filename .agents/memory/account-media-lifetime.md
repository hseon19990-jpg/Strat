---
name: Account media lifetime
description: The permanent uniqueness rule for story and avatar distribution.
---

Each account may receive at most one story and at most one avatar for its lifetime. The uniqueness record must survive retries, restarts, and replacing a stock row with the same phone number.

**Why:** The distribution flow previously tracked progress only in transient owner-session state, so starting a new operation returned accounts that had already received media.

**How to apply:** Keep the durable assignment record keyed by media type plus account identity, seed it from historical successful/progress reports, and use an atomic claim before sending media.