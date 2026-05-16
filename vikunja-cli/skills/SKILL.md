---
name: vikunja-cli
description: Manage Vikunja projects, tasks, relations, templates, attachments, labels, comments, due/reminder notifications, views, and kanban buckets through a restricted CLI. Use whenever the user asks to inspect or update Vikunja tasks/projects, create structured tasks from sources, attach evidence, link blockers/subtasks/order with task relations, move tasks between projects or kanban buckets, manage workflow labels/comments, or check Vikunja reminders/overdue items. Prefer this skill over raw Vikunja API calls.
---

Use `vikunja-cli` for Vikunja task-management workflows. Do not use raw API calls; this CLI owns the allowlisted API surface and deterministic workflow semantics.

Prefer JSON for agent workflows:

```bash
vikunja-cli -j project list --all
vikunja-cli -j task list --project Inbox --all
vikunja-cli -j task show 123
vikunja-cli -j task create --project Inbox --title "Call Kim" --due 2026-05-15 --reminder 2026-05-15T09:00:00Z
vikunja-cli -j task update 123 --project Inbox --title "Call Kim back"
vikunja-cli -j task complete 123
vikunja-cli -j notification list --kind due --unread
```

## Safety

- Mutating commands require an explicit user request in the current conversation.
- Destructive commands are available only in the trusted local CLI; agent workflows must use n8n-hooks instead.
- Run `vikunja-cli -j setup labels` before template-backed creation or transitions in a fresh instance.
- Use `vikunja-cli -j setup labels --create` only after the user agrees to create workflow labels.

## Common workflows

```bash
# Inspect schema from Markdown+YAML template, then create task and attach source/evidence files
vikunja-cli -j template schema submission
vikunja-cli -j task create --project Inbox --title "Submit patch" \
  --template submission --context context.json \
  --attach proof.md --attach screenshot.png

# Move between semantic workflow states; use relations for real blockers
vikunja-cli -j task transition 123 --state waiting --comment "Waiting for review"
vikunja-cli -j relation add --task 123 --kind blocked --other 456
vikunja-cli -j relation list --task 123

# Manage files and comments
vikunja-cli -j attachment list --task 123
vikunja-cli -j attachment upload --task 123 --file notes.md --file screenshot.png
vikunja-cli -j comment add --task 123 --message "Waiting for review"

# Move cards/projects
vikunja-cli -j task move 123 --project Work
vikunja-cli -j bucket move-task --project Roadmap --view Kanban --task 123 --bucket Doing
```

## References

Read only the relevant reference:

- `references/setup-and-labels.md` — bootstrap workflow labels; label vs relation roles; semantic states and transitions.
- `references/templates-and-workflow.md` — choose templates, inspect required context, render/create tasks, attach evidence.
- `references/attachments.md` — upload/list/download/delete attachments and partial-failure behavior.
- `references/filters.md` — task/view filters, overdue/due/high-priority examples, filter bucket mode.
- `references/views-and-buckets.md` — project views, kanban buckets, manual vs filter buckets.

Bootstrap once if the CLI is not configured:

```bash
vikunja-cli bootstrap --base-url https://vikunja.example.com --api-key-command "rbw get vikunja-api-token"
```
