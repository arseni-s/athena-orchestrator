# Correctness: Harbormaster

## Sources of truth
- `docs/decisions/0003-booking-rules.md`: what a booking is and when two overlap.
- `docs/decisions/0004-pricing.md`: rates, seasons, length bands, rounding.
- `harbormaster/booking/rules.py`: the only place overlap is decided.

## Check
- Bookings are half-open nights `[arrive, depart)`. A boat leaving on the 5th and one
  arriving on the 5th do not overlap.
- No double booking under concurrency: the database constraint (exclusion on berth and
  date range) decides, never a read-then-write in Python. A check only in Python is a
  Blocker.
- Prices come from `pricing.quote()` only. Any arithmetic on money elsewhere is Major.
- Money is integer cents end to end. A float anywhere in a price path is a Blocker.
- A cancelled booking frees the berth and never appears on the dock sheet.

## Cases to trace
- Two requests for berth 12, same nights, arriving within the same millisecond.
- A stay from 30 March to 2 April crossing the season change on 1 April.
- A 9.99 m boat against the 10 m length band.
- Cancel after payment, then rebook the same berth for the same nights.
- A booking for zero nights, and one for 400 nights.

## Heavy tools
A throwaway local Postgres (`docker compose up -d db`) to check constraints and
migrations. Nothing else.
