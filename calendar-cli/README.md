# calendar-cli

CLI tool for managing local vdirsyncer calendars.

Reads and writes `.ics` files directly in the vdirsyncer filesystem store
(`~/.local/share/calendars/`) using the `icalendar` Python library. No khal
dependency required.

Also supports sending meeting invitations, importing calendar invites from
email, and replying to invitations with RSVP responses (via msmtp).

## Subcommands

| Command | Description |
| ----------- | ------------------------------------------------------ |
| `calendars` | List available calendars |
| `list` | List events (date range, calendar filter) |
| `show` | Show a single event by UID |
| `search` | Search events by text (summary, location, description) |
| `new` | Create a new local event |
| `edit` | Edit an existing event |
| `delete` | Delete an event by UID |
| `invite` | Create and send a meeting invitation via email |
| `import` | Import invites, process RSVP replies & cancellations |
| `reply` | RSVP to a calendar invitation |

## Structured references

`new` and `edit` support iCalendar reference fields:

```sh
calendar-cli new "Deadline" --start 2025-04-01 --all-day -c academic \
  --description "Submit after advisor sign-off" \
  --url "https://example.org/source" \
  --attach "file:///home/user/forms/form.pdf"

calendar-cli edit <uid> --url "https://example.org/new-source" \
  --attach "https://example.org/doc.pdf"
calendar-cli edit <uid> --clear-url --clear-attach
```

Use `DESCRIPTION` for short notes, `URL` for the primary source, and repeated
`ATTACH` values for related documents or files. `show <uid>` displays all of
these fields.

## Requirements

- Python 3.13+
- vdirsyncer (for calendar sync)
- msmtp (optional, for sending invitations and replies)

## Configuration

Organizer email/name for `invite` can be set in
`~/.config/vcal/config.toml`:

```toml
[user]
email = "user@example.com"
name = "User Name"
```

## Integration with aerc

Add to your aerc `binds.conf`:

```ini
ii = :pipe -m calendar-cli import<Enter>
ia = :pipe -m calendar-cli reply accept<Enter>
id = :pipe -m calendar-cli reply decline<Enter>
it = :pipe -m calendar-cli reply tentative<Enter>
```

Use `ii` for **all** incoming calendar emails: new invites,
attendee responses, and cancellations are detected automatically.
