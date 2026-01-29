---
name: style-apply
description: Apply a learned code style profile to current code. Use when writing new code or refactoring to match a specific user's or repository's conventions.
---

# Overview

Applies a previously generated style profile to code you're writing or modifying.

# Prerequisites

A style profile must exist. Generate with `/style-profile`.

# Usage

```
/style-apply Mic92                           # Apply user style
/style-apply numtide/llm-agents.nix          # Apply repo style
/style-apply Mic92@numtide/llm-agents.nix    # Apply combined style
/style-apply Mic92 src/main.rs               # Apply to specific file
```

# Behavior

1. Read the profile from `_profile.md`
2. For new code: Follow patterns, naming, structure preferences
3. For existing code: Suggest changes that align with profile
4. Explain reasoning for changes

# Profile Locations

- User: `~/.local/share/github-reviews/users/<user>/_profile.md`
- Repo: `~/.local/share/github-reviews/repos/<repo>/_profile.md`
- Combined: `~/.local/share/github-reviews/combined/<user>@<repo>/_profile.md`
