# UX: Harbormaster

## Sources of truth
- `docs/features/booking-flow.md` and `docs/features/dock-sheet.md`.

## Check
- Booking pages work on a phone at 360 px wide, with no horizontal scroll.
- The dock sheet is readable on a 10-inch tablet in sunlight: large type, high contrast.
- Every error tells the boater what to do next; no raw exception text or stack trace.
- A price shown before payment is the price charged. A mismatch is a Blocker.
- Forms keep what the user typed when validation fails.

## Cases to trace
- A boat name of 40 characters on the dock sheet.
- The booking form submitted twice by a double tap.
- A sold-out week: what the boater sees instead of a calendar.
