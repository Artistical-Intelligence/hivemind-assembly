# Independent check, 2026-10-28 (second)

- Item: push early, check later, after the fixes for review 1 (up to d4b4810)
- Checker: a new, separate Claude session with a fresh context, given only the owner's request, the code and review 1's report; it did not see the writer's conversation. It read and ran code only.
- Result: **failed**: items 4, 5, 6 and 7 passed; 1, 2 and 3 failed.
- Review 1's findings 1, 2, 6, 7 and 8 were confirmed fixed; 3, 4 and 5 were fixed but opened the problems below.

## Findings (verified by the checker with scratch tests)

1. When a project has no verified repository (or a push failed), every write counted as "GitHub has a different version", so passes and "I checked it" never cleared the marker, and the project could never be accepted.
2. If the commit carrying a check report failed, or the report was refused by the privacy filter, a later push still removed the markers without the report.
3. A write pushed while a check finished could make HA forget a folder, leaving a stale STATUS.md line on GitHub.
4. A CHECKS_STATUS.md row written elsewhere that names a folder stopped every check in the project.
5. Files the type filter keeps off GitHub were reported as "pushed before review".
