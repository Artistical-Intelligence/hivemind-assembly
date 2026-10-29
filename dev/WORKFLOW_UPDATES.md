# Workflow update: evidence, ownership and clean context

Owner request, 29 October 2026. Apply selected wave-orchestrator ideas to the
running application, without installing Wave or adding performance tracking.

## Scope and implementation

- Reconcile saved checks with actual file hashes when resuming and before
  completion. Preserve reports, reopen changed evidence, and never treat an
  absent marker as proof. Preserve unknown remote changes rather than overwriting.
- Retain HA's project-wide writer lease, epoch/revision fences and central saver.
  Make this ownership explicit in native briefs. No second lock or Git system.
- Give workers focused current-work instructions and evidence references, keeping
  required reading, source permissions and protected evaluators intact.
- Finish pending checks before starting more work. A failed check permits repair;
  a checker unavailable or still running must not silently allow backlog growth.
  Continue already authorized uncertain-operation reconciliation safely.
- Reuse pinned whole-project acceptance after integration; child checks never
  replace the root's verifier. Save drafts immediately, independently of approval.
- Let models request fresh conversation context with a bounded saved handoff.
  Preserve exact configured provider/model/mode/effort. Reconcile pending sends
  and mutations before resetting; reuse durable request identities on retry.
  Use a verified new-chat operation when service context clearing is unavailable.
  Never guess a clear command, delete conversations, or clear on a timer.

No new elapsed-time, token-cost or retry-performance records are requested.
Existing correctness evidence, operational recovery records, and independent
learning evaluations remain part of the application.

## Verification boundary

Changes remain checks pending until focused regression tests and an independent
review pass. Existing ownership and final-acceptance tests must remain green.
Native-service resets tested through fixtures are not live-provider acceptance.
The release workflow must pass before a new installer is described as available.
