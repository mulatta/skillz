# skillz

LLM-useful CLI tools and skills.

## Structure

```
skillz/
├── flake.nix           # Nix flake (packages, checks, treefmt)
├── pyproject.toml      # Python tooling config (ruff, mypy)
├── skills/             # Claude Code skills (SKILL.md files)
│   └── <skill-name>/
│       └── SKILL.md
└── <tool-name>/        # CLI tools (packaged via Nix)
    ├── default.nix
    └── ...
```

## Usage

```bash
# Enter dev shell
nix develop

# Build a package
nix build .#<package-name>

# Format code
nix fmt

# Run checks
nix flake check
```

## Adding a CLI Tool

1. Create `<tool-name>/` directory with source code
2. Add `<tool-name>/default.nix` for packaging
3. Register in `flake.nix` under `packages`

## Adding a Skill

1. Create `skills/<skill-name>/SKILL.md`
2. Follow the SKILL.md format (YAML frontmatter + markdown body)

```markdown
---
name: my-skill
description: Short description of what this skill does
---

# Usage

Instructions for the LLM...
```
