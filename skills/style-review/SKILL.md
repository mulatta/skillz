---
name: style-review
description: Access GitHub PR data (code, reviews, diffs) for coding style analysis
---

# Overview

Query collected PR data and search code/comments to understand coding styles.

- `style-review` - metadata queries (SQL)
- `ck` / `ast-grep` - code search
- `qmd` - review comment search

Data path: `~/.local/share/style-review/files/`

# Data Collection

```bash
style-review collect NixOS/nixpkgs --author ConnorBaker --limit 50
style-review collect NixOS/nixpkgs --reviewer ConnorBaker --limit 30
```

# Metadata Query

```bash
# PR list by user
style-review query "SELECT p.file_path, p.title FROM prs p
  JOIN pr_participants pp ON p.id = pp.pr_id
  WHERE pp.user = 'ConnorBaker' AND pp.role = 'author'"

# Review statistics
style-review query "SELECT reviewer, state, COUNT(*) FROM reviews
  WHERE pr_author = 'ConnorBaker' GROUP BY reviewer, state"

# Cross-validation (who reviews whom)
style-review query "SELECT reviewer, pr_author, COUNT(*) FROM reviews
  WHERE reviewer <> pr_author GROUP BY reviewer, pr_author ORDER BY 3 DESC LIMIT 10"
```

# Code Search

```bash
# Semantic search
ck --sem "strictDeps finalAttrs" ~/.local/share/style-review/files/

# Pattern search
ast-grep --pattern "finalAttrs: { $$$ }" ~/.local/share/style-review/files/
ast-grep --pattern "__structuredAttrs = true" ~/.local/share/style-review/files/
ast-grep --pattern "strictDeps = true" ~/.local/share/style-review/files/
```

# Comment Search

```bash
# Review comments
qmd query "strictDeps" ~/.local/share/style-review/files/
qmd query "missing meta.teams" ~/.local/share/style-review/files/
```

# Schema

| Table | Key Columns |
|-------|-------------|
| prs | id, file_path, title, state |
| pr_participants | pr_id, user, role |
| reviews | pr_id, reviewer, pr_author, state, body |
| comments | pr_id, author, body, file_path, comment_type |

# File Structure

```
~/.local/share/style-review/files/<owner_repo>/pr<N>/
├── code/           # Source files
├── diffs/          # Patch files
└── docs/
    ├── summary.md
    ├── comments/   # Line-level review comments
    └── reviews/    # Review summaries
```
