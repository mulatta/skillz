---
name: vikunja-cli
description: Manage Vikunja projects, tasks, labels, comments, due/reminder notifications, views, and kanban buckets through a restricted CLI. Use whenever user asks to inspect or update Vikunja tasks/projects, move cards between kanban buckets, manage labels/comments, or check Vikunja reminders/overdue items.
---

Use `vikunja-cli` for Vikunja task-management workflows. Do not use raw API calls; this CLI intentionally exposes only allowlisted operations.

Read references only when needed:

- `references/filters.md` — task/view filters, overdue/due/high-priority examples, filter bucket mode.
- `references/views-and-buckets.md` — project views, kanban buckets, manual vs filter buckets.

Bootstrap once if the CLI is not configured:

```bash
vikunja-cli bootstrap --base-url https://vikunja.example.com --api-key-command "rbw get vikunja-api-token"
```

Prefer JSON for agent workflows:

```bash
vikunja-cli -j project list --all
vikunja-cli -j task list --project Inbox --all
vikunja-cli -j task create --project Inbox --title "Call Kim" --due 2026-05-15
vikunja-cli -j task complete 123
vikunja-cli -j label add-to-task --task 123 --label urgent
vikunja-cli -j comment add --task 123 --message "Waiting for review"
vikunja-cli -j notification list --kind due --unread
```

Destructive operations require `--yes`:

```bash
vikunja-cli task delete 123 --yes
vikunja-cli project delete OldProject --yes
```

Kanban columns are buckets inside a project view:

```bash
vikunja-cli -j view list --project Roadmap
vikunja-cli -j bucket list --project Roadmap --view Kanban
vikunja-cli -j bucket move-task --project Roadmap --view Kanban --task 123 --bucket Doing
```

Notification support is intentionally narrow. Use it for due/reminder signals only:

```bash
vikunja-cli -j notification list --kind due --unread
vikunja-cli -j notification read-all --kind due
```
