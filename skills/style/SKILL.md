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

# Data Collection

**style-review CLI** collects PR data. Two modes:

| Mode         | Purpose          | Data Quality                         |
| ------------ | ---------------- | ------------------------------------ |
| `--author`   | Writing patterns | Code samples, PR descriptions        |
| `--reviewer` | Review patterns  | Feedback comments, approval patterns |

```bash
# Writing style: collect authored PRs
style-review collect NixOS/nixpkgs --author ConnorBaker --limit 50 --since 1y

# Review style: collect reviewed PRs (higher quality feedback)
style-review collect NixOS/nixpkgs --reviewer SomeoneSerge --limit 50 --since 1y

# Both modes for complete profile
style-review collect NixOS/nixpkgs --author ConnorBaker --limit 30
style-review collect NixOS/nixpkgs --reviewer ConnorBaker --limit 30
```

**Storage:** `~/.local/share/style-review/`

```
~/.local/share/style-review/
├── style-review.db          # SQLite: PRs, reviews, comments, cross-validation
├── files/<owner_repo>/pr{N}/   # e.g., pytorch_pytorch/pr123
│   ├── meta.json
│   ├── code/                # Changed source files
│   ├── diffs/               # Patch files
│   └── docs/
│       ├── summary.md       # PR description
│       ├── comments/        # Line-level review comments (with code context)
│       ├── reviews/         # Review summaries
│       └── discussion/      # General PR discussion
└── users/<user>/
    └── _profile.md          # Generated profile (cached)
```

# Recommended Data Sources

**Best repos** (strong review culture with detailed feedback):

| Repo          | Domain       | Good Reviewers                             |
| ------------- | ------------ | ------------------------------------------ |
| NixOS/nixpkgs | Nix packages | SomeoneSerge, ConnorBaker, SuperSandro2000 |
| NixOS/nix     | Nix core     | edolstra, roberth                          |

**Note:** CHANGES_REQUESTED is rarely used. Real feedback is in **line comments** and **COMMENTED** reviews.

# Quality Metrics

Check data quality before generating profiles:

```bash
# Overall stats
style-review query "SELECT
  (SELECT COUNT(*) FROM prs) as prs,
  (SELECT COUNT(*) FROM reviews) as reviews,
  (SELECT COUNT(*) FROM comments WHERE comment_type='line_comment') as line_comments,
  (SELECT COUNT(*) FROM reviews WHERE state='CHANGES_REQUESTED') as changes_req"

# Reviewer activity - all feedback types matter
style-review query "SELECT reviewer, COUNT(*) as reviews,
  SUM(CASE WHEN state='APPROVED' THEN 1 ELSE 0 END) as approved,
  SUM(CASE WHEN state='CHANGES_REQUESTED' THEN 1 ELSE 0 END) as changes_req,
  SUM(CASE WHEN state='COMMENTED' THEN 1 ELSE 0 END) as commented
  FROM reviews WHERE reviewer <> pr_author
  GROUP BY reviewer ORDER BY reviews DESC LIMIT 10"

# Line comments by author (detailed feedback)
style-review query "SELECT c.author, COUNT(*) as line_comments
  FROM comments c WHERE c.comment_type = 'line_comment'
  GROUP BY c.author ORDER BY line_comments DESC LIMIT 10"

# Cross-validation: who reviews whom
style-review query "SELECT reviewer, pr_author, COUNT(*) as reviews
  FROM reviews WHERE reviewer <> pr_author
  GROUP BY reviewer, pr_author ORDER BY reviews DESC LIMIT 10"
```

**Judgment criteria** (reviewers have different styles - use all signals):

| Signal            | Meaning                                    |
| ----------------- | ------------------------------------------ |
| CHANGES_REQUESTED | Explicit rejection with required fixes     |
| COMMENTED         | Feedback without formal approval/rejection |
| line_comments     | Specific code-level feedback with context  |

| Metric                                                         | Minimum | Good |
| -------------------------------------------------------------- | ------- | ---- |
| PRs per user                                                   | 20      | 50+  |
| Total feedback (line_comments + COMMENTED + CHANGES_REQUESTED) | 30      | 100+ |
| Cross-validation pairs                                         | 5       | 20+  |

# Analysis Tools

