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

`bootstrap` writes config, reads the token through `api_key_command`, and
verifies it with a lightweight authenticated API call.

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

Global flags such as `-j`/`--json` come before the command:

```bash
vikunja-cli -j task list --project Inbox --all
```

```bash
# Setup
vikunja-cli setup labels [--create]

# Projects
vikunja-cli project list [--search TEXT] [--archived] [--all]
vikunja-cli project show <project>
vikunja-cli project create --title TITLE [--description TEXT] [--color HEX] [--parent PROJECT]
vikunja-cli project update <project> [--title TITLE] [--description TEXT] [--color HEX]
vikunja-cli project archive <project> --yes
vikunja-cli project unarchive <project>
vikunja-cli project delete <project> --yes

# Tasks
vikunja-cli task list [--project PROJECT] [--filter FILTER] [--search TEXT] [--sort-by FIELD] [--order-by asc|desc] [--expand FIELD] [--all]
vikunja-cli task show <task>
vikunja-cli task create --project PROJECT --title TITLE [--description TEXT] [--due DATE] [--start DATE] [--end DATE] [--priority N] [--color HEX] [--reminder DATE] [--attach FILE ...]
vikunja-cli task create --project PROJECT --title TITLE --template TEMPLATE --context context.json [--allow-missing] [--description TEXT] [--priority N] [--reminder DATE] [--attach FILE ...]
vikunja-cli task update <task> [--title TITLE] [--project PROJECT] [--description TEXT] [--due DATE] [--start DATE] [--end DATE] [--priority N] [--color HEX] [--percent-done N] [--reminder DATE]
vikunja-cli task move <task> --project PROJECT
vikunja-cli task transition <task> --state waiting|next|someday [--comment TEXT]
vikunja-cli task complete <task>
vikunja-cli task reopen <task>
vikunja-cli task duplicate <task>
vikunja-cli task delete <task> --yes

# Templates: local metadata/render only, no Vikunja credentials required
vikunja-cli template list [--template-dir DIR]
vikunja-cli template show TEMPLATE [--template-dir DIR]
vikunja-cli template render TEMPLATE --context context.json [--template-dir DIR]
vikunja-cli template validate TEMPLATE [--template-dir DIR]
vikunja-cli template validate --all [--template-dir DIR]
vikunja-cli template required TEMPLATE [--template-dir DIR]

# Attachments
vikunja-cli attachment list --task TASK
vikunja-cli attachment upload --task TASK --file FILE [--file FILE ...]
vikunja-cli attachment download --task TASK --attachment ID --output PATH
vikunja-cli attachment delete --task TASK --attachment ID --yes

# Labels
vikunja-cli label list [--search TEXT] [--all]
vikunja-cli label show <label>
vikunja-cli label create --title TITLE [--description TEXT] [--color HEX]
vikunja-cli label update <label> [--title TITLE] [--description TEXT] [--color HEX]
vikunja-cli label delete <label> --yes
vikunja-cli label add-to-task --task TASK --label LABEL
vikunja-cli label remove-from-task --task TASK --label LABEL
vikunja-cli label replace-on-task --task TASK --label LABEL [--label LABEL ...]

# Comments
vikunja-cli comment list --task TASK [--order asc|desc]
vikunja-cli comment add --task TASK --message TEXT
vikunja-cli comment update --task TASK --comment COMMENT --message TEXT
vikunja-cli comment delete --task TASK --comment COMMENT --yes

# Notifications: focused on actionable due/reminder signals
vikunja-cli notification list --kind due|reminder|overdue [--unread]
vikunja-cli notification read <id>
vikunja-cli notification read-all --kind due|reminder|overdue

# Views
vikunja-cli view list --project PROJECT
vikunja-cli view show <view> --project PROJECT
vikunja-cli view create --project PROJECT --title TITLE --kind list|table|kanban|gantt [--filter FILTER]
vikunja-cli view update <view> --project PROJECT [--title TITLE] [--kind list|table|kanban|gantt] [--filter FILTER] [--clear-filter]
vikunja-cli view update <view> --project PROJECT --bucket-mode none|manual|filter
vikunja-cli view update <view> --project PROJECT --bucket-mode filter \
  --bucket-filter "Overdue=done = false && due_date < now" \
  --bucket-filter "High priority=priority >= 4"
vikunja-cli view delete <view> --project PROJECT --yes

# Buckets: manual kanban columns
vikunja-cli bucket list --project PROJECT --view VIEW
vikunja-cli bucket create --project PROJECT --view VIEW --title TITLE [--limit N]
vikunja-cli bucket update <bucket> --project PROJECT --view VIEW [--title TITLE] [--limit N]
vikunja-cli bucket move-task --project PROJECT --view VIEW --task TASK --bucket BUCKET
vikunja-cli bucket delete <bucket> --project PROJECT --view VIEW --yes
```

