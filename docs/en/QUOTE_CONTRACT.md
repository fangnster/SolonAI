# Exact swap quote amounts

[English home](../../README.en.md) · [API](API.md) · [Portfolio](PORTFOLIO.md)

## The failure this change prevents

The earlier HTTP route accepted a human-readable float and multiplied it by 1,000,000,000 for every input mint. Requesting 1 USDC at scale 6 therefore sent 1,000,000,000 units, which represents 1,000 USDC. The service already expects raw units, so the API boundary must not guess the input mint's scale.

`POST /api/v1/assets/swap/quote` now accepts `amount_raw` as canonical positive u64 integer text. This is an ExactIn request. Human-readable `amount` is removed; callers using the old field must migrate. There is no compatibility fallback that guesses units. Repository search found no frontend caller of this endpoint at the time of the change.

```json
{
  "input_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  "output_mint": "So11111111111111111111111111111111111111112",
  "amount_raw": "1000000",
  "slippage_bps": 50,
  "provider": "auto"
}
```

This represents one USDC only when that input mint's independently known scale is 6. The API passes 1,000,000 to the provider without fetching or guessing decimals. To convert user-entered token text, the caller needs authoritative mint metadata and a separate exact conversion; do not multiply a JavaScript Number by a scale.

## Validation and response checks

- `amount_raw`: JSON string, ASCII digits, no sign/whitespace/exponent/leading zero; 1 through 18446744073709551615. Length is bounded before integer conversion.
- `slippage_bps`: strict JSON integer, 0 through 10000. This is this application's input policy, not a claim about every provider's permitted range.
- `provider`: `auto`, `jupiter`, or `raydium`. Extra fields are forbidden.
- Mint fields are nonempty bounded strings; this change does not establish chain ownership or verify their decimal metadata.
- The returned provider, input/output mints, input amount and slippage must match the requested contract. Output amount must be an integer in u64 range. Mismatch returns 502 instead of a successful quote.
- Validation failures return 422 before creating the transaction service. The service is closed on success and on provider failure; existing generic provider failures still return 500.

Response `in_amount` and `out_amount` remain JSON strings. A valid fixture or returned quote is not authorization to sign or send a transaction. This change does not establish price freshness, executable liquidity, exact USD valuation, or a live swap integration.

## Reproduce without keys or network

```bash
.venv/bin/python -m unittest discover -s apps/api/tests -p test_swap_quote_units.py -v
.venv/bin/python scripts/demo_swap_quote.py
```

Expected: 14 test methods pass. The demonstration runs five HTTP cases against the real route with an injected quote service; external provider calls and submitted orders are both zero. It labels its output as a fixture, not a market price.

The regression was first run against the previous implementation: a legacy float request returned HTTP 200 when the test expected 422. After the fix it is rejected. The suite separately verifies USDC units, maximum u64, one base unit, malformed JSON, slippage, quote mismatch and client cleanup.

[Jupiter's quote reference](https://developers.jup.ag/docs/api-reference/swap/v1/quote) documents a raw u64 amount and ExactIn/ExactOut semantics. The inspected reference is legacy Swap V1 and points to V2; offline tests do not certify current provider/API compatibility. Validate the live integration separately before enabling real transactions.
