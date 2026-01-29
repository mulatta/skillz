---
name: style-profile
description: Generate or view code style profiles from collected GitHub reviews. Use when learning coding patterns from specific users or repositories.
---

# Overview

Analyzes collected GitHub reviews to create style profiles for:
- **User profiles**: How a specific reviewer gives feedback
- **Repo profiles**: Project conventions from all reviewers
- **Combined profiles**: User style in a specific repo context

# Prerequisites

Reviews must be collected first:
```bash
collect-github-reviews --user <username> <repos...>
collect-github-reviews --repo <repo>
collect-github-reviews --repo-style <repo>
```

Data location: `~/.local/share/github-reviews/`

# Usage

## Generate User Profile

```
/style-profile Mic92
```

1. Read reviews from `~/.local/share/github-reviews/users/Mic92/`
2. Analyze review patterns across all repos
3. Generate `~/.local/share/github-reviews/users/Mic92/_profile.md`

## Generate Repo Profile

```
/style-profile numtide/llm-agents.nix
```

1. Read reviews from `~/.local/share/github-reviews/repos/numtide_llm-agents.nix/reviews/`
2. Read style files from `~/.local/share/github-reviews/repos/numtide_llm-agents.nix/style/`
3. Generate `~/.local/share/github-reviews/repos/numtide_llm-agents.nix/_profile.md`

## Generate Combined Profile

```
/style-profile Mic92@numtide/llm-agents.nix
```

1. Read user reviews in that specific repo
2. Combine with repo style
3. Generate `~/.local/share/github-reviews/combined/Mic92@numtide_llm-agents.nix/_profile.md`

## View Existing Profile

```
/style-profile --view Mic92
```

Display the profile without regenerating.

# Profile Generation Guidelines

When generating a profile, analyze:

## For User Profiles
- Common feedback patterns (what they often point out)
- Preferred coding style (naming, structure, patterns)
- Review tone and communication style
- Specific technical preferences (libraries, approaches)
- Examples of before/after code changes they suggested

## For Repo Profiles
- Code conventions from style files (.editorconfig, treefmt, etc.)
- Common review themes from all reviewers
- Project-specific patterns and idioms
- Language-specific conventions used

## Profile Format

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
\`\`\`
code example
\`\`\`

### After (approved)
\`\`\`
improved code
\`\`\`

## Anti-patterns
Things this user/repo avoids.
```

# Output

Profiles are saved as `_profile.md` in the respective data directory and can be referenced by other skills like `/style-apply` and `/style-review`.
