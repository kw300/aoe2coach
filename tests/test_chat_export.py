"""Markdown export gets only display context and the visible conversation."""

from aoe2coach.report import build_chat_export


def test_export_escapes_labels_and_plain_user_content():
    text = build_chat_export(
        replay_name="/private/folder/[game].aoe2record",
        map_name="<img src=x>",
        duration_label="30:00",
        players=[{"name": "A*lice", "civilization": "Franks"}],
        focus_player="A*lice",
        messages=[
            {"role": "system", "text": "secret system prompt"},
            {"role": "user", "text": "# Fake heading\n<script>alert(1)</script>"},
            {"role": "assistant", "text": "**Advice**", "model": "test", "input_tokens": 0},
        ],
    )
    assert "/private/" not in text
    assert "\\[game\\].aoe2record" in text
    assert "&lt;img src=x&gt;" in text
    assert "A\\*lice" in text
    assert "> \\# Fake heading\n> &lt;script&gt;alert\\(1\\)&lt;/script&gt;" in text
    assert "secret system prompt" not in text
    assert "**Advice**" in text
    assert "Input tokens: 0 · Output tokens: unavailable" in text
