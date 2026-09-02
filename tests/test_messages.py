import pytest

from bot.domain.messages import Button, ButtonsMessage, ListMessage, Row


def test_whatsapp_allows_at_most_three_buttons():
    with pytest.raises(ValueError):
        ButtonsMessage(
            to="549",
            body="Elegi",
            buttons=[Button(id=f"b{i}", title=f"B{i}") for i in range(4)],
        )


def test_whatsapp_allows_at_most_ten_list_rows():
    with pytest.raises(ValueError):
        ListMessage(
            to="549",
            body="Elegi",
            button_label="Ver",
            rows=[Row(id=f"r{i}", title=f"R{i}") for i in range(11)],
        )


def test_a_list_needs_at_least_one_row():
    with pytest.raises(ValueError):
        ListMessage(to="549", body="Elegi", button_label="Ver", rows=[])


def test_button_titles_are_capped_at_twenty_characters():
    with pytest.raises(ValueError):
        ButtonsMessage(
            to="549",
            body="Elegi",
            buttons=[Button(id="b", title="x" * 21)],
        )
