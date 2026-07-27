// Tab deep-linking & tab switching via native JavaScript (Bootstrap-Free)
//
// Supported hash formats:
//   #camera                        — open the tab whose panel ID is "nav-camera"
//   #nav-camera                    — same, full panel ID form
//   #processing-SOME_FIELD__NAME   — open Processing tab and highlight that field
//   #doesnotexist-SOME_FIELD__NAME — bad tab name: fall back to finding the field
//   #camera-DETECT_MASK            — tab found but field is elsewhere: field wins
//   #SOME_FIELD__NAME              — no tab: find the field, open its tab

(function() {
    function parseHash(hash) {
        let raw = hash.replace(/^#/, '');
        if (raw.startsWith('nav-')) raw = raw.slice(4);
        const sep = raw.indexOf('-');
        if (sep === -1) return { tab: raw, field: null };
        return { tab: raw.slice(0, sep), field: raw.slice(sep + 1) };
    }

    function showTab(tabName) {
        const targetId = 'nav-' + tabName;
        const targetPane = document.getElementById(targetId);

        if (!targetPane) return false;

        // Hide all tab panes
        document.querySelectorAll('.tab-pane').forEach(function(pane) {
            pane.classList.remove('show', 'active');
            pane.style.display = 'none';
        });

        // Show active tab pane
        targetPane.classList.add('show', 'active');
        targetPane.style.display = 'block';

        // Update active tab buttons
        document.querySelectorAll('[data-tab-target]').forEach(function(btn) {
            const isMatch = btn.getAttribute('data-tab-target') === targetId || btn.getAttribute('data-bs-target') === '#' + targetId;
            btn.classList.toggle('tw:tab-active', isMatch);
            btn.classList.toggle('active', isMatch);
            if (isMatch) {
                btn.setAttribute('aria-selected', 'true');
            } else {
                btn.setAttribute('aria-selected', 'false');
            }
        });

        return true;
    }

    function highlightField(fieldId) {
        const el = document.getElementById(fieldId);
        if (!el) return;

        // Open any collapsed accordion section that contains this field
        const collapse = el.closest('.tw:collapse, .collapse');
        if (collapse) {
            const checkbox = collapse.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.checked = true;
            }
        }

        // Highlight the field container
        const row = el.closest('.tw:flex, .tw:grid, .form-group') || el;
        row.classList.add('field-highlight');

        setTimeout(function() {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 200);
    }

    function clearHighlights() {
        document.querySelectorAll('.field-highlight').forEach(function(el) {
            el.classList.remove('field-highlight');
        });
    }

    function findFieldTab(fieldId) {
        const el = document.getElementById(fieldId);
        if (!el) return null;
        const panel = el.closest('.tab-pane');
        if (!panel) return null;
        return panel.id.replace(/^nav-/, '');
    }

    function activateTabFromHash(hash) {
        if (!hash) return;
        clearHighlights();
        const { tab, field } = parseHash(hash);

        let activeTab = tab;
        if (field) {
            const actualTab = findFieldTab(field);
            if (actualTab) activeTab = actualTab;
        }

        if (showTab(activeTab)) {
            if (field) highlightField(field);
            history.replaceState(null, '', '#' + activeTab + (field ? '-' + field : ''));
        } else {
            const fieldId = field || tab;
            const foundTab = findFieldTab(fieldId);
            if (foundTab && showTab(foundTab)) {
                highlightField(fieldId);
                history.replaceState(null, '', '#' + foundTab + '-' + fieldId);
            }
        }
    }

    function init() {
        const tabButtons = document.querySelectorAll('[data-tab-target], [data-bs-toggle="tab"]');
        if (!tabButtons.length) return;

        tabButtons.forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                let targetId = btn.getAttribute('data-tab-target') || btn.getAttribute('data-bs-target');
                if (targetId) {
                    targetId = targetId.replace(/^#/, '');
                    const tabName = targetId.replace(/^nav-/, '');
                    showTab(tabName);
                    history.replaceState(null, '', '#' + tabName);
                }
            });
        });

        // Initialize from URL hash or default to camera
        const initialHash = window.location.hash || '#camera';
        activateTabFromHash(initialHash);

        window.addEventListener('hashchange', function() {
            activateTabFromHash(window.location.hash);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
