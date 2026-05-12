# skillz

LLM-useful CLI tools and skills.

## Structure

```
skillz/
├── flake.nix           # Nix flake (packages, checks, treefmt)
├── nix/                # Nix modules, checks, package registry, treefmt
├── pyproject.toml      # Python tooling config (ruff, mypy)
└── <tool-name>/        # CLI tools (packaged via Nix)
    ├── default.nix
    ├── skills/         # Claude Code skill shipped by the package
    │   └── SKILL.md
    └── ...
```

## Tools

- `buildbot-pr-check` - inspect Buildbot (buildbot-nix) CI for a PR
- `calendar-cli` - manage local vdirsyncer calendars
- `context7-cli` - fetch up-to-date library docs from Context7
- `crabfit-cli` - create and manage Crab.fit scheduling events
- `crwl-cli` - crawl web pages and extract markdown
- `gmaps-cli` - search places and get directions with Google Maps
- `miniflux-cli` - read Miniflux RSS entries and enclosures
- `nmap-cli` - use NAVER Cloud Maps APIs
- `n8n-cli` - inspect and manage n8n workflows/API objects
- `pexpect-cli` - automate interactive terminal applications
- `shortcuts-cli` - build and run Apple Shortcuts from Cherri on macOS
- `vikunja-cli` - manage Vikunja tasks, projects, and kanban buckets
- `weather-cli` - get Korean weather from KMA APIs

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
2. Create `<tool-name>/skills/SKILL.md`
3. Add `<tool-name>/default.nix` for packaging
4. Install `<tool-name>/skills` to `$out/share/skills/<tool-name>/`
5. Register the package in `nix/packages.nix`
6. Register the installable skill in `nix/skills.nix`

## Adding a Skill

Standalone top-level skill directories are not used. Add skill definitions under
`<tool-name>/skills/` and ship them from the corresponding package.

Follow the SKILL.md format (YAML frontmatter + markdown body):

```markdown
---
name: my-skill
description: Short description of what this skill does
---

# Usage

Instructions for the LLM...
```
