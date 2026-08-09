---
name: Telegram media batches
description: Handling Telegram albums and multi-photo uploads in the bot.
---

Telegram albums are delivered as separate photo updates that share a media-group identifier, so a handler that processes each update immediately cannot reliably treat an album as one batch.

**Why:** Batch workflows need all photos from a user-selected album before assigning work, while rapid later batches must preserve the existing queue position.

**How to apply:** Buffer updates by `(user_id, media_group_id)`, debounce briefly, then process the collected file IDs under a per-user lock. Keep the work queue fixed for the operation so later batches continue without repeating earlier targets.