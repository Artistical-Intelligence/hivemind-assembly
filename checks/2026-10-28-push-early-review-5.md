# Independent check, 2026-10-28 (fifth)

- Item: push early, check later, after the fixes for review 4 (up to cef1f4b)
- Checker: a new, separate Claude session with a fresh context, given only the owner's request, the code and the earlier reports; it did not see the writer's conversation. It read and ran code only.
- Result: **failed**: items 1, 3, 5, 6 and 7 passed; 2 and 4 failed.
- All findings of review 4 were confirmed fixed.

## Findings (verified by the checker with scratch tests)

1. A file written outside HA that changed on GitHub while HA was checking it lost its markers when the older version passed.
2. While any marker file was refused by the privacy filter (for example STATUS.md in a folder HA never sends to GitHub), HA kept treating already-checked files as its own and removed markers others later added for them.
3. Edge case, safe direction: a check finishing during another push could make HA re-adopt its own row as written elsewhere, causing a needless recheck.
4. Edge case: a key-like text in someone else's CHECKS_STATUS.md row stops HA's updates of that file on GitHub.
5. Polish: the writer was told STATUS.md says what is wrong (it now points to the report); stored findings weren't shown on the Projects page.
