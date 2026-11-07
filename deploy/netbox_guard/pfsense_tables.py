"""Read-only list layouts for collected pfSense tables. Each cell retains its references."""

from itertools import zip_longest

ALIAS_TYPES = {"ip": ["host", "network"], "ports": ["port"], "urls": ["url", "urltable", "url_ports", "urltable_ports"]}

LAYOUTS = {
    ("firewall", "rules"): "action transport source source/port destination destination/port gateway queue sched descr",
    ("aliases", "aliases"): "name members descr",
    ("schedules", "schedules"): "name intervals descr",
    ("schedules", "ranges"): "month day position hour rangedescr",
    ("nat", "port_forwards"): "interface transport source_endpoint destination_endpoint redirect descr",
    ("nat", "one_to_one"): "interface external source destination translation_mode descr",
    ("nat", "outbound"): "interface transport source_endpoint destination_endpoint translation descr",
    ("interfaces", "interfaces"): "descr name device address",
    ("interfaces", "vlans"): "name tag parent descr",
    ("routing", "gateways"): "name interface gateway monitor descr",
    ("routing", "groups"): "name item trigger descr",
    ("routing", "static_routes"): "network gateway descr",
    ("general", "dns"): "address hostname gateway",
    ("users", "users"): "name memberships expires descr",
    ("users", "groups"): "name member description",
    ("users", "authservers"): "name type host",
    ("certificates", "certificates"): "descr common_name issuer valid_until validity",
    ("certificates", "authorities"): "descr common_name issuer valid_until validity",
    ("certificates", "crls"): "descr caref next_update",
    ("certificates", "revocations"): "serial descr reason revoke_time",
    ("dhcp", "ipv4"): "range/from range/to gateway dnsserver domain",
    ("dhcp", "ipv6"): "range/from range/to dnsserver domain",
    ("dhcp", "static_ipv4"): "ipaddr mac hostname descr",
    ("dns_resolver", "hosts"): "fqdn ip descr",
    ("dns_forwarder", "hosts"): "fqdn ip descr",
    ("dns_resolver", "domains"): "domain dns_target descr",
    ("haproxy", "frontends"): "name listeners backend_serverpool status",
    ("haproxy", "backends"): "name mode balance check_type",
    ("haproxy", "servers"): "name address port ssl status",
    ("ipsec", "phase1"): "descr interface remote-gateway iketype",
    ("ipsec", "phase2"): "descr localid remoteid protocol mode",
    ("wireguard", "tunnels"): "name tunnel_addresses listenport descr",
    ("wireguard", "peers"): "descr endpoint port allowed_networks",
    ("openvpn", "servers"): "description mode interface protocol local_port tunnel_network tunnel_networkv6",
    ("openvpn", "clients"): "description server_addr server_port protocol",
    ("openvpn", "client_overrides"): "common_name local_network remote_network description",
}
# All other configuration pages have a single settings form in the source UI.
HEADINGS = {
    "action": "Действие",
    "transport": "Протокол",
    "source": "Источник",
    "source/port": "Порт источника",
    "destination": "Назначение",
    "destination/port": "Порт назначения",
    "queue": "Очередь",
    "sched": "Расписание",
    "descr": "Описание",
    "description": "Описание",
    "name": "Имя",
    "members": "Состав",
    "intervals": "Период",
    "month": "Месяц",
    "day": "День",
    "position": "Дни недели",
    "hour": "Время",
    "rangedescr": "Описание интервала",
    "gateway": "Шлюз",
    "interface": "Интерфейс",
    "source_endpoint": "Источник / порт",
    "destination_endpoint": "Назначение / порт",
    "redirect": "Перенаправление",
    "external": "Внешний адрес",
    "translation_mode": "Преобразование",
    "translation": "Адрес трансляции",
    "device": "Устройство",
    "address": "Адрес",
    "tag": "VLAN ID",
    "parent": "Родительский интерфейс",
    "monitor": "IP мониторинга",
    "item": "Шлюзы и приоритеты",
    "trigger": "Условие переключения",
    "network": "Сеть назначения",
    "hostname": "Имя хоста",
    "memberships": "Группы",
    "expires": "Действует до",
    "member": "Участники",
    "type": "Тип",
    "host": "Хост",
    "common_name": "Common Name",
    "issuer": "Кем выдан",
    "valid_until": "Действует до",
    "validity": "Срок на момент сбора",
    "caref": "Центр сертификации",
    "next_update": "Следующее обновление",
    "serial": "Серийный номер",
    "reason": "Причина",
    "revoke_time": "Дата отзыва",
    "range/from": "Начало пула",
    "range/to": "Конец пула",
    "dnsserver": "DNS-серверы",
    "domain": "Домен",
    "ipaddr": "IP-адрес",
    "mac": "MAC",
    "fqdn": "DNS-имя",
    "ip": "IP-адрес",
    "dns_target": "DNS-сервер назначения",
    "listeners": "Адрес / порт",
    "backend_serverpool": "Backend",
    "status": "Состояние",
    "mode": "Режим",
    "balance": "Балансировка",
    "check_type": "Проверка",
    "port": "Порт",
    "ssl": "TLS",
    "remote-gateway": "Удалённый шлюз",
    "iketype": "IKE",
    "localid": "Локальная сеть",
    "remoteid": "Удалённая сеть",
    "protocol": "Протокол",
    "listenport": "Порт",
    "tunnel_addresses": "Адреса туннеля",
    "endpoint": "Endpoint",
    "allowed_networks": "Разрешённые сети",
    "local_port": "Локальный порт",
    "tunnel_network": "Сеть туннеля IPv4",
    "tunnel_networkv6": "Сеть туннеля IPv6",
    "server_addr": "Сервер",
    "server_port": "Порт сервера",
    "local_network": "Локальные сети",
    "remote_network": "Удалённые сети",
}
VALIDITY = {"valid": "Действует", "expired": "Истёк", "not_yet_valid": "Ещё не действует"}
PRIMARY = {"name", "description", "descr", "network", "ipaddr", "fqdn", "domain", "serial", "common_name"}


