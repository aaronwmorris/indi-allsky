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

        // Ensure Expert mode is activated if the requested tab is an expert-only tab
        const targetBtn = document.querySelector('[data-tab-target="' + targetId + '"]');
        if (targetBtn && targetBtn.classList.contains('config-expert') && typeof window.setConfigMode === 'function') {
            window.setConfigMode('expert');
        }

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
            const isMatch = btn.getAttribute('data-tab-target') === targetId;
            btn.classList.toggle('tw:tab-active', isMatch);
            btn.classList.toggle('active', isMatch);
            if (isMatch) {
                btn.classList.add('tw:btn-primary');
                btn.classList.remove('tw:btn-ghost', 'tw:text-base-content/60');
                btn.setAttribute('aria-selected', 'true');
            } else {
                btn.classList.remove('tw:btn-primary');
                btn.classList.add('tw:btn-ghost', 'tw:text-base-content/60');
                btn.setAttribute('aria-selected', 'false');
            }
        });

        return true;
    }

    let highlightTimer = null;

    function clearHighlights() {
        if (highlightTimer) {
            clearTimeout(highlightTimer);
            highlightTimer = null;
        }
        document.querySelectorAll('.field-highlight').forEach(function(el) {
            el.classList.remove('field-highlight');
        });
    }

    function findSettingContainer(el) {
        if (!el) return null;

        // 1. Direct form-group container
        const formGroup = el.closest('.form-group');
        if (formGroup) return formGroup;

        // 2. Check for standard indi-allsky row with border-b or py-3 padding
        const standardRow = el.closest('[class*="tw:border-b"], .tw\\:py-3, .tw\\:py-2');
        if (standardRow && !standardRow.classList.contains('tw:card-body') && !standardRow.classList.contains('card-body') && !standardRow.classList.contains('tab-pane')) {
            return standardRow;
        }

        // 3. Walk up until container with label and input is found
        let candidate = el.parentElement;
        while (candidate && candidate !== document.body && !candidate.classList.contains('tab-pane')) {
            if (candidate.classList.contains('tw:card') || candidate.classList.contains('card')) {
                break;
            }
            const hasLabel = candidate.querySelector('label[for="' + el.id + '"]') ||
                             candidate.querySelector('span.tw\\:font-bold, span.tw\\:tracking-wider, label');
            if (hasLabel && candidate !== el.parentElement && (candidate.classList.contains('tw:grid') || candidate.classList.contains('tw:flex'))) {
                return candidate;
            }
            if (hasLabel && candidate.parentElement && (candidate.parentElement.classList.contains('tw:grid') || candidate.parentElement.classList.contains('tw:flex'))) {
                return candidate;
            }
            candidate = candidate.parentElement;
        }

        return el.closest('.tw\\:flex, .tw\\:grid') || el;
    }

    function highlightField(fieldId) {
        const el = document.getElementById(fieldId);
        if (!el) return;

        // Ensure Expert mode is activated if the targeted field is in an expert container
        if (typeof window.setConfigMode === 'function' && el.closest('.config-expert')) {
            window.setConfigMode('expert');
        }

        // Open any collapsed accordion section that contains this field
        const collapse = el.closest('.tw\\:collapse, .collapse');
        if (collapse) {
            collapse.classList.add('tw:collapse-open');
            const checkbox = collapse.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.checked = true;
            }
        }

        // Clear any previous highlights across the page
        clearHighlights();

        // Highlight the resolved field container
        const row = findSettingContainer(el);
        if (!row) return;

        row.classList.add('field-highlight');

        setTimeout(function() {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 150);

        // Auto-fade highlight after 4.5 seconds
        highlightTimer = setTimeout(function() {
            row.classList.remove('field-highlight');
        }, 4500);
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
        const tabButtons = document.querySelectorAll('[data-tab-target]');
        if (!tabButtons.length) return;

        tabButtons.forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                let targetId = btn.getAttribute('data-tab-target');
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

    window.indiAllskyTabs = {
        showTab: showTab,
        highlightField: highlightField,
        clearHighlights: clearHighlights,
        findSettingContainer: findSettingContainer,
        findFieldTab: findFieldTab,
        activateTabFromHash: activateTabFromHash,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
