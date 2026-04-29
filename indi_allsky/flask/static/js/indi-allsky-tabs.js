// Tab deep-linking via URL hash.
//
// Automatically initializes on DOMContentLoaded for any page that uses
// Bootstrap nav-tabs with the standard data-bs-toggle="tab" pattern.
//
// Supported hash formats:
//   #camera                        — open the tab whose panel ID is "nav-camera"
//   #nav-camera                    — same, full panel ID form
//   #processing-SOME_FIELD__NAME   — open Processing tab and highlight that field
//   #doesnotexist-SOME_FIELD__NAME — bad tab name: fall back to finding the field
//   #camera-DETECT_MASK            — tab found but field is elsewhere: field wins
//   #SOME_FIELD__NAME              — no tab: find the field, open its tab
//
// Tab names are the panel IDs without the "nav-" prefix (e.g. camera, image,
// processing ...).  Field names match the HTML input IDs which use underscores
// and double-underscores, so the first hyphen is always the tab/field separator.
//
// The hash is updated via replaceState when the user switches tabs so the URL
// always reflects the active tab and can be bookmarked or shared.

(function() {
    function parseHash(hash) {
        // Returns { tab: 'camera', field: 'SOME_FIELD' | null }
        let raw = hash.replace(/^#/, '');
        if (raw.startsWith('nav-')) raw = raw.slice(4);
        const sep = raw.indexOf('-');
        if (sep === -1) return { tab: raw, field: null };
        return { tab: raw.slice(0, sep), field: raw.slice(sep + 1) };
    }

    function highlightField(fieldId) {
        const el = document.getElementById(fieldId);
        if (!el) return;

        // Open any collapsed accordion section that contains this field
        const collapse = el.closest('.accordion-collapse');
        if (collapse && !collapse.classList.contains('show')) {
            bootstrap.Collapse.getOrCreateInstance(collapse).show();
        }

        // Highlight the whole form-group row so the label is included
        const row = el.closest('.form-group') || el;
        row.classList.add('field-highlight');

        // Scroll after a short delay to let accordion/tab transitions finish
        setTimeout(function() {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 350);
    }

    function clearHighlights() {
        document.querySelectorAll('.field-highlight').forEach(function(el) {
            el.classList.remove('field-highlight');
        });
    }

    function findFieldTab(fieldId) {
        // Return the tab short-name that contains this field, or null
        const el = document.getElementById(fieldId);
        if (!el) return null;
        const panel = el.closest('.tab-pane');
        if (!panel) return null;
        return panel.id.replace(/^nav-/, '');
    }

    function showTabThenHighlight(btn, fieldId) {
        const panel = document.querySelector(btn.getAttribute('data-bs-target'));
        if (panel && panel.classList.contains('active')) {
            // Tab already active — highlight immediately
            if (fieldId) highlightField(fieldId);
        } else {
            if (fieldId) {
                btn.addEventListener('shown.bs.tab', function() {
                    highlightField(fieldId);
                }, { once: true });
            }
            bootstrap.Tab.getOrCreateInstance(btn).show();
        }
    }

    function activateTabFromHash(hash) {
        if (!hash) return;
        clearHighlights();
        const { tab, field } = parseHash(hash);

        let btn = document.querySelector('[data-bs-target="#nav-' + tab + '"]');

        if (btn && field) {
            // Tab found and field requested — verify the field is actually in that tab.
            // If not, the field takes priority: use the tab the field lives in and fix the URL.
            const actualTab = findFieldTab(field);
            if (actualTab && actualTab !== tab) {
                btn = document.querySelector('[data-bs-target="#nav-' + actualTab + '"]');
                history.replaceState(null, '', '#' + actualTab + '-' + field);
            }
            showTabThenHighlight(btn, field);
        } else if (btn) {
            // Tab found, no field
            showTabThenHighlight(btn, null);
        } else {
            // Tab not found — treat field (or whole token) as the field ID
            const fieldId = field || tab;
            const foundTab = findFieldTab(fieldId);
            if (foundTab) {
                btn = document.querySelector('[data-bs-target="#nav-' + foundTab + '"]');
                showTabThenHighlight(btn, fieldId);
                // Update hash to canonical form now that we know the tab
                history.replaceState(null, '', '#' + foundTab + '-' + fieldId);
            }
            // If nothing found at all, leave the URL untouched
        }
    }

    function init() {
        // Skip pages that have no nav-tabs
        if (!document.querySelector('[data-bs-toggle="tab"]')) return;

        // Activate tab on page load if a hash is present, and whenever the
        // hash changes without a full page reload (e.g. manual URL bar edit)
        activateTabFromHash(window.location.hash);
        window.addEventListener('hashchange', function() {
            activateTabFromHash(window.location.hash);
        });

        // Update hash when the user switches tabs (without adding a history entry)
        document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function(btn) {
            btn.addEventListener('shown.bs.tab', function(e) {
                const panelId = e.target.getAttribute('data-bs-target').replace(/^#nav-/, '');
                history.replaceState(null, '', '#' + panelId);
            });
        });
    }

    document.addEventListener('DOMContentLoaded', init);
})();