def cell_data(obj, key, refs, related):
    data = obj.data

    def item(text, url=None):
        return {"text": text, "url": url}

    def values(field):
        raw = data.get(field, [])
        return [item(text, refs.get((field, text))) for text in raw if text]

    def joined(*fields):
        return " ".join(text for field in fields for text in data.get(field, []) if text)

    def endpoint(side):
        found = values(side + "/address") + values(side + "/network")
        if data.get(side + "/any"):
            found.append(item("Любой"))
        return found

    def paired(left, right, delimiter):
        return [
            item(a + (delimiter + b if b else ""))
            for a, b in zip_longest(data.get(left, []), data.get(right, []), fillvalue="")
        ]

    if key in ("source", "destination", "source_endpoint", "destination_endpoint"):
        side = key.split("_")[0]
        parts = endpoint(side)
        if key.endswith("_endpoint") and data.get(side + "/port"):
            parts.extend(item("порт " + v["text"], v["url"]) for v in values(side + "/port"))
        return parts
    if key in ("source/port", "destination/port"):
        return values(key) or [item("Любой")]
    if key == "members":
        if data.get("content_omitted"):
            return [item("Содержимое не собрано")]
        return [
            item(v, refs.get(("address", v)))
            for part in data.get("address", [])
            for v in part.replace(",", " ").split()
        ]
    if key in ("memberships", "intervals"):
        return related.get(key, [])
    if key == "transport":
        families = {"inet": "IPv4", "inet6": "IPv6", "inet46": "IPv4/IPv6"}
        family = joined("ipprotocol")
        return [item(" ".join(filter(None, [families.get(family, family), joined("protocol").upper() or "Любой"])))]
    if key == "action":
        return [item(joined("type").capitalize())] if joined("type") else []
    if key == "queue":
        return values("defaultqueue") + [item("ACK " + v["text"]) for v in values("ackqueue")]
    if key == "redirect":
        return (
            [item("Без NAT")]
            if data.get("nordr")
            else values("target") + [item("порт " + v["text"], v["url"]) for v in values("local-port")]
        )
    if key == "translation_mode":
        return [item("Без NAT" if data.get("nobinat") else "1:1")]
    if key == "translation":
        if data.get("nonat"):
            return [item("Без NAT")]
        parts = values("targetip") or values("target")
        parts.extend(item("порт " + v["text"], v["url"]) for v in values("natport"))
        if data.get("staticnatport"):
            parts.append(item("Сохранить порт"))
        return parts
    if key == "fqdn":
        return [item(".".join(v for v in (joined("host"), joined("domain")) if v))]
    if key == "dns_target":
        return values("ip")
    if key == "listeners":
        return paired("a_extaddr/item/extaddr", "a_extaddr/item/extaddr_port", " · ")
    if key in ("localid", "remoteid"):
        return paired(key + "/address", key + "/netbits", "/") or values(key + "/type")
    if key in ("allowed_networks", "tunnel_addresses"):
        path = "allowedips/item/" if key == "allowed_networks" else "addresses/item/"
        return paired(path + "address", path + "mask", "/")
    if key == "validity":
        return [item(VALIDITY.get(v, v)) for v in data.get(key, [])]
    return values(key)


def table_cells(obj, columns, references, related=None):
    cells = []
    for key in columns:
        items = cell_data(obj, key, references, related or {})
        side = key.split("_")[0]
        prefix = "Кроме" if side in ("source", "destination") and obj.data.get(side + "/not") else ""
        cells.append(
            dict(
                key=key,
                items=items,
                preview=items[:2],
                remaining=max(0, len(items) - 2),
                prefix=prefix,
                primary=key in PRIMARY,
            )
        )
    return cells
