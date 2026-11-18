# Global Allsky Map

This optional integration registers an INDI-AllSky installation on the
[AllskyTeam Global Allsky Map](https://www.thomasjacquin.com/allsky-map/).
It is independent of the existing **INDI-AllSky Map** integration at
allsky-map.com. Enabling either integration does not enable the other.

## Publication and consent

Registration is disabled by default. The public metadata includes location,
owner, coordinates, camera, lens, computer description, equipment, public URLs
and the canonical INDI-AllSky application version (for example
`indi_v2026.11.11`). No image bytes, full configuration, credentials or host
machine ID are uploaded. The Image URL points to an independently hosted public
image; this feature does not host or publish that image itself.

Global Privacy Mode is authoritative: Global Map retains whole-degree coordinates
and disables its location-accuracy control. With Privacy Mode off, choose Exact,
approximate 0.5/1/2/5 km grids, or Existing rounding (2 decimal places). Existing
rounding is the compatibility default, including when upgrading an older config;
upgrading alone does not move the published location. Turning Privacy Mode off
reactivates the saved choice, including Exact.

Exact uses the saved configured location without further rounding. Normal manual
and GPS config updates retain up to three decimals; Global Map does not read live
GPS or infer accuracy from GPS Enable. Grid output never has more fractional
places than each stored source axis (maximum six for grids). Lost trailing zeros
are not reconstructed: a source of 51.7 cannot acquire apparent extra precision.
These digits describe representation, not verified measurement uncertainty.

Grid labels mean approximate geographic spacing, adjusted for longitude at the
quantised latitude row; poles use a conventional zero longitude. Source precision
can limit or eliminate the effect of a finer grid. Rounding is deterministic,
not random anonymisation, a minimum displacement or a guaranteed error radius.
Exact can disclose your home/site; coarser settings cannot erase previous public
locations. Preview shows exactly the saved coordinates that will be sent.
Images, URLs and descriptions may still reveal the installation's location. Review all
metadata before publishing. Do not use allsky-map.com or its subdomains as the
Image URL: its image proxy is not third-party image hosting.

Both URLs may be empty, or an Image URL may be supplied alone. A Website URL
requires an Image URL, but they may use different domains. Supplied URLs must
be public HTTP(S) URLs without login requirements. Equipment
is sent identically in `equipmentinfo` and `allsky_settings.equipmentinfo`;
`website_settings` remains empty. No other configuration is serialized.

## Configuration and actions

Use the Global Allsky Map configuration panel as an administrator. Save the
settings, then choose **Preview saved metadata**. Preview makes no external
request; it creates the local installation identifier if needed and displays
exact public metadata with that identifier hidden. Opening the page never
registers the installation.

- **Register / Update** explicitly submits the previewed saved metadata. First
  registration always requires this action. A conflicting pending request must
  finish before a different manual request can be queued.
- **Force update** is a separately confirmed server-quota override. Use it only
  deliberately; it is never added to automatic requests or used to conceal
  uncertain outcomes.
- **Remove and disable** first saves Disable, then queues the server's deletion
  request. Publication stays disabled even if deletion fails. Only a confirmed
  `RETURN DELETED` establishes successful removal. An identifier with missing
  local publication history can still be used for removal after a backup restore.
- **Refresh status** reads local status and retained response evidence; it does
  not send a Map request.

Disabling alone stops future publication, including queued updates that have
not started. It does not delete an existing listing. Re-enabling preserves the
identifier. A request already in progress cannot be cancelled by disabling.

## Automatic refresh and quota

After successful registration, enabled installations refresh approximately every
48 hours and when published metadata changes. Changes to shared Owner, Location,
coordinates, Lens and Privacy Mode settings also publish automatically. Review
those shared settings with this in mind. Restarts/re-enabling can resume a due or
dirty scheduled update; they do not perform an immediate synchronous POST.
The Map hides entries not refreshed for more than 30 days.

Ordinary publication has a local limit of five attempts in a rolling 24 hours,
with at least one minute between publication attempts. Failed/ambiguous attempts
can count because the server may have received them. Remove is exempt from the
local ordinary budget and does not consume it, but still uses single-flight
protection; this is not a guarantee that the server will accept deletion.
Server update counts/limits, when returned, appear in status. A server quota
response delays automatic updates. Force remains explicit. No per-image
heartbeat, image upload or automatic repeat of an uncertain POST occurs.

## Failures and review

The client uses bounded HTTP timeouts, refuses redirects and requires the
protocol's terminal `RETURN` result; HTTP 200 alone is not success. Status keeps
bounded response text, HTTP status and Content-Type with the installation
identifier redacted. It does not retain request bodies or sensitive headers.

An uncertain/failed request can require manual review and pause automatic
publication. Inspect status/evidence and the public Map before deciding what to
do. Then Preview the saved metadata and explicitly choose Register / Update, or
confirm Remove if withdrawing. Preview or queueing is not itself an acknowledgement
of success. Do not edit database state or regenerate the identifier to bypass
review. A still-RUNNING interrupted worker may require separate operator recovery
before an action is safe; there is no automatic age-based unlock. During a database
outage, terminal task/status persistence cannot be guaranteed. Existing claims
are retained rather than blindly retried.

## Installation identity and backups

A random persistent 32-character installation identifier is stored in the
application database, separately from camera identity. It is the remote record
key, not authentication or an API key. Back up the database to preserve it.
Independent cloned installations must not publish using the same identity.
Losing/replacing it can orphan the previous listing and require Map-maintainer
assistance. Disabling, re-enabling or updating software does not regenerate it.

## Testing

Automated tests use temporary databases and synthetic HTTP responses. They must
never contact the production Map or consume its update quota. Real registration
is a separately authorised operation, not a regression-test step.
