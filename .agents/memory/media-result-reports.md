---
name: Media result reports
description: Persistence and navigation behavior for account story/avatar operation results.
---

The owner-facing story and avatar operations keep their latest success and failure results in the existing settings store. Failed entries retain both the account number and the exception reason, and the owner can browse them from the account information menu.

**Why:** Upload workflows can finish or be interrupted after processing many accounts; a transient Telegram message is not enough to audit which numbers succeeded or why others failed.

**How to apply:** Preserve separate report keys for stories and avatars, save progress after each batch, and keep paginated success/failure views behind the account information report button.