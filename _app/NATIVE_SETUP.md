# Native session setup

Use **Set up AI assistants** on Overview. HA opens dedicated persistent
browser profiles, discovers rendered account/model/mode/effort controls, and
selects exact matching options when available. Sign-in, passkeys and 2FA stay in
the provider browser; HA does not copy credentials from your ordinary profile.
Pending setup resumes after sign-in and after an application restart.

The first setup, saved as **Default**, is:

| Assistant | Provider and surface | Model | Effort |
| --- | --- | --- | --- |
| Worker 1 | Claude native | Opus 5.5 | High |
| Worker 2 | ChatGPT Work | GPT-6 Astra | High |
| Worker 3 | ChatGPT Chat | GPT-6 | Extra High |
| Adviser | Separate ChatGPT Chat conversation | GPT-6 | Extra High |
| Reviewer | Separate ChatGPT Chat conversation | GPT-6 | High |

## Choosing models and saving setups

**AI assistants** has one sign-in button per service (ChatGPT, Claude) on its
top row; one sign-in covers every assistant on that service. Each assistant's
row has a **Model** and a **Thinking** list. **Read choices** opens each
service's own model menu in HA's tab, records every model, Chat/Work mode and
thinking level it offers, and puts your selection there back; until then the
lists show only models already in use or saved. **Use** switches the
assistants to the lists as shown; only assistants whose choice changed are set
up again, with a new conversation and their own usage check when the service or
mode changes. **Save** replaces the selected setup (including **Default**) and
**Save as new** keeps another one. Pause a running project before using another
setup or reading choices; both change models in the services' tabs.

A route becomes eligible only after the exact controls are observed, its shared
allowance permits admission, and a new persistent conversation passes a two-way
file canary. HA uploads a file whose bytes are absent from the prompt, verifies
its exact echoed bytes, and downloads a native copy with the same SHA-256.
Homepage URLs and model self-reports cannot establish conversation identity.
Role conversations remain distinct even when they share an account/profile.

## Allowance and unrecognized controls

Discovery never treats missing usage telemetry as unlimited. If the provider
exposes an unambiguous Usage link and labeled percentage progress bars, HA can
map them. Otherwise, the setup state explains the unresolved mapping. Advanced
settings accept observed selectors and a same-provider usage URL. A numeric
window specifies its name, selector, full-match regex with named `percent`
capture, explicit `used` or `remaining` interpretation, and task/handoff/reserve/
uncertainty estimates. Estimates are reservations, not measured forecasts.

There is at most one usage-page attempt per shared account/surface in each
rolling 24 hours, including failed attempts. Role setup can reuse that retained
allowance observation only for the same account/scope. Admission requires at
least 10% in every applicable window and enough capacity for reservations.
Unknown mappings remain blocked. `no_numeric_limit_confirmed` is valid only with
actual provider evidence, never as a workaround for absent telemetry.

Exact provider labels and controls can change. Missing, hidden, ambiguous or
mismatched controls stop dispatch. To correct advanced bindings, save settings;
HA stops pending native setup, closes its browser contexts and discards stale
selectors before using the new configuration. Active work must first settle.

## Renewal and interrupted delivery

Sessions renew at a configured turn threshold (80 by default), an observed
context-limit notice, or an explicit renewal request. The old binding remains
active until the replacement passes identity and both transfer checks. Durable
session intent and commit records reconcile a crash around settings persistence.
Unresolved deliveries prevent a work conversation from being abandoned.

Every outgoing envelope has a durable ID. HA requires the complete visible
user-message echo, associates the reply by native turn order, and waits for a
completion control belonging to that turn. Raw partial/malformed responses are
logged before parsing. An uncertain send is never blindly repeated. When the
page advertises the public WebMCP conversation action, HA can use it; otherwise
it uses rendered DOM controls. It does not fall back after a dispatched action.

## Native learning

The evaluation controller gives each paired baseline/candidate trial a separate
conversation, keeps expected answers local, verifies outputs independently, and
resumes retained trials after quota waits. Sharing permission is checked before
each request and promotion; isolated trial tabs close after their evidence is
saved. Evaluations reserve capacity in the same pool as project work.

Fresh conversations alone do not establish that a provider's account-wide memory
or personalization is disabled. That isolation, exact live routing and genuine
cross-project improvements still need signed-in acceptance evidence. Local
fixtures do not certify native learning effectiveness.

No model API, changed model/effort, Chat-for-Work substitution, paid overage or
manual message relay satisfies native acceptance. Current evidence and limits
are recorded in `release_status.json`.

## Recovery after sign-in

If a scheduled allowance check finds a sign-in screen or broken conversation
binding, HA can recheck the native conversation after it is restored. Rechecks
are spaced at least 30 seconds apart, require previously accepted two-way
transport and retain the original allowance timestamp. They send no model
request and do not visit the usage page again. Stale, unknown or exhausted
allowance cannot be renewed by a conversation recheck.

Quota warnings retain the affected route across application restarts. An adviser
warning does not incorrectly mark the active worker as exhausted. Native setup
waits for quota automatically; reopening setup cannot clear a recorded quota
exhaustion using an older balance.
