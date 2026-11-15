# AllskyTeam Global Allsky Map

This optional integration publishes metadata to the Allsky project's public map.
It is independent of the existing `allsky-map.com` integration and defaults off.
It sends no image bytes, full configuration, host machine ID or camera commands.
The Image URL is a public link, not an image upload.

## Configure and consent

In **Config → Global Allsky Map**, enable publication and supply an optional public
Image URL and equipment description. The optional shared Public Website URL lives
in `WEBSITE.PUBLIC_URL`; it does not depend on another map integration. An image
URL alone is valid. A website requires an image URL on the same hostname (with an
optional `www.` prefix); public HTTP(S) URLs must not require credentials. URLs
are validated, never rewritten or fetched by this client.

Location, owner and lens reuse `LOCATION_NAME`, `OWNER` and `LENS_NAME`. Coordinates
reuse `LOCATION_LATITUDE`/`LOCATION_LONGITUDE`, rounded to two decimal degrees, or
whole degrees with `PRIVACY_MODE`. Camera name comes from active local database
metadata. Computer model/architecture and memory are derived locally. The actual
`indi_allsky.version.__version__` supplies the canonical dated application version
for this integration: `indi_v2026.11.11+trixie.qhy.globalmap.<commit>` becomes
`indi_v2026.11.11`. A dated release is unchanged; development/package suffixes
(`+`, `-`, `~` or `.` after the date) are omitted. The Global Map HTTP User-Agent
uses that same canonical version. Other application/package version reporting is
unchanged.

Save, then **Preview saved metadata**. Review the public location, owner, camera,
lens, computer, equipment, URLs and software version. Images and descriptive text
can identify a location despite coordinate rounding. Opening Config, previewing,
or enabling alone does not register. **Register / Update** explicitly queues the
first publication using the exact previewed saved metadata.

## Identity and lifecycle

Preview creates one cryptographically random 32-character lowercase hex installation
identifier in the existing database state table, key `GLOBAL_MAP_ID`. It is stable
across restarts, disable/re-enable and removal. It is a record identifier, **not
an authentication secret or API key**; the server currently has no authentication.
Back up the database to preserve it. Cloned installations must not share this
identity; do not regenerate an identity to evade server limits.

Scheduling/result state is JSON in `GLOBAL_MAP_STATE`; no schema migration is
required. Enabled, successfully registered installations refresh after about
48 hours or changed published metadata. Existing parent periodic tasks enqueue
ordinary VIDEO jobs; the VideoWorker makes the request. Changes coalesce into one
pending job, use fresh saved configuration and a payload fingerprint, and wait at
least five minutes after successful publication. No per-image heartbeat exists.
The map hides records not refreshed for 30 days.

Ordinary attempts are capped locally at five per rolling 24 hours, with at least
one minute between publication attempts. Server `ALREADY_UPDATED` suppresses
scheduled attempts for 24 hours. **Force update** requires preview and explicit
confirmation; it overrides only quota, never automatically runs or retries.
Errors with uncertain outcomes pause automatic publication for manual review.
A durable pre-I/O task claim prevents repeating an attempted POST after restart.
A queued refresh expired by parent restart can be replaced only if it was never
attempted. A stopped/expired attempted task remains visible as requiring review; preview and
an explicit subsequent Update/Remove are required to resolve uncertainty.

Disabling stops future queued/scheduled publication (an already transmitted request
cannot be recalled) but leaves the public listing. **Remove and disable** saves
Disable first, then queues the protocol deletion. It stays disabled even if the
server removal fails. Retry removal deliberately after checking status; do not
assume a timeout means the server did nothing.

## Protocol and status

The helper posts allowlisted JSON to
`https://www.thomasjacquin.com/allsky-map/postToMap.php` with JSON Accept/Content-Type.
`allsky_settings.equipmentinfo` duplicates top-level `equipmentinfo` (both empty
strings when unconfigured); `website_settings` remains an empty object. Deletion sends
only `machine_id` and `website_url: "DELETE"`. No host machine-id is read.

HTTP 200 alone is insufficient: the response must contain a terminal `RETURN`
INSERTED/UPDATED/DELETED status appropriate to the operation. ERROR, ALREADY_UPDATED,
MESSAGE-only, malformed and empty responses are not publication successes.
There are no redirects or automatic retries. The network socket timeout is
15 seconds; response size is bounded to 8 KiB. The worker does not hold a database
transaction across the network call. Status is available in the panel and ordinary
Video tasks/notifications. The identifier is hidden from the preview/status output.

Each attempted task stores `data.response_evidence`. The latest response is also
retained in the existing state table as `GLOBAL_MAP_RESPONSE`, so a paused failure
survives the normal three-day task cleanup. This adds no schema migration or file.
Evidence contains HTTP status, Content-Type only
(up to 256 characters), a UTF-8 body excerpt of at most 2 KiB, byte count/truncation
flags and any terminal status/counters. A 4096-character JSON storage budget can
further shorten control-character-heavy excerpts; truncation remains explicit.
Evidence is committed before parsing/failure
handling and available through the administrator's Refresh status action. The full
8 KiB protocol limit is unchanged; a truncated diagnostic is not used for parsing.
No request body or other response headers (cookies, authentication, etc.) are stored.
Literal echoed installation identifiers are redacted before truncation; detected
common escaped-ID bodies are withheld. HTML/JSON/BOM/MESSAGE-only/empty responses
remain failures, not invented successes. Transport failures distinguish missing
status from a known HTTP response; uncertain outcomes continue to pause scheduling.
Historical tasks without captured bodies cannot be retrospectively reconstructed.

After reviewing an ambiguous first attempt, **no SQL edit/reset/acknowledgement is
needed**. Once separately authorized to try again: install the corrected build,
Preview saved metadata anew (canonical version changes the fingerprint), then click
Register / Update exactly once, with force=false. The previous needs_review stays
set while this explicit manual task queues; only confirmed protocol success clears
it and establishes registered=true. Another unknown response keeps review required.
Ordinary quota/cooldown and the persistent identifier are retained. The old task
and its evidence are not rewritten. Do not use Force to bypass uncertainty.

## Development validation

Run the three `tests/test_global_allsky_map*.py` unittest modules in an isolated
process with application dependencies. They use in-memory SQLite, synthetic users
and cameras, actual Flask routes/forms and synchronous VideoWorker dispatch, with
external HTTP denied. Upstream form tests should run separately where their global
mock importers require isolation. A real registration is a separate explicitly
approved checkpoint; automated tests must never consume the public map quota.
