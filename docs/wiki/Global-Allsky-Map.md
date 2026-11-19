# Global Allsky Map (AllskyTeam)

indi-allsky can list your camera on the [AllskyTeam Global Allsky Map](https://www.thomasjacquin.com/allsky-map/), the public map run by the Allsky project.

This is a separate, optional integration. It is not the **Allsky Map** integration (allsky-map.com) on the neighboring settings tab, and enabling one does not enable the other.

Publication is off by default. First publication requires explicit Register; existing enabled registrations can update automatically. Preview itself sends no request.

## What gets published

Everything below is sent to the map service; listing metadata is public. **Preview** shows the exact listing metadata, with the private installation identifier hidden.

| Item | Source |
|---|---|
| Coordinates | Your saved location, reduced according to *Location accuracy* and *Privacy Mode* |
| Location name, Owner, Lens | Your existing indi-allsky settings |
| Camera | Detected camera name |
| Computer | Board model (or "Generic PC") and RAM |
| INDI-AllSky version | Release version, e.g. `indi_v2026.11.01` |
| Website URL, Image URL, Equipment | The Global Allsky Map settings |
| Installation identifier | A random ID that identifies your listing (see below) |

Not sent: image files, your configuration, credentials, or your host machine ID. The Image URL is only a link; indi-allsky does not upload or host the image.

## Location accuracy and privacy

**Privacy Mode always wins.** If indi-allsky's global *Privacy Mode* is on, whole-degree coordinates (e.g. `35N, 13E`) are published and the accuracy setting is ignored. Your accuracy choice is kept and applies again when Privacy Mode is turned off. That change can publish automatically while registration is active, enabled and not under a suppression or review hold.

For this integration, Privacy Mode only affects coordinates. Owner, location name, URLs and images are still published, and pictures or text can reveal where a camera is.

With Privacy Mode off, choose one of:

| Option | What is published | How far the marker can move from your saved location |
|---|---|---|
| Round to 2 decimal places (default) | Coordinates rounded to 0.01° | up to ~0.56 km per axis at the equator; less east–west away from the equator |
| Exact saved location | Your saved coordinates as stored | none — **can reveal your home** |
| Approximate 0.5 / 1 / 2 / 5 km grid | The nearest point on a fixed grid of roughly that spacing | nominally up to half a grid spacing per axis before rounding to the precision of your saved location; not a displacement or privacy guarantee |

Things to know:

- Grids are deterministic. The same location always gives the same point, and a site that happens to sit near a grid point barely moves. A grid is **not** a guaranteed privacy radius or random offset.
- Published coordinates are limited by the precision of your saved location. Normal manual and GPS updates save up to 3 decimal places (~100 m); stored trailing zeros do not establish extra precision. Rounding to your saved location’s precision can alter or eliminate the requested grid spacing. The Global Map integration never reads GPS directly or changes your saved location.
- Choosing a coarser setting later does not remove locations that were already public.

## Setting up

1. Open **Config → Global Allsky Map**.
2. Turn on **Enable publication**.
3. Choose **Location accuracy**.
4. Optionally add an **Image URL** (a public image anyone can open without logging in), a **Website URL**, and **Equipment**.
5. **Save** the configuration.
6. Press **Preview saved metadata** and check every row. Preview sends nothing; an existing active registration may update automatically.
7. Press **Register / Update** to publish exactly what you previewed.

### URL rules

- Both URLs are optional. An Image URL on its own is fine; a Website URL needs an Image URL.
- They can be on different domains.
- They must be public `http`/`https` addresses: no login, no `user:password@`, no `#fragment`, no private or local addresses (e.g. `192.168.x.x`, `localhost`, `*.local`).
- allsky-map.com image links cannot be used as the Image URL.

## Buttons

| Button | What it does |
|---|---|
| Preview saved metadata | Shows what would be published from the **saved** configuration. Sends nothing. Creates the installation identifier the first time. |
| Register / Update | Publishes the previewed details. Required for the first listing and to resume after publishing was paused. |
| Force update… | Bypasses the local ordinary-attempt cap and asks the server to override its update limit. Still requires Preview, single-flight ownership and the one-minute guard. Deliberate only; never automatic. |
| Remove and disable… | Turns publication off and asks the map to delete the listing. Publication stays off even if deletion fails. |
| Refresh status | Reloads local status. Sends nothing. |

## Automatic updates and limits

While registered and enabled, with no suppression or review hold, the listing refreshes about every **48 hours**, and soon after any published detail changes. That includes location or coordinates, Owner, Lens, Privacy Mode, the URLs, Equipment, the detected camera or computer, and an INDI-AllSky upgrade that changes the published canonical version.

The map hides entries that haven't refreshed for more than 30 days.

Limits:

- The client permits at most **5 ordinary attempts in a rolling 24 hours**, at least one minute apart. Failed or uncertain attempts count, because the server may have received them. The server normally permits five updates per day. Server counts use the server’s own accounting window; status shows the count at the last response, not a live quota query.
- **Force** bypasses the local ordinary cap and requests the server-limit override. The one-minute guard and single-flight protection still apply; it is never automatic.
- **Remove** is exempt from the local ordinary budget and one-minute guard, but retains single-flight protection. Server acceptance is not guaranteed.

## Turning publication off

- **Disable** (turn off *Enable publication* and save) stops all future updates, but your listing stays on the map until it expires.
- **Remove and disable** also asks the map to delete the listing. Only a confirmed deletion counts as removed.

Either way, publication stays **paused** even if other settings later turn the Enable switch back on. To publish again, enable, **Preview**, and **Register**. A request that was already in progress when you disabled can still finish; it cannot be recalled.

## Status

| Status | Meaning | What to do |
|---|---|---|
| Registered | The map accepted your listing | Nothing |
| Publishing paused | You disabled or removed publication | Preview and Register to resume |
| Needs review | A request may or may not have reached the server, or the server reported an error. Automatic updates are paused; nothing is retried automatically. | Check the public map, then Preview and Register (or Remove) |
| Request pending | A request is queued or running | Wait, then Refresh status |
| Changes not yet published | Saved settings differ from the listing | Sent automatically if publishing is active; otherwise Register |

*Technical details* shows the raw status and the last server response, with the identifier hidden. If a task remains running, preserve the evidence for administrator review rather than repeatedly submitting requests. A service restart can expire interrupted tasks; it does not prove whether the server received the request.

## Installation identifier and backups

The first Preview creates a random 32-character identifier and stores it in the indi-allsky database. The map uses it to know which listing is yours.

- It is not a password, an API key or your host machine ID.
- It does not change when you disable, re-enable, remove or upgrade.
- It is included in **database** backups, not configuration exports. If you rebuild without restoring the database, a new identifier creates a new listing and the old one may remain until it expires.
- Do not run cloned installations with the same database: they would overwrite each other's listing.

## Troubleshooting

- **Register is greyed out** — run Preview first. If you change and save settings after previewing, Preview again.
- **"Preview the saved metadata before publication"** — settings changed since your Preview. Preview again.
- **"Five ordinary attempts in the last 24 hours"** — wait, or deliberately choose Force only after reviewing the refusal; Force still requires one minute between publication attempts.
- **Image or website rejected** — check the URL rules above.
- **"No active local camera metadata"** — the active camera isn't a local camera, or no camera has connected yet.

## Development and tests

Automated tests must use synthetic fixtures or a local/mock HTTP endpoint. They must never contact the production Global Allsky Map or consume its quota.
