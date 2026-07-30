"""Jellyfin server discovery — the real protocol.

Jellyfin does NOT advertise over mDNS; its discovery is a UDP
broadcast: send ``who is JellyfinServer?`` to port 7359 and servers
reply with JSON ``{"Address": "http://host:8096", "Id": ..., "Name": ...}``.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

DISCOVERY_PORT = 7359
DISCOVERY_MESSAGE = b"who is JellyfinServer?"


@dataclass(frozen=True)
class DiscoveredServer:
    name: str
    url: str
    server_id: str = ""


async def discover(timeout: float = 2.0,
                   broadcast: str = "255.255.255.255",
                   port: int = DISCOVERY_PORT) -> list[DiscoveredServer]:
    """Broadcast a discovery probe and collect replies for ``timeout``
    seconds. Returns deduped servers (possibly empty; never raises for
    ordinary network conditions)."""
    loop = asyncio.get_running_loop()
    found: dict[str, DiscoveredServer] = {}

    class _Probe(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            transport.sendto(DISCOVERY_MESSAGE, (broadcast, port))

        def datagram_received(self, data, addr):
            try:
                reply = json.loads(data.decode("utf-8", "replace"))
                url = (reply.get("Address") or "").rstrip("/")
                if url:
                    key = reply.get("Id") or url
                    found[key] = DiscoveredServer(
                        name=reply.get("Name") or url,
                        url=url, server_id=reply.get("Id") or "")
            except Exception:
                pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Probe, local_addr=("0.0.0.0", 0), allow_broadcast=True)
    except OSError:
        return []
    try:
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(found.values())
