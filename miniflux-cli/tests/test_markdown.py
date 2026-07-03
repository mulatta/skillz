from miniflux_cli.markdown import entry_to_markdown, html_to_markdown


def test_html_to_markdown_basic() -> None:
    html = '<h1>Title</h1><p>Hello <strong>world</strong> <a href="https://e.test">link</a></p><ul><li>One</li><li>Two</li></ul>'

    assert (
        html_to_markdown(html)
        == "# Title\n\nHello **world** link (https://e.test)\n\n- One\n- Two\n"
    )


def test_entry_to_markdown_includes_frontmatter_and_attachments() -> None:
    entry = {
        "id": 42,
        "title": "Event",
        "url": "https://example.test/event",
        "published_at": "2026-05-01T00:00:00Z",
        "changed_at": "2026-05-02T00:00:00Z",
        "content": "<p>Deadline is <em>tomorrow</em>.</p>",
        "feed": {"title": "Notifications", "category": {"title": "notification"}},
        "enclosures": [
            {"url": "https://example.test/file.pdf", "mime_type": "application/pdf"}
        ],
    }

    rendered = entry_to_markdown(entry)

    assert "id: 42" in rendered
    assert 'category: "notification"' in rendered
    assert "idx: 0" in rendered
    assert "Deadline is _tomorrow_." in rendered
