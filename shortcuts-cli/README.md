# shortcuts-cli

Agent-friendly wrapper for [Cherri](https://github.com/electrikmilk/cherri) and macOS Shortcuts.

This tool is macOS-oriented. It builds signed `.shortcut` files locally with Cherri/macOS signing and wraps `/usr/bin/shortcuts` for list/view/run operations.

## Usage

```bash
# Write or inspect Cherri source
shortcuts-cli actions alert
shortcuts-cli docs web

# Validate source without producing an importable shortcut
shortcuts-cli validate example.cherri

# Build signed Shortcut under ~/.claude/outputs by default
shortcuts-cli build example.cherri

# Build and open the Shortcuts import UI
shortcuts-cli build example.cherri --open

# Run installed Shortcuts
shortcuts-cli list
shortcuts-cli run "Example Shortcut"
```

Default build output:

```text
$HOME/.claude/outputs/<source-stem>.shortcut
```

## Example

```cherri
#define color blue
#define glyph shortcuts

alert("Hello from Cherri")
```

```bash
shortcuts-cli validate hello.cherri
shortcuts-cli build hello.cherri --open
```

## Notes

- Signed builds require macOS.
- The tool does not use HubSign or custom signing servers.
- Import is user-confirmed in the Shortcuts app; direct unattended iPhone deployment is not supported.
- Do not hardcode secrets in Cherri source. Use import questions or runtime prompts.
