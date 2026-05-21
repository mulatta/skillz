---
name: shortcuts-cli
description: Build, validate, import, and run Apple Shortcuts from Cherri source on macOS. Use for iOS/macOS Shortcuts automation.
---

# Use

Use `shortcuts-cli` when user asks to create or modify Apple Shortcuts automation. It wraps Cherri and macOS `/usr/bin/shortcuts`. This skill is macOS-only for actual signed Shortcut builds and execution.

Do not use HubSign, custom signing servers, or direct iPhone deployment. Build signed files locally on macOS, then open them in Shortcuts for user-confirmed import. There is no supported unattended iPhone deployment API.

# Workflow

1. Write Cherri source under `$HOME/.claude/outputs/<name>.cherri` unless user gives path.
1. Look up actions before guessing names or arguments.
1. Validate source.
1. Build signed `.shortcut` under `$HOME/.claude/outputs`.
1. Open/import only when user asks or after explaining user must confirm import in Shortcuts app.
1. Run installed shortcuts only after they exist in macOS Shortcuts.

```bash
# Discover actions and docs
shortcuts-cli actions alert
shortcuts-cli docs web
shortcuts-cli docs scripting
shortcuts-cli glyphs timer

# Validate without creating importable Shortcut
shortcuts-cli validate "$HOME/.claude/outputs/example.cherri"

# Build signed Shortcut locally on macOS
shortcuts-cli build "$HOME/.claude/outputs/example.cherri"

# Build and open Shortcuts import UI
shortcuts-cli build "$HOME/.claude/outputs/example.cherri" --open

# Open existing signed Shortcut for import
shortcuts-cli import "$HOME/.claude/outputs/example.shortcut"

# Run/list/view installed Shortcuts
shortcuts-cli list
shortcuts-cli run "Example Shortcut"
shortcuts-cli view "Example Shortcut"
```

# Cherri basics

```cherri
#define color blue
#define glyph shortcuts

alert("Hello from Shortcuts")
```

Variables and interpolation:

```cherri
@name = "World"
alert("Hello {@name}")
```

Includes for action categories:

```cherri
#include 'actions/web'
#include 'actions/scripting'

const response = downloadURL("https://example.com")
alert("Downloaded")
```

Menus:

```cherri
menu "Choose" {
    item "A":
        alert("A")
    item "B":
        alert("B")
}
```

Import questions for secrets/user-specific values:

```cherri
#question apiKey "API Key" ""

#include 'actions/web'

const apiKeyText = text(apiKey)
const response = downloadURL("https://api.example.com", {"Authorization": "Bearer {apiKeyText}"})
```

# Command guide

| Need | Command | Notes |
| ------------------------ | --------------------------------------------------------------- | ------------------------------------------------------------- |
| Compile check | `shortcuts-cli validate FILE.cherri` | Uses unsigned temp artifact; not importable |
| Build importable file | `shortcuts-cli build FILE.cherri` | Requires macOS local signing |
| Build and open import UI | `shortcuts-cli build FILE.cherri --open` | User must confirm in Shortcuts app |
| Share with anyone | `shortcuts-cli build FILE.cherri --share anyone` | Default is contacts/people who know me |
| Find action syntax | `shortcuts-cli actions QUERY` | Wraps `cherri --action` |
| Browse category docs | `shortcuts-cli docs CATEGORY` | Categories include `web`, `scripting`, `shortcuts`, `network` |
| Decompile | `shortcuts-cli decompile LINK_OR_UNSIGNED --output FILE.cherri` | Signed local files are not supported by Cherri decompile |

# Safety rules

- Never hardcode API keys, passwords, tokens, or personal secrets in `.cherri`.
- Use `#question`, Ask for Input, or Keychain-capable Shortcuts actions for secrets.
- Add confirmation before destructive actions such as deleting files, sending messages, or calling paid APIs.
- iOS-only actions may compile on Mac but cannot always be runtime-tested on Mac.
- Third-party app actions may require `#import` and local Shortcuts toolkit data; look up docs/actions first.
- If Cherri lacks an action, use `rawAction()` only when identifier and parameter keys are known from docs or decompilation.

# Limits

- No Linux/remote signing path in this skill.
- No automatic iPhone deployment.
- `validate` proves Cherri compilation only; it does not prove runtime permissions or iOS-only behavior.