| Tool     | Source | Purpose                                       |
| -------- | ------ | --------------------------------------------- |
| ast-grep | Plugin | Structural code pattern analysis              |
| ck       | MCP    | Semantic code search, similar pattern finding |
| qmd      | MCP    | Review comment and documentation search       |

# Commands

## /style profile <user>

Generate a style profile for a user.

**Process:**

1. **Query user data:**

   ```bash
   # Authored PRs (writing style)
   style-review query "SELECT p.file_path, p.title FROM prs p
     JOIN pr_participants pp ON p.id = pp.pr_id
     WHERE pp.user = '<user>' AND pp.role = 'author'"

   # Reviews given (review style)
   style-review query "SELECT pr_author, state, COUNT(*) FROM reviews
     WHERE reviewer = '<user>' GROUP BY pr_author, state"

   # Who reviews this user (cross-validation)
   style-review query "SELECT reviewer, COUNT(*) as cnt,
     SUM(CASE WHEN state='APPROVED' THEN 1 ELSE 0 END) as approved
     FROM reviews WHERE pr_author = '<user>'
     GROUP BY reviewer ORDER BY cnt DESC"
   ```

2. **Analyze code patterns with ast-grep:**

   First, get user's PR directories:
   ```bash
   USER_DIRS=$(style-review query "SELECT file_path FROM prs p
     JOIN pr_participants pp ON p.id = pp.pr_id
     WHERE pp.user = '<user>' AND pp.role = 'author'" --format tsv | tail -n +2)
   ```

   Then run pattern detection on each directory:
   ```bash
   CODE_BASE=~/.local/share/style-review/files

   # Pattern detection with frequency count
   for pattern in \
     'finalAttrs: { $$$ }' \
     '__structuredAttrs = true' \
     'strictDeps = true' \
     'inherit ($LIB) $$$NAMES;' \
     'lib.optionals $COND $LIST' \
     'buildPythonPackage $ARGS' \
     'mkDerivation $ARGS'; do
     echo "=== $pattern ==="
     ast-grep --pattern "$pattern" "$CODE_BASE" --json 2>/dev/null | jq -s 'length'
   done
   ```

   **Standard patterns to detect:**

   | Pattern | Meaning | Indicates |
   |---------|---------|-----------|
   | `finalAttrs: { $$$ }` | finalAttrs pattern | Modern Nix style |
   | `__structuredAttrs = true` | Structured attrs | Strict packaging |
   | `strictDeps = true` | Strict deps | Proper dependency handling |
   | `inherit ($LIB) $$$;` | Grouped inherit | Clean imports |
   | `lib.optionals $COND $LIST` | Conditional lists | Conditional logic style |
   | `nixLog "$$$ "` | Logging calls | Verbose build scripts |

   Record pattern frequencies in profile's "Structural Patterns" section.

3. **Semantic search with ck:**

   ```bash
   # Find similar patterns
   ck semantic_search "error handling pattern" ~/.local/share/style-review/files/
   ```

4. **Analyze review feedback (use all signals):**

   ```bash
   # Find PRs with CHANGES_REQUESTED (explicit rejection)
   style-review query "SELECT p.file_path, r.reviewer, r.state FROM prs p
     JOIN reviews r ON r.pr_id = p.id
     WHERE r.state = 'CHANGES_REQUESTED'"

   # Find PRs with most line comments
   style-review query "SELECT p.file_path, COUNT(*) as comments FROM prs p
     JOIN comments c ON c.pr_id = p.id
     WHERE c.comment_type = 'line_comment'
     GROUP BY p.id ORDER BY comments DESC LIMIT 10"

   # Find user's line comments
   style-review query "SELECT p.file_path, c.file_path as commented_file
     FROM comments c JOIN prs p ON c.pr_id = p.id
     WHERE c.author = '<user>' AND c.comment_type = 'line_comment'"

   # Read line comments (code context + feedback)
   cat ~/.local/share/style-review/files/<owner_repo>/<pr>/docs/comments/*.md

   # Read review summaries (overall feedback)
   cat ~/.local/share/style-review/files/<owner_repo>/<pr>/docs/reviews/*.md
   ```

   Different reviewers use different feedback styles:
   - **CHANGES_REQUESTED**: Explicit rejection, must-fix issues
   - **line_comments**: Specific code issues with diff context
   - **COMMENTED**: General feedback, suggestions, questions

5. **Generate profile** in `~/.local/share/style-review/users/<user>/_profile.md`

