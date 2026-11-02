"""Own a temporary Redis process with a private Unix socket and no TCP listener."""

import asyncio
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from redis.asyncio import Redis


@asynccontextmanager
async def isolated_redis(binary, log_output=None):
    with tempfile.TemporaryDirectory(
        prefix="solon-report-", dir="/private/tmp" if Path("/private/tmp").is_dir() else "/tmp"
    ) as directory:
        root = Path(directory)
        socket = root / "r.sock"
        log = root / "server.log"
        with log.open("w") as stream:
            process = subprocess.Popen(
                [
                    str(Path(binary).resolve()),
                    "--port",
                    "0",
                    "--unixsocket",
                    str(socket),
                    "--unixsocketperm",
                    "700",
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                    "--dir",
                    str(root),
                    "--databases",
                    "1",
                    "--maxmemory",
                    "32mb",
                ],
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        client = Redis(
            unix_socket_path=str(socket),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        try:
            ready = False
            for _ in range(100):
                if process.poll() is not None:
                    break
                try:
                    ready = bool(await client.ping())
                except Exception:
                    pass
                if ready:
                    break
                await asyncio.sleep(0.02)
            if not ready:
                raise RuntimeError("isolated Redis did not start: " + log.read_text()[-2000:])
            yield client, socket
        finally:
            await client.aclose()
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
            if log_output:
                Path(log_output).parent.mkdir(parents=True, exist_ok=True)
                Path(log_output).write_text(log.read_text())
