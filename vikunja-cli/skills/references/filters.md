# Vikunja filters

Use filters when the user asks for a task subset beyond simple project/search
queries: overdue tasks, due soon, high priority, incomplete tasks, or a custom
saved view condition.

## CLI entry points

```bash
vikunja-cli -j task list --filter 'done = false'
vikunja-cli -j task list --project Inbox --filter 'done = false && priority >= 3'
vikunja-cli -j view update Table --project Roadmap --filter 'done = false'
vikunja-cli -j view update Table --project Roadmap --clear-filter
```

`--project` on `task list` is converted to a filter and combined with the user
filter, so these are equivalent in effect:

```bash
vikunja-cli -j task list --project Inbox --filter 'done = false'
vikunja-cli -j task list --filter '(project_id = 12) && (done = false)'
```

Prefer `--project` when user names a project; let CLI resolve the project id.

## Common examples

```bash
# Open tasks
vikunja-cli -j task list --filter 'done = false'

# Overdue open tasks
vikunja-cli -j task list --filter 'done = false && due_date < now'

# Due today or earlier
vikunja-cli -j task list --filter 'done = false && due_date <= now/d'

# High priority open tasks
vikunja-cli -j task list --filter 'done = false && priority >= 4'

# Tasks with no due date
vikunja-cli -j task list --filter 'done = false && due_date = null'

# Done tasks updated recently, newest first
vikunja-cli -j task list --filter 'done = true' --sort-by updated --order-by desc
```

## Filter bucket mode

Filter bucket mode belongs to a kanban view. Use it when user wants columns such
as "Overdue", "High priority", or "Waiting" to be computed by filters instead of
manual drag/drop buckets.

```bash
vikunja-cli -j view update Kanban --project Roadmap --bucket-mode filter \
  --bucket-filter 'Overdue=done = false && due_date < now' \
  --bucket-filter 'High priority=done = false && priority >= 4'
```

Each `--bucket-filter` uses `TITLE=FILTER` syntax.

## Saved filters

Vikunja has saved filter endpoints, but inspected Swagger exposes create/show/
update/delete without a list endpoint. The CLI MVP intentionally avoids saved
filter management. Use inline filters unless saved filter support is added later.
