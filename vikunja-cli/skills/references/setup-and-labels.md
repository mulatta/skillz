# Setup and workflow labels

Use this reference before template-backed task creation, semantic transitions, or first-time Vikunja workflow setup.

Labels describe workflow state and task type only. Relations describe dependencies, hierarchy, and order. Do not use labels to model blockers, subtasks, parents, or ordering.

## Check setup

```bash
vikunja-cli -j setup labels
```

The command verifies all workflow labels required by local templates and transitions:

```text
state:next
state:waiting
state:someday
type:backlog
type:bugfix
type:communication
type:decision
type:submission
type:workaround
```

If labels are missing, ask the user before creating them:

```bash
vikunja-cli -j setup labels --create
```

## Semantic states

Use `task transition` instead of manually replacing `state:*` labels. It preserves non-state labels and replaces any existing `state:*` label with the target state.

```bash
vikunja-cli -j task transition 123 --state next
vikunja-cli -j task transition 123 --state waiting --comment "Waiting for review"
vikunja-cli -j task transition 123 --state someday
```

Supported states:

```text
next
waiting
someday
```

For blockers, hierarchy, or order, link tasks with a relation and keep workflow state separate:

```bash
vikunja-cli -j relation add --task 123 --kind blocked --other 456
vikunja-cli -j task transition 123 --state waiting --comment "Waiting on 456"
```

Safe relation kinds are `blocked`, `blocking`, `subtask`, `parenttask`, `precedes`, `follows`, and `related`.

## Type labels

Templates apply `type:*` labels from `defaults.json` during task creation. They are resolved before the task is created, so missing labels fail early instead of leaving a partially configured task.

Use `setup labels` when a template create fails with a missing `type:*` or `state:*` label.
