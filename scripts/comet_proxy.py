#!/usr/bin/env python3
"""Loopback TCP fault harness: per-directed-link proxies, no host firewall changes."""
import argparse
import asyncio
import json
from pathlib import Path


class Network:
    def __init__(self, base: int, count: int):
        self.base, self.count = base, count
        self.groups = None
        self.connections = set()

    def allowed(self, source, target):
        return self.groups is None or any(source in group and target in group for group in self.groups)

    async def forward(self, reader, writer, source, target):
        if not self.allowed(source, target):
            writer.close()
            return
        try:
            downstream, upstream = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.base + target * 10), 3)
        except (OSError, asyncio.TimeoutError):
            writer.close()
            return
        if not self.allowed(source, target):
            writer.close()
            upstream.close()
            return
        pair = (source, target, writer, upstream)
        self.connections.add(pair)

        async def pump(origin, destination):
            while data := await origin.read(64 * 1024):
                destination.write(data)
                await destination.drain()

        tasks = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(downstream, writer))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.connections.discard(pair)
            for stream in (writer, upstream):
                stream.close()
                try:
                    await stream.wait_closed()
                except OSError:
                    pass

    async def control(self, reader, writer):
        try:
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
            if len(headers) > 4096 or not headers.startswith(b"POST /"):
                raise ValueError("POST required")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            if not 0 < length <= 1024:
                raise ValueError("body limit")
            body = json.loads(await asyncio.wait_for(reader.readexactly(length), 3))
            groups = body.get("groups")
            if groups is not None and (not isinstance(groups, list) or sorted(i for group in groups for i in group) != list(range(self.count))):
                raise ValueError("groups must partition all node IDs")
            self.groups = groups
            for source, target, first, second in list(self.connections):
                if not self.allowed(source, target):
                    first.close()
                    second.close()
            payload = b'{"ok":true}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
        except (ValueError, StopIteration, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        finally:
            writer.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.network.read_text())
    net = Network(config["base_port"], len(config["nodes"]))
    servers = []
    for source in range(net.count):
        for target in range(net.count):
            if source != target:
                async def handler(r, w, s=source, t=target):
                    await net.forward(r, w, s, t)
                servers.append(await asyncio.start_server(handler, "127.0.0.1", net.base + 100 + source * 8 + target))
    servers.append(await asyncio.start_server(net.control, "127.0.0.1", net.base + 99, limit=4096))
    print("Loopback link proxies ready", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        for server in servers:
            server.close()


if __name__ == "__main__":
    asyncio.run(main())
