
indi-allsky can list your camera on the [Allsky Map](https://www.thomasjacquin.com/allsky-map/), the public map run by the Allsky project.

This is a separate, optional integration. It is not the **Allsky Map** integration (allsky-map.com) on the neighboring settings tab, and enabling one does not enable the other.

> **Your listing is public.** Treat everything you publish as visible to anyone, including your coordinates, owner and location name, website and image. Even with reduced coordinates, a picture or description can reveal where a camera is. Publication is off by default, and enabling it does not register you automatically. Your first listing is normally created when you press Register / Update.

## Quick start

1. Open **Config → Allsky Map (Allsky project)**.
2. Turn on **Enable publication**.
3. Choose **Location accuracy** (see [Location accuracy and Privacy Mode](#location-accuracy-and-privacy-mode)).
4. Optionally add an **Image URL** (a public image anyone can open without logging in), a **Website URL** and **Equipment**.
5. **Save** the configuration.
6. Press **Preview saved metadata** and check every row.
7. Press **Register / Update** to publish exactly what you previewed.

Preview never contacts the map. It shows what would be published from your *saved* settings, so save first. If you change and save settings after previewing, preview again before registering.

Once registered, changes can be published automatically while publication is enabled and active. For an existing listing, saved changes can be published before you Preview them. See [Keeping your listing up to date](#keeping-your-listing-up-to-date).

## What gets published

Everything below is sent to the map. **Preview** shows exactly what will be sent, with the installation identifier hidden.

| Item | Where it comes from |
|---|---|
| Coordinates | Your saved location, reduced by *Location accuracy* and *Privacy Mode* |
| Location name, Owner, Lens | Your existing indi-allsky settings |
| Camera | Detected camera name |
| Computer | Board model (or "Generic PC") and RAM |
| Version | indi-allsky release version, e.g. `indi_v2026.11.01` |
| Website URL, Image URL, Equipment | The Allsky Map settings |
| Installation identifier | A random ID that tells the map which listing is yours (see [Installation identifier and backups](#installation-identifier-and-backups)) |

Location name and Owner are published as `Unknown` when not configured or blank. Your saved settings are not changed.

Not sent: image files, your configuration, passwords or credentials, or your computer's machine ID. The Image URL is only a link. indi-allsky does not upload or host the image.

## Location accuracy and Privacy Mode

### Privacy Mode always wins

If indi-allsky's global **Privacy Mode** is on, coordinates are rounded to whole degrees (e.g. `35N, 13E`) and the accuracy setting is ignored. Your accuracy choice is kept, and applies again when Privacy Mode is turned off. If your listing is active, that change is published automatically.

For this integration, Privacy Mode only affects coordinates. Owner, location name, URLs and images are still published.

### Accuracy options

With Privacy Mode off, choose one of these:

| Option | What is published | Effect on marker position |
|---|---|---|
| Round to 2 decimal places (default) | Coordinates rounded to 0.01° | Up to ~0.56 km north–south; less east–west away from the equator (~0.35 km in the UK) |
| Exact saved location | Your saved coordinates, unchanged | None. **This can reveal your home.** |
| Approximate 0.5 / 1 / 2 / 5 km grid | The nearest point on a fixed grid of roughly that spacing | Usually 0 to about half the spacing in each direction, then limited by your saved location's precision (see example) |

### Worked example

These are actual outputs for two saved locations:

| Saved location | 2 decimal places (default) | 1 km grid | 5 km grid |
|---|---|---|---|
| 35.123, 12.654 | 35.12N, 12.65E | 35.126N, 12.65E | 35.11N, 12.641E |
| 35.1, 12.6 | 35.1N, 12.6E | 35.1N, 12.6E | 35.1N, 12.6E |

With Privacy Mode on, both rows publish `35N, 13E`.

The second row shows why precision matters. Published coordinates never have more decimal places than your saved location. In this example, saving the location with only one decimal place means every grid option publishes the same point. Low saved precision can reduce or eliminate differences between grid settings, although this is not guaranteed for every location.

### Things to know

- **Grids are not a privacy guarantee.** The grid is fixed, so the same location always gives the same point. A site that happens to sit near a grid point barely moves. A grid is not a random offset or a guaranteed privacy radius.
- **Saved precision.** indi-allsky saves manual and GPS locations to 3 decimal places (~100 m). A saved 35.100 counts as 35.1.
- **Your saved location is the only source.** This integration never reads GPS directly and never changes your saved location.
- **You can't take a location back.** Choosing a coarser setting later does not remove a more precise location that was already published.

## Keeping your listing up to date

While your listing is registered and publication is enabled, and nothing is holding it back (a pause, a review, a pending request, limits or a back-off), it refreshes about every **48 hours**. It also updates soon after any published detail changes:

- location or coordinates, including accuracy and Privacy Mode changes
- Owner, Location name or Lens
- Website URL, Image URL or Equipment
- detected camera or computer
- an indi-allsky upgrade that changes the published version number

The map hides entries that haven't been refreshed for more than 30 days.

### Limits

- **indi-allsky's own limit:** at most **5 ordinary attempts in any 24 hours** (a rolling window), at least one minute apart. Failed or uncertain attempts count, because the map may have received them.
- **The map's own limit:** the map keeps its own update count (normally 5 per day, by its own reckoning). Status shows the count from the map's last reply, not a live figure. If the map replies that its update limit has been reached, automatic updates wait at least 24 hours, and any other holds still apply. Other errors, including ones that mention a limit, may show Needs review instead.
- **Force** skips indi-allsky's 5-attempt limit and asks the map to override its limit. It still needs a Preview, still waits a minute after the last attempt, and still runs only one request at a time. It is never used automatically.
- **Remove** doesn't count towards the 5-attempt limit and doesn't wait for the one-minute gap. It still runs only one request at a time, and the map isn't guaranteed to accept it.

## Turning publication off or removing your listing

- **Disable:** turn off *Enable publication* and save. This stops all future updates, but your listing stays on the map until the map hides it (after 30 days without updates).
- **Remove and disable:** turns publication off and asks the map to delete your listing. Only a confirmed deletion counts as removed. Publication stays off even if deletion fails.

Either way, publication is **paused**. It stays paused even if another process later turns the Enable switch back on. To publish again: enable, **Preview** and **Register**.

A request that was already in progress when you disabled can still finish. It cannot be recalled.

## Status and troubleshooting

### Status badges

| Badge | Meaning | What to do |
|---|---|---|
| Registered | The map accepted your listing | Nothing |
| Not registered | indi-allsky has no confirmation of a listing. If an earlier request had an uncertain outcome, a listing may still exist. | Follow the quick start; if Needs review is also shown, check the public map first |
| Removed | The map confirmed deletion | Preview and Register to list again |
| Publishing active | Publication is enabled and automatic updates are allowed. It doesn't mean a request is running; limits and pending requests still apply. | Nothing |
| Publishing paused | You disabled or removed publication | Enable, Preview and Register to resume |
| Publishing off | Publication is disabled (not paused). A listing may still exist on the map. | Enable when ready, or use Remove to delete a listing |
| Needs review | A request may or may not have reached the map, or the map reported an error. Automatic updates stop and nothing is retried. | Check the public map, then Preview and Register, or Remove |
| Request pending | A request is recorded as pending. It may be queued or running, or it may have been interrupted. | Wait, then press Refresh status; if Needs review is also shown, check the public map |
| Changes not yet published | Your saved settings differ from the listing | Sent automatically if publishing is active; otherwise Preview and Register |

**Technical details** shows the raw status and the map's last reply, with the identifier hidden.

**A request that stays pending.** Don't keep resubmitting. Restarting indi-allsky expires stuck local tasks, but it won't necessarily clear the pending or review status, and it doesn't tell you whether the map received the request. Check the public map before deciding what to do next.

### Messages

| Message | What it means |
|---|---|
| Register / Update is greyed out | Run Preview first |
| "Preview the saved metadata before publication" | Settings changed since your Preview. Preview again. |
| "Publication suppressed; Preview and explicitly Register to resume" | Publication is paused. Enable, Preview and Register. |
| "Five ordinary attempts in the last 24 hours; wait for quota or explicitly force an update" | Wait for the 24-hour window, or use Force only after checking why updates were refused |
| "Wait one minute between map requests" | Try again after a minute. This applies to Force too. |
| "A different map request is pending; wait for it to finish" | Wait, then press Refresh status |
| Image or website URL rejected | Check the [URL rules](#url-rules) |
| "No active local camera metadata is available" | The active camera isn't a local camera, or no camera has connected yet |

## Reference

### Buttons

| Button | What it does |
|---|---|
| Preview saved metadata | Shows what would be published from the saved settings. Doesn't contact the map. Creates the installation identifier the first time. |
| Register / Update | Publishes the previewed details. The normal way to create the first listing, to resume after pausing, and after a Needs review state. |
| Force update… | Skips indi-allsky's 5-attempt limit and asks the map to override its limit. Still needs Preview and the one-minute gap. Never automatic. |
| Remove and disable… | Turns publication off and asks the map to delete your listing. Publication stays off even if deletion fails. |
| Refresh status | Reloads the status shown on the page. Doesn't contact the map. |

### URL rules

- Both URLs are optional. An Image URL on its own is fine; a Website URL needs an Image URL.
- They can be on different domains.
- They must be public `http` or `https` addresses:
  - no login
  - no `user:password@`
  - no `#fragment`
  - no private or local addresses (e.g. `192.168.x.x`, `localhost`, `*.local`)
- allsky-map.com image links cannot be used as the Image URL.

### Installation identifier and backups

The first Preview creates a random 32-character identifier and stores it in the indi-allsky database. The map uses it to know which listing is yours.

- **Keep it private.** Anyone with it could change or remove your listing. It is hidden in Preview, status and logs for this reason.
- It is not used to log in to indi-allsky, and it is not your computer's machine ID.
- It doesn't change when you disable, re-enable, remove or upgrade.
- It is included in **database** backups, not configuration exports. If you rebuild without restoring the database, the next Preview creates a new identifier. Publishing with it creates a separate listing; the rebuild itself doesn't register anything. The old listing is unaffected and stays until the map hides it.
- Don't run cloned installations from the same database: they would overwrite each other's listing.
