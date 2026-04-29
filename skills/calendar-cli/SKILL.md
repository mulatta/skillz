---
name: calendar-cli
description: Manage calendar events and send meeting invitations. Use for listing, creating, editing, deleting events and sending/replying to invites.
---

# Usage

- Always pass an Olson timezone (`Europe/Berlin`, `America/New_York`) when
  creating or editing events. Ask the user if unclear.
- Run `calendar-cli calendars` first to discover available calendar names.
  Calendar names are resolved case-insensitively.
- `list`, `show`, and `search` do **not** sync by default (fast, uses local
  cache). Pass `--sync` to pull remote changes first.
- `new`, `edit`, and `delete` always sync after the operation.
- `list` shows at most 50 events by default and truncates descriptions.
  Use `show <uid>` to get full details including URL and attachments.
- Keep descriptions concise. Store the primary source link in `--url` and
  additional document/file links with repeated `--attach` values.

```bash
calendar-cli calendars
calendar-cli list                                     # today + 7 days
calendar-cli list --from 2025-04-01 --to 2025-04-07 -v
calendar-cli list --days 30 --limit 100               # more events
calendar-cli search "dentist"                          # find by text
calendar-cli search "sprint|retro" -c work -v          # regex, one calendar
calendar-cli show <uid>                                # full details

calendar-cli new "Meeting" --start "2025-04-01 14:00" --timezone Europe/Berlin -d 60 -c personal
calendar-cli new "Deadline" --start 2025-04-01 --all-day -c academic \
  --description "Submit after advisor sign-off" --url "https://example.org/source" \
  --attach "file:///home/user/forms/form.pdf"
calendar-cli new "Standup" --start "2025-04-01 09:00" --timezone America/New_York \
  -d 15 --rrule "FREQ=WEEKLY;BYDAY=MO,WE,FR" --alarm 15m

calendar-cli edit <uid> --summary "New Title"
calendar-cli edit <uid> --url "https://example.org/new-source" --attach "https://example.org/doc.pdf"
calendar-cli edit <uid> --clear-url --clear-attach
calendar-cli edit <uid> --start "2025-04-02 10:00" --timezone Europe/Berlin
calendar-cli delete <uid>
```

For email invites, import and RSVP see [EMAIL_INVITES.md](./EMAIL_INVITES.md).