**Options:**

- `--force` - Regenerate even if profile exists
- `--view` - View existing profile without regenerating

## /style apply <user> [file]

Write code following the user's style.

**Process:**

1. Read profile from `users/<user>/_profile.md`
2. Extract concrete patterns from "Writing Style" section
3. Apply patterns to new code generation
4. Validate generated code against profile

**Concrete Application Guide:**

### Step 1: Pattern Checklist

Extract from profile's "Structural Patterns":

```markdown
- [ ] `__structuredAttrs = true;` included
- [ ] `strictDeps = true;` included
- [ ] `finalAttrs` pattern used
- [ ] `inherit (lib) ...;` style
- [ ] `meta.teams` / `meta.maintainers` present
```

### Step 2: Code Validation

After generating code, verify with ast-grep:

```bash
# Check required patterns
ast-grep --pattern '__structuredAttrs = true' generated.nix
ast-grep --pattern 'finalAttrs: { $$$ }' generated.nix
ast-grep --pattern 'strictDeps = true' generated.nix
```

### Step 3: Anti-pattern Check

Verify profile's anti-patterns are NOT present:

```bash
# Should return no matches
ast-grep --pattern 'find_package(CUDA)' generated.nix
ast-grep --pattern 'CMAKE_CXX_COMPILER' generated.nix
```

**Example Template (ConnorBaker style CUDA package):**

```nix
{ backendStdenv, lib, ... }:

let
  inherit (lib) licenses maintainers teams;
in
backendStdenv.mkDerivation (finalAttrs: {
  __structuredAttrs = true;
  strictDeps = true;

  pname = "...";
  version = "...";

  meta = {
    description = "...";
    license = licenses.unfree;
    platforms = [ "aarch64-linux" "x86_64-linux" ];
    maintainers = with maintainers; [ connorbaker ];
    teams = [ teams.cuda ];
  };
})
```

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

### Pattern Checklist

For `/style apply` validation:

| Pattern | ast-grep Query | Required |
|---------|---------------|----------|
| structuredAttrs | `__structuredAttrs = true` | Yes/No |
| strictDeps | `strictDeps = true` | Yes/No |
| finalAttrs | `finalAttrs: { $$$ }` | Yes/No |
| inherit style | `inherit ($LIB) $$$;` | Recommended |

### Naming Conventions

File naming, variable naming rules.

### Code Structure

Organization patterns, module structure.

### Anti-patterns

Things to avoid. List patterns that should NOT appear in generated code.

---

## Review Style

For `/style review`. How to review like this user.

### What They Point Out

Common issues they flag with examples.
Extract from all feedback: CHANGES_REQUESTED, line_comments, COMMENTED reviews.

### Review Tone

Communication style, directness level.

### Before/After Examples

Concrete examples from their reviews.

---

## Cross-Validation

Related reviewers and their interaction patterns.

### Primary Reviewers

Who reviews this user most frequently, approval rates.

### Review Relationships

- User → Others: How this user reviews others
- Others → User: How others review this user
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
# 1. Collect data (both modes for complete profile)
style-review collect NixOS/nixpkgs --author ConnorBaker --limit 50 --since 1y
style-review collect NixOS/nixpkgs --reviewer ConnorBaker --limit 30 --since 1y

# 2. Check data quality
style-review query "SELECT COUNT(*) FROM prs"
style-review query "SELECT reviewer, COUNT(*) FROM reviews
  WHERE pr_author='ConnorBaker' GROUP BY reviewer"

# 3. Generate profile (in Claude)
/style profile ConnorBaker

# 4. Apply style when writing CUDA packages
/style apply ConnorBaker

# 5. Review code like SomeoneSerge would
/style review SomeoneSerge src/foo.nix
```

# Troubleshooting

| Issue                    | Solution                                                                        |
| ------------------------ | ------------------------------------------------------------------------------- |
| Empty profile            | Collect more data with `--reviewer` mode                                        |
| No review patterns       | Check total feedback (line_comments + COMMENTED + CHANGES_REQUESTED)            |
| Missing cross-validation | Collect PRs from users who review each other                                    |
| Low feedback             | Find active reviewers from nixpkgs; target repos with review culture            |
| Only APPROVED reviews    | Some reviewers use COMMENTED instead of CHANGES_REQUESTED - check line_comments |
