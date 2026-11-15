"""The established scanner is paused by the scanner.established_on default. Turning the setting on brings it back."""
import asyncio
from desk import commands, config
from desk.agents import scanner


def test_established_scanner_is_off_until_the_setting_is_turned_on(tdb, monkeypatch):
    scanner.room.clear()
    assert config.all_settings()["scanner.established_on"] is False

    async def boom(*_a, **_k):
        raise AssertionError("established sources must not be called while the scanner is paused")

    monkeypatch.setattr(scanner.S, "gt_pumpswap_pools", boom)
    monkeypatch.setattr(scanner.S, "dex_list", boom)
    monkeypatch.setattr(scanner.S, "dex_tokens", boom)
    assert asyncio.run(scanner.established_once()) == 0
    assert scanner.room == {}
    assert "False -> True" in commands.run("set established_on on")["text"]
    assert config.get("scanner.established_on") is True
    assert "True -> False" in commands.run("set established_on off")["text"]
    assert config.get("scanner.established_on") is False
    assert asyncio.run(scanner.established_once()) == 0
