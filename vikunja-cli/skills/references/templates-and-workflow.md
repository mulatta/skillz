# Templates and task workflow

Use this reference when creating structured Vikunja tasks from external notices, issues, build logs, email/slack threads, or planning context.

## Template commands are local

Template discovery, validation, and rendering do not require Vikunja credentials.

```bash
vikunja-cli -j template list
vikunja-cli -j template validate --all
vikunja-cli -j template schema submission
vikunja-cli -j template required submission
vikunja-cli -j template render submission --context context.json
```

Templates live under XDG data paths, normally `${XDG_DATA_HOME:-~/.local/share}/vikunja-cli/templates`. The root may provide `common.schema.json` and `common.template.md.njk`; each template directory may provide only `schema.json` and `defaults.json` when the common layout is enough.

`template schema` exposes the merged common context schema and template-specific hints. `template required` exposes compact required fields, optional fields, and defaults. Use schema/required before asking the user for missing context.

## Template choice

```text
External deadline?
├─ yes
│  ├─ submit form/document/package -> submission
│  ├─ send to person and wait reply -> communication
│  └─ otherwise -> submission variant
└─ no
   ├─ decision is main work -> decision
   ├─ reproducible bug to fix -> bugfix
   ├─ temporary pin/disable/patch until upstream fixed -> workaround
   └─ feature/infra/idea -> backlog
```

## Create task from template

```bash
vikunja-cli -j task create --project Inbox --title "Submit patch" \
  --template submission --context context.json
```

With `--template`, rendered Markdown is converted to Vikunja TipTap HTML and stored as the task description unless `--description` is supplied. Explicit CLI fields win over template defaults; for example, `--priority` overrides `defaults.json` priority.

Missing required context fails unless the user explicitly accepts placeholders:

```bash
vikunja-cli -j task create --project Inbox --title "Submit patch" \
  --template submission --context context.json --allow-missing
```

## Attach source/evidence during creation

Prefer clickable/openable `sources[]` entries and concise `notes[]` facts. Attach raw evidence only when the original file must be preserved or reviewed later.

```bash
vikunja-cli -j task create --project Inbox --title "Submit patch" \
  --template submission --context context.json \
  --attach notice.md --attach patch.diff --attach build.log
```

`--attach` validates all files before creating the task, then uploads each file after creation. If upload fails after creation, the task remains; see `attachments.md` for failure handling.

## Defaults and labels

Labels are for workflow state and task type only. Use task relations for dependencies, subtasks, and ordering.

Required `defaults.json` shape:

```json
{
  "priority": 4,
  "labels": ["type:submission", "state:next"]
}
```

Shortcut fields such as `type` and `label` are rejected. Spell every label as an explicit `labels` entry.

Template labels are resolved before task creation, so missing labels fail early. Run `vikunja-cli -j setup labels` if a template create reports missing labels.

## Description contract

- Context uses the description-only envelope: `summary`, `checklist[]`, `notes[]`, `proof[]`, and `sources[]`.
- Description is rendered from structured context, not raw evidence dump.
- Deadlines, relations, priority, labels, projects, buckets, reminders, and assignees stay in Vikunja task fields or relation APIs, not description text.
- `template render` keeps Markdown for review; `task create --template` stores Vikunja-compatible HTML so headings and task lists render in the UI.
- Description checkboxes are single-task progress milestones from `checklist[]`, not subtasks.
- Attachments are source/proof files.
- Relations are dependencies, blockers, hierarchy, and order; create them with `relation add` after task creation.
- Comments are time-ordered progress/audit log.
- Task fields (`due`, `priority`, labels, buckets) are searchable state.
