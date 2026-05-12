# vikunja-cli

Agent-oriented CLI for Vikunja. The command surface is intentionally smaller
than the REST API: it exposes common task-management workflows and avoids raw API
access.

## Goals

- Use Vikunja API tokens, not username/password login.
- Store configuration under XDG config and retrieve secrets via commands such as
  `rbw get ...`.
- Keep commands allowlisted. No `raw`, `api`, or arbitrary-path escape hatch.
- Prefer stable, agent-readable output. Add `-j`/`--json` for raw JSON.
- Make destructive operations explicit with `--yes`.

## Bootstrap

Only bootstrap is provided for setup. It writes config, reads the token through
`api_key_command`, and verifies it with a lightweight authenticated API call.

```bash
vikunja-cli bootstrap \
  --base-url https://vikunja.example.com \
  --api-key-command "rbw get vikunja-api-token"
```

Configuration is stored in:

```text
${XDG_CONFIG_HOME:-~/.config}/vikunja-cli/config.json
```

Example:

```json
{
  "base_url": "https://vikunja.example.com",
  "api_key_command": "rbw get vikunja-api-token"
}
```

Environment overrides, for non-agent use or CI:

```text
VIKUNJA_BASE_URL
VIKUNJA_API_KEY
VIKUNJA_API_KEY_COMMAND
```

Priority: environment variables > config command.

## Command shape

```bash
# Projects
vikunja-cli project list [--search TEXT] [--archived] [-j]
vikunja-cli project show <project> [-j]
vikunja-cli project create --title TITLE [--description TEXT] [--parent PROJECT] [-j]
vikunja-cli project update <project> [--title TITLE] [--description TEXT] [--color HEX] [-j]
vikunja-cli project archive <project> --yes
vikunja-cli project unarchive <project>
vikunja-cli project delete <project> --yes

# Tasks
vikunja-cli task list [--project PROJECT] [--filter FILTER] [--search TEXT] [--all] [-j]
vikunja-cli task show <task> [-j]
vikunja-cli task create --project PROJECT --title TITLE [--description TEXT] [--due DATE] [-j]
vikunja-cli task update <task> [--title TITLE] [--description TEXT] [--due DATE] [--priority N] [-j]
vikunja-cli task complete <task> [-j]
vikunja-cli task reopen <task> [-j]
vikunja-cli task duplicate <task> [-j]
vikunja-cli task delete <task> --yes

# Labels
vikunja-cli label list [--search TEXT] [-j]
vikunja-cli label show <label> [-j]
vikunja-cli label create --title TITLE [--description TEXT] [--color HEX] [-j]
vikunja-cli label update <label> [--title TITLE] [--description TEXT] [--color HEX] [-j]
vikunja-cli label delete <label> --yes
vikunja-cli label add-to-task --task TASK --label LABEL [-j]
vikunja-cli label remove-from-task --task TASK --label LABEL [-j]
vikunja-cli label replace-on-task --task TASK --label LABEL [--label LABEL ...] [-j]

# Comments
vikunja-cli comment list --task TASK [-j]
vikunja-cli comment add --task TASK --message TEXT [-j]
vikunja-cli comment update --task TASK --comment COMMENT --message TEXT [-j]
vikunja-cli comment delete --task TASK --comment COMMENT --yes

# Notifications: focused on actionable due/reminder signals
vikunja-cli notification list --kind due|reminder|overdue [--unread] [-j]
vikunja-cli notification read <id> [-j]
vikunja-cli notification read-all --kind due|reminder|overdue [-j]

# Views
vikunja-cli view list --project PROJECT [-j]
vikunja-cli view show <view> --project PROJECT [-j]
vikunja-cli view create --project PROJECT --title TITLE --kind list|table|kanban|gantt [-j]
vikunja-cli view update <view> --project PROJECT [--title TITLE] [--filter FILTER] [--clear-filter] [-j]
vikunja-cli view update <view> --project PROJECT --bucket-mode none|manual|filter [-j]
vikunja-cli view update <view> --project PROJECT --bucket-mode filter \
  --bucket-filter "Overdue=done = false && due_date < now" \
  --bucket-filter "High priority=priority >= 4" [-j]
vikunja-cli view delete <view> --project PROJECT --yes

# Buckets: manual kanban columns
vikunja-cli bucket list --project PROJECT --view VIEW [-j]
vikunja-cli bucket create --project PROJECT --view VIEW --title TITLE [-j]
vikunja-cli bucket update <bucket> --project PROJECT --view VIEW [--title TITLE] [--limit N] [-j]
vikunja-cli bucket move-task --project PROJECT --view VIEW --task TASK --bucket BUCKET [-j]
vikunja-cli bucket delete <bucket> --project PROJECT --view VIEW --yes
```

## Resolution rules

IDs are preferred. Human names are accepted when they resolve exactly.
Ambiguous names fail with candidate output instead of guessing.

- `project`: id or exact title
- `task`: id or Vikunja identifier such as `PROJ-42`
- `label`: id or exact title
- `view`: id or exact title within a project
- `bucket`: id or exact title within a project view

## Notifications

Vikunja does not provide a notification creation endpoint. Notifications are
created by server events. The CLI filters list results client-side because the
API only supports pagination for `/notifications`.

Useful notification names:

```text
task.reminder
task.undone.overdue
```

Kind mapping:

```text
reminder -> task.reminder
overdue  -> task.undone.overdue
due      -> task.reminder, task.undone.overdue
```

## Views and buckets

A project view is a way to display tasks in a project: `list`, `table`,
`kanban`, or `gantt`. A project may have multiple views.

A bucket is a kanban column inside a kanban view, for example `Backlog`, `Doing`,
`Review`, and `Done`.

Filter bucket mode is configured on the view, not on individual bucket CRUD. It
builds kanban columns from filter definitions instead of manually moved buckets.

## Saved filters

Vikunja also has saved filter endpoints:

```text
PUT    /filters
GET    /filters/{id}
POST   /filters/{id}
DELETE /filters/{id}
```

There is no list endpoint in the inspected Swagger document, so saved filters are
not part of the MVP command surface. Use inline filters first:

```bash
vikunja-cli task list --filter 'done = false && priority >= 3'
vikunja-cli view update Kanban --project Roadmap --filter 'done = false'
```
