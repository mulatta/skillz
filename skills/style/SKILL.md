---
name: style
description: Analyze and apply coding styles from GitHub PR data using ast-grep, ck, and qmd
---

# Overview

Analyze coding styles from PR data (code changes, reviews, diffs) and apply that knowledge when writing or reviewing code.

**Commands:**
- `profile` - Generate style profile from collected PR data
- `apply` - Write code following a style profile
- `review` - Review code using a style profile (replaces /code-review)

# Data Source

**style-review CLI** collects PR data:

```bash
# Collect PRs by author
style-review collect NixOS/nixpkgs --author GaetanLepage --limit 20

# Collect PRs by reviewer
style-review collect NixOS/nixpkgs --reviewer SomeoneSerge --limit 20

# Query database
style-review query "SELECT * FROM pr_participants WHERE user='ConnorBaker'"
```

**Storage:** `~/.local/share/style-review/`

```
~/.local/share/style-review/
├── style-review.db          # SQLite: PR metadata, participants, comments
├── files/<repo>/pr{N}/
│   ├── meta.json            # PR metadata
│   ├── code/                # Changed source files
│   ├── diffs/               # Patch files (*.patch)
│   └── docs/
│       ├── summary.md       # PR description
│       ├── comments/        # Review comments
│       └── reviews/         # Review summaries
└── users/<user>/
    └── _profile.md          # Generated profile (cached)
```

# Analysis Tools

| Tool | Source | Purpose |
|------|--------|---------|
| ast-grep | Plugin | Structural code pattern analysis |
| ck | MCP | Semantic code search, similar pattern finding |
| qmd | MCP | Review comment and documentation search |

# Commands

## /style profile <user>

Generate a style profile for a user.

**Process:**

1. Query DB for user's PRs:
   ```bash
   style-review query "
     SELECT p.file_path FROM prs p
     JOIN pr_participants pp ON p.id = pp.pr_id
     WHERE pp.user = '<user>'
   "
   ```

2. Analyze diffs with ast-grep:
   ```bash
   # Find finalAttrs usage
   ast-grep --pattern 'buildPythonPackage (finalAttrs: { $$$ })' ~/.local/share/style-review/files/

   # Find env.* pattern
   ast-grep --pattern 'env.$VAR = $VAL' ~/.local/share/style-review/files/
   ```

3. Search similar patterns with ck:
   ```
   ck semantic_search "finalAttrs pattern nix" ~/.local/share/style-review/files/
   ```

4. Search review comments with qmd:
   ```
   qmd query "redundant" --collection style-review
   ```

5. Generate `_profile.md` in `users/<user>/`

**Options:**
- `--force` - Regenerate even if profile exists
- `--view` - View existing profile without regenerating

## /style apply <user> [file]

Write code following the user's style.

**Process:**

1. Read profile from `users/<user>/_profile.md`
2. Apply patterns from "Writing Style" section
3. Follow naming conventions, structure patterns
4. Avoid anti-patterns listed in profile

## /style review <user> [file|--pr N]

Review code using the user's review style. Replaces `/code-review`.

**Process:**

1. Read profile from `users/<user>/_profile.md`
2. Apply patterns from "Review Style" section
3. Check for issues the user typically points out
4. Use their review tone and suggestion format

**Options:**
- `--pr N` - Review entire PR

# Profile Format

```markdown
# {User} Style Profile

## Summary
Brief description and technical domains.

## Data Sources
- Authored PRs: N (repos)
- Reviews given: N
- Reviews received: N

---

## Writing Style
For `/style apply`. How to write code like this user.

### Structural Patterns
ast-grep detectable patterns with examples.

### Naming Conventions
File naming, variable naming rules.

### Code Structure
Organization patterns, module structure.

### Anti-patterns
Things to avoid.

---

## Review Style
For `/style review`. How to review like this user.

### What They Point Out
Common issues they flag with examples.

### Review Tone
Communication style, directness level.

### Before/After Examples
Concrete examples from their reviews.

---

## Cross-Validation
Related reviewers and their interaction patterns.
```

# ast-grep Patterns for Nix

Common patterns to detect:

```yaml
# finalAttrs pattern
rule:
  pattern: buildPythonPackage (finalAttrs: { $$$ })

# env attribute usage
rule:
  pattern: env.$NAME = $VALUE

# lib.optionals
rule:
  pattern: lib.optionals $COND $LIST

# pythonImportsCheck
rule:
  pattern: pythonImportsCheck = [ $$$ ]
```

# Example Workflow

```bash
# 1. Collect data
style-review collect NixOS/nixpkgs --author ConnorBaker --limit 20
style-review collect NixOS/nixpkgs --reviewer SomeoneSerge --limit 20

# 2. Generate profile (in Claude)
/style profile ConnorBaker

# 3. Apply style when writing
/style apply ConnorBaker

# 4. Review code
/style review SomeoneSerge src/foo.nix
```
