---
name: style-review
description: Review code using a learned style profile. Provides feedback as if from the profiled user or following repo conventions.
---

# Overview

Reviews code through the lens of a learned style profile, providing feedback consistent with how that user reviews or what the repo expects.

# Prerequisites

A style profile must exist. Generate with `/style-profile`.

# Usage

```
/style-review Mic92                          # Review current file as Mic92 would
/style-review Mic92 src/lib.rs               # Review specific file
/style-review numtide/llm-agents.nix         # Review against repo conventions
/style-review Mic92@numtide/llm-agents.nix   # Combined perspective
```

# Output Format

```markdown
## Style Review: [Profile Name]

### Issues Found

1. **[Category]** Line X-Y
   - Problem: Description
   - Suggestion: How to fix
   - Reference: Similar feedback from profile

### Good Patterns

- Line X: Follows [pattern] correctly

### Summary

Overall assessment and priority fixes.
```

# Behavior

1. Read the profile from `_profile.md`
2. Analyze code against profile patterns
3. Flag anti-patterns the profiled user typically catches
4. Suggest improvements in their style
5. Acknowledge good patterns that match the profile

# Profile Locations

- User: `~/.local/share/github-reviews/users/<user>/_profile.md`
- Repo: `~/.local/share/github-reviews/repos/<repo>/_profile.md`
- Combined: `~/.local/share/github-reviews/combined/<user>@<repo>/_profile.md`
