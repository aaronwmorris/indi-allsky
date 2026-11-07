# CSS Architecture & Guidelines

This directory contains the stylesheets and frontend compilation configuration for the `indi-allsky` Flask web interface.

## File Manifest

| File | Purpose | Source Control Status | Editable? |
|---|---|---|---|
| [`app.css`](app.css) | Tailwind CSS v4 root manifest and compilation configuration | Tracked | Yes (manifest & imports only) |
| [`custom.css`](custom.css) | Runtime user theme imports saved via the Web UI (`/user`) | Tracked (empty, 0 bytes) | **No** (managed by Web UI) |
| [`overrides.css`](overrides.css) | Repository-maintained custom styles and component overrides | Tracked | Yes (primary stylesheet) |
| [`dist.css`](dist.css) | Compiled CSS distribution bundle output by Tailwind CSS | Tracked | **No** (auto-generated) |

---

## Detailed File Responsibilities

### 1. `app.css` (Compilation Root)
`app.css` is the entry point for the `@tailwindcss/cli` build tool. It defines:
- The Tailwind utility prefix (`tw:`, e.g., `tw:flex`, `tw:btn`).
- Imports for local stylesheets: `@import "./custom.css";` and `@import "./overrides.css";`.
- Plugins: `@plugin "daisyui"` (with all themes enabled) and `@plugin "@iconify/tailwind4"`.

Do not write ad-hoc CSS rules directly into `app.css`.

### 2. `custom.css` (UI Theme Injector Target)
`custom.css` is exclusively reserved for end-user customizations injected via the **Custom Theme Injector** on the user profile page (`/indi-allsky/user`):
- The backend view (`AjaxCustomCssView` in `indi_allsky/flask/views.py`) reads this file directly and renders its content into a `<textarea>`.
- Saving custom CSS through the UI overwrites `custom.css` completely and triggers an automatic compilation of `dist.css`.
- **CRITICAL**: This file must remain **0 bytes (completely empty)** in Git. If rules or comments are added to `custom.css`, they will appear inside the user form textarea on `/user`, displace the HTML `placeholder`, and be permanently lost when a user saves a custom theme.

### 3. `overrides.css` (Repository Stylesheet)
All committed custom styles and adjustments belonging to the `indi-allsky` codebase **must be placed here**. This includes:
- Adjustments for third-party libraries (DataTables, PhotoSwipe, VirtualSky).
- Custom form elements, toggles, badges, and layout overrides (e.g., deep-link `.field-highlight`).
- Keyframe animations and visual effects.

### 4. `dist.css` (Compiled Output)
This file is generated automatically by `@tailwindcss/cli`. It is referenced in `indi_allsky/flask/templates/base.html`.
- **Never edit `dist.css` manually.** Any changes made directly to this file will be overwritten on the next build.

---

## Build Pipeline

To compile frontend stylesheets manually, run:

```bash
# Standard compilation
npm run build

# Minified compilation
npm run build:min
```

### Automated Git Hooks
- **Pre-commit**: The repository utilizes a pre-commit hook (`githooks/pre-commit`) that automatically runs `npm run build` and stages `dist.css` prior to committing.
- **Merge Driver**: The `.gitattributes` file registers a custom merge driver (`build_css`) configured to resolve merge conflicts in `dist.css` by automatically running `npm run build`.
