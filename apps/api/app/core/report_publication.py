"""Conditional publication on ONE Redis primary; reservations are not exclusive read locks."""

PUBLISH_IF_CURRENT_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[2], ARGV[2], 'PX', ARGV[3])
return 1
"""


async def publish_if_current(redis, reservation_key, report_key, token, payload_json, ttl_ms):
    """The comparison and report write run atomically; no unconditional write fallback."""
    return await redis.eval(
        PUBLISH_IF_CURRENT_LUA, 2, reservation_key, report_key, token, payload_json, ttl_ms
    )
