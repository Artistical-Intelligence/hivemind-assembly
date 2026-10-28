# Independent check, 2026-10-28 (fourth)

- Item: push early, check later, after the fixes for review 3 (up to eee5ea7)
- Checker: a new, separate Claude session with a fresh context, given only the owner's request, the code and the earlier reports; it did not see the writer's conversation. It read and ran code only.
- Result: **failed**: items 1, 5, 6 and 7 passed; 2, 3 and 4 failed.
- All findings of reviews 1–3 were confirmed fixed.

## Findings (verified by the checker with scratch tests)

1. A file another assistant changed on GitHub was checked from HA's older copy in the project folder; the pass then removed the other assistant's markers, so the unchecked GitHub version got past the gate.
2. A write landing between a check's result and the push of its report could push the markers' removal without the report.
3. A failure note quoting something like a key made GitHub refuse the marker files, which then stopped updating.
4. Minor: removals queued while a project had no repository could later remove someone else's markers; the Projects page overstated "a different assistant" when only the writer's kind had usage left.
