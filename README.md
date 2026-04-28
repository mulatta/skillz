# skillz

LLM-useful CLI tools and skills.

## Structure

```
skillz/
├── flake.nix           # Nix flake (packages, checks, treefmt)
├── nix/                # Nix modules, checks, package registry, treefmt
├── pyproject.toml      # Python tooling config (ruff, mypy)
├── skills/             # Claude Code skills (SKILL.md files)
│   └── <skill-name>/
│       └── SKILL.md
└── <tool-name>/        # CLI tools (packaged via Nix)
    ├── default.nix
    └── ...
```

## Tools

- `calendar-cli` - manage local vdirsyncer calendars
- `context7-cli` - fetch up-to-date library docs from Context7
- `crwl-cli` - crawl web pages and extract markdown
- `n8n-cli` - inspect and manage n8n workflows/API objects
- `pexpect-cli` - automate interactive terminal applications

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
3. Register the package in `nix/packages.nix`
4. Register the installable skill in `nix/skills.nix`

## Adding a Skill

1. Create `skills/<skill-name>/SKILL.md`
2. For CLI-backed skills, install the skill directory from the package output at `$out/share/skills/<skill-name>/`
3. Follow the SKILL.md format (YAML frontmatter + markdown body)

```markdown
---
name: my-skill
description: Short description of what this skill does
---

# Usage

Instructions for the LLM...
```