Examples:

```bash
vikunja-cli task move 123 --project Work
vikunja-cli task update PROJ-42 --project Inbox --title "Triage customer reply"
```

## Templates

Templates are local files under:

```text
${XDG_CONFIG_HOME:-~/.config}/vikunja-cli/templates/<name>/
```

Each template directory contains `template.md.njk`, optional `schema.json`, and
optional `defaults.json`. `template render` returns the rendered description,
defaults, schema, and missing required fields. `template validate` checks one
template or `--all` template directories, and requires exactly one of `TEMPLATE`
or `--all`. `template required` returns required/optional context metadata and
raw defaults for planning. Template commands are local and do not read Vikunja
credentials.

Use templates at creation time:

```bash
vikunja-cli task create --project Inbox --title "Submit patch" \
  --template submission --context context.json
```

Attach source/evidence files during creation:

```bash
vikunja-cli task create --project Inbox --title "Submit patch" \
  --template submission --context context.json \
  --attach patch.diff --attach build.log
```

With `--template`, rendered Markdown becomes the task description. Explicit CLI
fields have highest priority: `--description` overrides rendered Markdown, and
`--priority` overrides template defaults. Missing required context fails unless
`--allow-missing` is set.

Supported `schema.json` metadata fields:

```json
{
  "required": ["goal"],
  "required_any": [["sources.slack_thread", "sources.email_thread"]],
  "optional": ["notes"],
  "attachment_expectations": ["patch file"]
}
```

Supported `defaults.json` fields for task creation:

```json
{
  "priority": 4,
  "labels": ["type:submission", "state:next"]
}
```

Labels are resolved by title before task creation, then applied through Vikunja's
bulk label endpoint after creation. For compatibility, old defaults still work: `"type":
"submission"` becomes `type:submission`, and `"label": "next"` becomes
`state:next`.

Use `VIKUNJA_TEMPLATE_DIR` or `--template-dir` on `template` commands to override
the template root. `task create --template` uses the configured template root.

## Resolution rules

IDs are preferred. Human names are accepted when they resolve exactly.
Ambiguous names fail with candidate output instead of guessing.

- `project`: id or exact title
- `task`: id or Vikunja identifier such as `PROJ-42`
- `label`: id or exact title
- `view`: id or exact title within a project
- `bucket`: id or exact title within a project view

## Attachments

Attachment upload uses Vikunja's `files` multipart field and sends repeated
`--file` values in one request. `attachment list` prints a compact table by
default. Use global `-j`/`--json` before `attachment list`, `upload`, `download`,
or `delete` for raw JSON/status output.

Downloads create parent directories for `--output` and fail if the output path
already exists or points to a directory.

`task create --attach FILE` validates all files before creating the task, then
uploads each file after creation. If an upload fails, the command exits nonzero
and reports the created task id and failed file; it does not delete the task.

## Reminders

Repeat `--reminder` on `task create` or `task update` to set absolute task
reminders. Updating reminders sends the full reminder list to Vikunja.

## Semantic workflow labels

Use `vikunja-cli setup labels` to verify required workflow labels. Add
`--create` to create missing defaults:

```text
state:next
state:waiting
state:waiting-upstream
state:someday
type:backlog
type:bugfix
type:communication
type:decision
type:submission
type:workaround
```

Use `vikunja-cli task transition TASK --state waiting|waiting-upstream|next|someday` to replace
any current `state:*` label while preserving other labels. Transition commands
expect existing state labels; run setup before using them. Add `--comment TEXT`
to record transition context on the task.

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
