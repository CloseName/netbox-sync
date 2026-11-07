from types import SimpleNamespace

from tests.test_pfsense_system import module

table_cells = module("pfsense_tables").table_cells


def record(component, table, **data):
    return SimpleNamespace(component=component, table=table, data=data, name="fixture")


def test_rule_conditions_preserve_aliases_negation_and_queue():
    rule = record(
        "firewall",
        "rules",
        type=["pass"],
        ipprotocol=["inet"],
        protocol=["tcp"],
        defaultqueue=["qLAN"],
        **{"source/not": [""], "source/address": ["LAN_HOSTS"], "destination/any": [""], "destination/port": ["443"]},
    )
    cells = table_cells(
        rule,
        ["action", "transport", "source", "destination", "destination/port", "queue"],
        {("source/address", "LAN_HOSTS"): "/alias/"},
    )
    assert [item["text"] for item in cells[1]["items"]] == ["IPv4 TCP"]
    assert cells[2]["prefix"] == "Кроме" and cells[2]["items"][0]["url"] == "/alias/"
    assert cells[3]["items"][0]["text"] == "Любой"
    assert cells[4]["items"][0]["text"] == "443"
    assert cells[5]["items"][0]["text"] == "qLAN"


def test_alias_preview_and_redacted_contents():
    alias = record("aliases", "aliases", address=["10.0.0.1 10.0.0.2 OTHER"])
    (cell,) = table_cells(alias, ["members"], {})
    assert len(cell["preview"]) == 2 and cell["remaining"] == 1
    alias.data.update(content_omitted=["yes"])
    (cell,) = table_cells(alias, ["members"], {})
    assert cell["items"][0]["text"] == "Содержимое не собрано"


def test_outbound_exception_and_source_port_are_visible():
    obj = record("nat", "outbound", nonat=[""], **{"source/network": ["lan"], "source/port": ["https"]})
    endpoint, translation = table_cells(obj, ["source_endpoint", "translation"], {})
    assert any("https" in i["text"] for i in endpoint["items"])
    assert translation["items"][0]["text"] == "Без NAT"
