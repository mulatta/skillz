# Views and buckets

Use this reference when user asks about kanban boards, columns, moving cards, or
why a task appears differently in Vikunja views.

## View

A project view is a way to display tasks in a project. Kinds:

```text
list
table
kanban
gantt
```

A project can have multiple views. Example:

```text
Project: Roadmap
  View: List
  View: Kanban
  View: Gantt
```

Commands:

```bash
vikunja-cli -j view list --project Roadmap
vikunja-cli -j view create --project Roadmap --title Kanban --kind kanban
vikunja-cli -j view update Kanban --project Roadmap --filter 'done = false'
vikunja-cli view delete Kanban --project Roadmap
```

## Bucket

A bucket is a kanban column inside a kanban view. Example:

```text
Kanban view:
  Backlog | Doing | Review | Done
```

Buckets are scoped by project + view, so bucket commands need both:

```bash
vikunja-cli -j bucket list --project Roadmap --view Kanban
vikunja-cli -j bucket create --project Roadmap --view Kanban --title Doing
vikunja-cli -j bucket move-task --project Roadmap --view Kanban --task 123 --bucket Doing
```

## Manual buckets vs filter buckets

Manual bucket mode:

- Buckets behave like normal kanban columns.
- Use `bucket move-task` to move tasks between columns.

Filter bucket mode:

- Columns are computed from filters.
- Configure through `view update`, not bucket CRUD.
- Use when user wants automatic columns like overdue/high-priority.

```bash
vikunja-cli -j view update Kanban --project Roadmap --bucket-mode filter \
  --bucket-filter 'Overdue=done = false && due_date < now' \
  --bucket-filter 'High priority=done = false && priority >= 4'
```

## Agent guidance

- If user says "move task/card to Doing", use `bucket move-task`.
- If user says "make a column for overdue tasks", use filter bucket mode.
- If user says "show only open tasks in this view", update the view filter.
- If view or bucket name is ambiguous, CLI fails with candidates; ask user or use id.
