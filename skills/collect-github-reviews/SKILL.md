---
name: style
description: Generate, apply, and review code using style profiles learned from GitHub PR reviews.
---

# Overview

Analyze GitHub PR review comments to learn coding styles, then apply that knowledge when writing or reviewing code.

**Subcommands:**
- `profile` - Generate style profile from collected reviews
- `apply` - Write code following a style profile
- `review` - Review code using a style profile

# Prerequisites

Collect review data first using the `collect-github-reviews` CLI:

```bash
# Collect reviews by a specific user
collect-github-reviews user <username> <repos...>

# Collect all reviews from a repository
collect-github-reviews repo <repos...>

# Collect repository style files (.editorconfig, treefmt, etc.)
collect-github-reviews repo-style <repos...>
```

Data is stored in `~/.local/share/github-reviews/`.

# Usage

## Generate Profile

```
/style profile Mic92                        # User profile
/style profile numtide/llm-agents.nix       # Repo profile
/style profile Mic92@numtide/llm-agents.nix # Combined profile
/style profile --view Mic92                 # View without regenerating
```

### Profile Generation Process

**For User Profiles:**
1. Read reviews from `~/.local/share/github-reviews/users/<user>/`
2. Analyze review patterns across all repos
3. Generate `_profile.md` in the same directory

**For Repo Profiles:**
1. Read reviews from `~/.local/share/github-reviews/repos/<repo>/reviews/`
2. Read style files from `~/.local/share/github-reviews/repos/<repo>/style/`
3. Generate `_profile.md` in the repo directory

**For Combined Profiles:**
1. Read user reviews in that specific repo
2. Combine with repo style
3. Generate in `~/.local/share/github-reviews/combined/<user>@<repo>/`

### Analysis Guidelines

**User Profiles - Analyze:**
- Common feedback patterns (what they often point out)
- Preferred coding style (naming, structure, patterns)
- Review tone and communication style
- Specific technical preferences (libraries, approaches)
- Before/after code examples from their suggestions

**Repo Profiles - Analyze:**
- Code conventions from style files (.editorconfig, treefmt, etc.)
- Common review themes from all reviewers
- Project-specific patterns and idioms
- Language-specific conventions

## Apply Style

```
/style apply Mic92                           # Apply user style
/style apply numtide/llm-agents.nix          # Apply repo style
/style apply Mic92@numtide/llm-agents.nix    # Apply combined style
/style apply Mic92 src/main.rs               # Apply to specific file
```

### Behavior

1. Read the profile from `_profile.md`
2. For new code: Follow patterns, naming, structure preferences
3. For existing code: Suggest changes that align with profile
4. Explain reasoning for style choices

## Review Code

```
/style review Mic92                          # Review current file
/style review Mic92 src/lib.rs               # Review specific file
/style review numtide/llm-agents.nix         # Review against repo conventions
/style review Mic92@numtide/llm-agents.nix   # Combined perspective
```

### Behavior

1. Read the profile from `_profile.md`
2. Analyze code against profile patterns
3. Flag anti-patterns the profiled user typically catches
4. Suggest improvements in their style
5. Acknowledge good patterns that match the profile

### Output Format

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

# Profile Locations

| Type | Path |
|------|------|
| User | `~/.local/share/github-reviews/users/<user>/_profile.md` |
| Repo | `~/.local/share/github-reviews/repos/<owner_repo>/_profile.md` |
| Combined | `~/.local/share/github-reviews/combined/<user>@<owner_repo>/_profile.md` |

# Profile Format

```markdown
# [User/Repo] Style Profile

## Summary
Brief description of overall style/approach.

## Key Patterns
- Pattern 1: Description with example
- Pattern 2: Description with example

## Code Preferences

### Naming
- ...

### Structure
- ...

### Error Handling
- ...

## Common Review Feedback
Typical comments and what triggers them.

## Examples

### Before (flagged in review)
```
code example
```

### After (approved)
```
improved code
```

## Anti-patterns
Things this user/repo avoids.
```
