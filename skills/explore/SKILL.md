---
name: explore
description: Explore codebases using ast-grep, ck, qmd, and deepwiki
---

# Overview

Explore and understand codebases using structural search, semantic search, and documentation tools.

**Commands:**
- `codebase` - Overview of project structure
- `pattern` - Search for structural patterns (ast-grep)
- `concept` - Search for concepts/meaning (ck semantic)
- `docs` - Search documentation (qmd)
- `lib` - Learn about external libraries (deepwiki)

# Analysis Tools

| Tool | Source | Use Case |
|------|--------|----------|
| ast-grep | Plugin | Structural patterns: "find all functions named X", "find if statements without else" |
| ck | MCP | Semantic search: "error handling code", "authentication logic" |
| qmd | MCP | Documentation: meeting notes, design docs, READMEs |
| deepwiki | MCP | External libraries: React internals, nixpkgs patterns |

# Commands

## /explore codebase

Get an overview of the project structure.

**Process:**

1. List directory structure
2. Identify language/framework from markers (Cargo.toml, pyproject.toml, flake.nix)
3. Find entry points, main modules
4. Summarize architecture

## /explore pattern <pattern>

Search for structural code patterns using ast-grep.

**Examples:**

```bash
# Nix patterns
/explore pattern "buildPythonPackage"
/explore pattern "finalAttrs"
/explore pattern "lib.optionals"

# Python patterns
/explore pattern "async def"
/explore pattern "try: $$$BODY except: pass"

# Rust patterns
/explore pattern "impl $TYPE for $TRAIT"
```

**Process:**

1. Convert pattern to ast-grep syntax
2. Run `ast-grep --pattern '<pattern>' <path>`
3. Summarize matches with file locations

## /explore concept <description>

Search for code by meaning using ck semantic search.

**Examples:**

```bash
/explore concept "error handling"
/explore concept "database connection pooling"
/explore concept "user authentication flow"
```

**Process:**

1. Use ck MCP `semantic_search` or `hybrid_search`
2. Return relevant code snippets with context
3. Explain how results relate to the concept

## /explore docs <query>

Search documentation using qmd.

**Examples:**

```bash
/explore docs "API design decisions"
/explore docs "deployment process"
/explore docs "meeting notes authentication"
```

**Process:**

1. Use qmd MCP `query` (hybrid search, best quality)
2. Return relevant documents
3. Summarize key points

## /explore lib <library>

Learn about external libraries using deepwiki.

**Examples:**

```bash
/explore lib react-query
/explore lib nixpkgs cuda-packages
/explore lib pytorch distributed
```

**Process:**

1. Use deepwiki MCP `read_wiki_contents` or `ask_question`
2. Summarize architecture, key concepts
3. Show common usage patterns

# Tool Selection Guide

| Need | Tool | Example |
|------|------|---------|
| Find exact code structure | ast-grep | "all async functions" |
| Find by meaning/concept | ck | "code that handles errors" |
| Find in documentation | qmd | "design rationale" |
| Understand external lib | deepwiki | "how does X work?" |
| Find by keyword (exact) | ck regex_search | "TODO" |

# ast-grep Quick Reference

**Basic patterns:**

```yaml
# Match function calls
$FUNC($$$ARGS)

# Match variable assignment
$VAR = $VALUE

# Match if statement
if $COND { $$$BODY }

# Match with type annotation (Rust)
let $VAR: $TYPE = $VALUE
```

**Nix-specific:**

```yaml
# Attribute set
{ $$$ATTRS }

# Function definition
$ARG: $BODY

# With statement
with $EXPR; $BODY

# Let binding
let $$$BINDINGS in $BODY
```

# Example Session

```
User: I need to understand how authentication works in this codebase

Claude: Let me explore that.

/explore concept "authentication"
→ Found auth middleware in src/auth/...

/explore pattern "async def authenticate"
→ Found 3 authentication functions

/explore docs "auth"
→ Found design doc explaining OAuth flow

Summary: Authentication uses OAuth2 with JWT tokens...
```
