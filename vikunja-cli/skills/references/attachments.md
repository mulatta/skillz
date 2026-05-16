# Attachments

Use this reference when user asks to upload, list, download, delete, or preserve source/proof files on Vikunja tasks.

## Upload/list

```bash
vikunja-cli -j attachment upload --task 123 --file notes.md --file screenshot.png
vikunja-cli -j attachment list --task 123
```

`attachment upload` sends repeated `--file` values in one request using Vikunja's `files` multipart field.

## Attach during task creation

```bash
vikunja-cli -j task create --project Inbox --title "Submit patch" \
  --template submission --context context.json \
  --attach notice.md --attach proof.png
```

`task create --attach FILE` validates every file before task creation. Files are uploaded after the task exists.

Partial-failure behavior:

- If file validation fails, no task is created.
- If task creation succeeds but an upload fails, the task remains.
- The error reports the created task id and failed file.
- Do not assume cleanup happened; ask the user before deleting or retrying.

## Download

```bash
vikunja-cli -j attachment download --task 123 --attachment 456 --output /tmp/proof.png
```

Downloads create parent directories for `--output` and fail if the output path already exists or points to a directory.

## Delete

Attachment deletion is destructive and requires explicit user request plus `--yes`:

```bash
vikunja-cli -j attachment delete --task 123 --attachment 456 --yes
```

## Agent guidance

- Attach raw notices, RSS snapshots, build logs, forms, receipts, confirmations, screenshots, generated outputs, and original emails only when preservation matters.
- Prefer clickable/openable sources for web pages, Slack permalinks, issue/PR links, CI links, and Bulwark/webmail messages.
- Do not attach or render bare email Message-Id values as useful sources; use a webmail URL, searchable local locator, or extracted note instead.
- Keep task descriptions structured; name or link attachments instead of duplicating large source text.
- Use `attachment list` before download/delete when attachment id is unknown.
