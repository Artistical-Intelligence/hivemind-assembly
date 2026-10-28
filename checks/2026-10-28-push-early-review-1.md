# Independent check, 2026-10-28

- Item: push early, check later (commits bb091ab..31529b8)
- Checker: a separate Claude session with a fresh context, given only the owner's request and the code; it did not see the writer's conversation. It read and ran code only.
- Result: **failed**: items 3, 6 and 7 passed; 1, 2, 4 and 5 failed or were partial.

## Findings (verified by the checker with scratch tests)

1. A binary file written by an assistant was sent as "remove" and deleted the file on GitHub.
2. The first push of a path overwrote a different version already on GitHub.
3. After a GitHub conflict, a passing check removed the marker although GitHub still held the other, unchecked version.
4. A malformed or hostile CHECKS_STATUS.md row (folder `../..`) made every later local marker write fail, and that error was swallowed, so pushing silently stopped.
5. Rows adopted from outside HA, binary files and files over 100,000 characters could never be checked, so the project could never be accepted; the Projects page gave a wrong error for outside-only items.
6. The check runner changed the shared state without the lock, so a file marked at the same moment could lose its marker.
7. The process-wide lock was held across GitHub calls, which could stall the assistant loop.
8. Minor: interrupted checks found at restart weren't pushed; "oldest file" wasn't the oldest; backticks in a folder cell became a directory name.

Not required here: project repositories get no CI release gate (the AGENTS.md rules ask assistants not to release), and imported reference material is flagged, not refused.
