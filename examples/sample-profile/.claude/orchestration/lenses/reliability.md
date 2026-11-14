# Reliability: Harbormaster

## Check
- The payment provider call has a timeout and is idempotent (an idempotency key per
  booking). A retry never charges twice.
- A payment that succeeds while our request times out is reconciled by the nightly job;
  the booking is never left half-made without a visible state.
- The dock tablet keeps working on a weak signal: it shows the last loaded sheet, marked
  with its time, rather than a blank page.
- Times are stored in UTC and shown in the marina's time zone from config.

## Cases to trace
- The provider returns 500 after charging the card.
- The app restarts mid-booking.
- The tablet loses Wi-Fi for ten minutes during the morning check-in rush.
- The clocks change for summer time on a night with arrivals.

## Heavy tools
A throwaway local Postgres, to restart it under a running test.
