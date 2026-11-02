"""Small protocol double; authoritative Lua/expiry tests use a real Redis server separately."""


class PublicationRedis:
    def __init__(self):
        self.data = {}
        self.writes = []
        self.reservations = []

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, *, px):
        self.data[key] = value
        self.reservations.append((key, value, px))
        return True

    async def setex(self, key, ttl, value):
        self.data[key] = value
        self.writes.append((key, ttl))

    async def eval(self, script, numkeys, reservation_key, report_key, token, payload, ttl_ms):
        if self.data.get(reservation_key) != token:
            return 0
        # setex is retained as a fault-injection seam for the pre-existing unit tests.
        await self.setex(report_key, (int(ttl_ms) + 999) // 1000, payload)
        return 1
