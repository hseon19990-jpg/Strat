---
name: GitHub push authentication
description: Reliable GitHub HTTPS push flow and handling of pre-existing remote commits.
---

GitHub personal access tokens work for HTTPS pushes when supplied through Git's credential prompt as the password with a non-empty username such as `x-access-token`; a `Bearer` HTTP header is not a reliable substitute for Git's normal authentication flow.

**Why:** An initial header-based attempt reported invalid credentials even though the token was valid; the credential-prompt flow authenticated successfully. The remote also had commits that required a normal fetch and merge before pushing.

**How to apply:** Never print or persist the token. Fetch first, inspect divergence, merge remote changes without force-pushing, then push with a temporary askpass helper or the managed GitHub integration. Always compare the local HEAD SHA with `git ls-remote` afterward; a managed push can report success without advancing the remote.