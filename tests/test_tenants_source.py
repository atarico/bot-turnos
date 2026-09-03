"""Where the tenants file comes from.

Same shape as the credentials: a hosted container has no disk to drop a file
on, so the businesses arrive as an environment variable. The path stays for
local work, where a file is easier to edit than a variable.
"""

from __future__ import annotations

import json

import pytest

from bot.main import TENANTS_FILE, TENANTS_JSON, build_registry

PELUQUERIA = "111"
KINESIO = "222"


def business(name: str) -> dict:
    return {
        "name": name,
        "timezone": "America/Argentina/Buenos_Aires",
        "open_hour": 9,
        "close_hour": 19,
        "slot_step_minutes": 30,
        "days_ahead": 7,
        "services": [{"id": "corte", "name": "Corte", "duration_minutes": 30}],
    }


def tenants(*entries: tuple[str, str]) -> str:
    return json.dumps(
        {"tenants": [{"phone_number_id": pid, "business": business(name)} for pid, name in entries]}
    )


@pytest.fixture(autouse=True)
def no_ambient_tenants(monkeypatch):
    monkeypatch.delenv(TENANTS_JSON, raising=False)
    monkeypatch.delenv(TENANTS_FILE, raising=False)


def test_nothing_configured_falls_back_to_the_demo_business():
    registry = build_registry()

    assert len(registry) == 1


def test_the_json_variable_is_read_as_the_tenants_file(monkeypatch):
    monkeypatch.setenv(TENANTS_JSON, tenants((PELUQUERIA, "Peluqueria"), (KINESIO, "Kinesio")))

    registry = build_registry()

    assert len(registry) == 2
    assert registry.get(PELUQUERIA).config.name == "Peluqueria"
    assert registry.get(KINESIO).config.name == "Kinesio"


def test_the_json_variable_wins_over_the_path(monkeypatch, tmp_path):
    leftover = tmp_path / "tenants.json"
    leftover.write_text(tenants((KINESIO, "Stale")), encoding="utf-8")
    monkeypatch.setenv(TENANTS_FILE, str(leftover))
    monkeypatch.setenv(TENANTS_JSON, tenants((PELUQUERIA, "Live")))

    registry = build_registry()

    assert registry.get(PELUQUERIA).config.name == "Live"
    assert registry.get(KINESIO) is None


def test_the_path_still_works_when_no_json_is_present(monkeypatch, tmp_path):
    path = tmp_path / "tenants.json"
    path.write_text(tenants((PELUQUERIA, "From disk")), encoding="utf-8")
    monkeypatch.setenv(TENANTS_FILE, str(path))

    assert build_registry().get(PELUQUERIA).config.name == "From disk"


def test_a_blank_variable_counts_as_unset(monkeypatch):
    monkeypatch.setenv(TENANTS_JSON, "")
    monkeypatch.setenv(TENANTS_FILE, "")

    assert len(build_registry()) == 1  # the demo business, not a crash
