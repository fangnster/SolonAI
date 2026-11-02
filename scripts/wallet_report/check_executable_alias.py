"""Regression: redis-server may be a symlink to an argv[0]-selected redis-check-rdb."""

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from redis_harness import isolated_redis


async def check(binary):
    with tempfile.TemporaryDirectory(prefix="solon-redis-alias-") as directory:
        root = Path(directory)
        checker = root / "redis-check-rdb"
        shutil.copy2(binary, checker)
        alias = root / "redis-server"
        alias.symlink_to(checker.name)
        # Resolving alias before exec would select the RDB checker and fail to start.
        async with isolated_redis(alias) as (redis, _socket):
            assert await redis.ping()
            version = (await redis.info("server"))["redis_version"]
    return {"verified": True, "redis_version": version, "executable_alias_preserved": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-server", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.redis_server.absolute())), indent=2))
