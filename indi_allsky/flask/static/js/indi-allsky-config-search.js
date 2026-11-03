// indi-allsky Configuration Live Search & Deep-Linking
// Zero-latency client-side DOM search across all configuration parameters

(function() {
    'use strict';

    let searchIndex = [];
    let currentResults = [];
    let selectedIndex = -1;
    let isShowingSuggestions = false;
    let activeFlashingRow = null;
    let flashCleanupTimer = null;
    let isSelectingResult = false;

    const SUGGESTED_SETTINGS = [
        'CCD_EXPOSURE_MAX',
        'CCD_CONFIG__NIGHT__GAIN',
        'LOCATION_LATITUDE',
        'TIMELAPSE_ENABLE',
        'IMAGE_SAVE_FITS'
    ];

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function buildSearchIndex() {
        const form = document.getElementById('form_config');
        if (!form) return [];

        const index = [];
        const seenIds = new Set();
        const elements = form.querySelectorAll('.tab-pane input[id], .tab-pane select[id], .tab-pane textarea[id]');

        elements.forEach(function(el) {
            const id = el.id;
            if (!id || seenIds.has(id)) return;
            if (id.includes('csrf_token') || el.type === 'hidden') return;
            seenIds.add(id);

            const tabPane = el.closest('.tab-pane');
            if (!tabPane) return;

            const tabId = tabPane.id.replace(/^nav-/, '');
            const tabBtn = document.querySelector('[data-tab-target="nav-' + tabId + '"]');
            const tabLabel = tabBtn ? tabBtn.textContent.trim() : tabId;

            // Extract Card / Section title
            const card = el.closest('.tw\\:card, .card');
            let section = '';
            if (card) {
                const sectionSpan = card.querySelector('span.tw\\:tracking-widest, span.tw\\:font-bold.tw\\:uppercase');
                if (sectionSpan) {
                    section = sectionSpan.textContent.trim();
                }
            }

            // Extract Label
            let label = '';
            const explicitLabel = form.querySelector('label[for="' + id + '"]');
            if (explicitLabel) {
                label = explicitLabel.textContent.trim();
            } else {
                const parentLabel = el.closest('label');
                if (parentLabel) {
                    const textSpan = parentLabel.querySelector('span');
                    label = textSpan ? textSpan.textContent.trim() : parentLabel.textContent.trim();
                } else {
                    const row = el.closest('.tw\\:grid, .tw\\:flex, .form-group');
                    if (row) {
                        const labelSpan = row.querySelector('span.tw\\:font-bold, label');
                        if (labelSpan) label = labelSpan.textContent.trim();
                    }
                }
            }
            if (!label) label = id;

            // Extract Description / Help text
            let desc = '';
            const row = el.closest('.tw\\:grid, .tw\\:flex, .form-group');
            if (row) {
                const descSpan = row.querySelector('span.tw\\:text-base-content\\/40, span.tw\\:text-base-content\\/50, span.tw\\:text-base-content\\/60, .help-block');
                if (descSpan) {
                    const candidate = descSpan.textContent.trim();
                    if (candidate && candidate !== label) {
                        desc = candidate;
                    }
                }
            }

            // Check if designated as Expert setting
            const isExpert = !!(
                el.closest('.config-expert') ||
                (tabBtn && tabBtn.classList.contains('config-expert'))
            );

            index.push({
                id: id,
                label: label,
                name: id,
                desc: desc,
                tab: tabId,
                tabLabel: tabLabel,
                section: section,
                isExpert: isExpert,
                searchText: (id + ' ' + label + ' ' + desc + ' ' + section + ' ' + tabLabel).toLowerCase()
            });
        });

        return index;
    }

    function getElementValueBadge(id) {
        const el = document.getElementById(id);
        if (!el) return '';

        if (el.type === 'checkbox') {
            if (el.checked) {
                return '<span class="tw:badge tw:badge-success tw:badge-outline tw:badge-xs tw:font-mono tw:font-bold tw:tracking-wider tw:py-0.5">ON</span>';
            } else {
                return '<span class="tw:badge tw:badge-ghost tw:badge-xs tw:font-mono tw:opacity-60 tw:py-0.5">OFF</span>';
            }
        }

        if (el.tagName === 'SELECT') {
            const opt = el.options[el.selectedIndex];
            const text = opt ? opt.text.trim() : el.value;
            if (text) {
                return '<span class="tw:badge tw:badge-neutral tw:badge-xs tw:font-mono tw:max-w-[130px] tw:truncate tw:py-0.5" title="' + escapeHtml(text) + '">' + escapeHtml(text) + '</span>';
            }
            return '';
        }

        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            if (el.type === 'password') {
                return el.value ? '<span class="tw:badge tw:badge-ghost tw:badge-xs tw:font-mono tw:opacity-60 tw:py-0.5">&bull;&bull;&bull;&bull;</span>' : '';
            }
            const val = el.value ? el.value.trim() : '';
            if (val) {
                return '<span class="tw:badge tw:badge-neutral tw:badge-xs tw:font-mono tw:max-w-[130px] tw:truncate tw:py-0.5" title="' + escapeHtml(val) + '">' + escapeHtml(val) + '</span>';
            }
        }

        return '';
    }

    const KNOWN_PARENT_MAP = {
        'IMAGE_SAVE_FITS_PERIOD': 'IMAGE_SAVE_FITS',
        'IMAGE_SAVE_FITS_PRE_DARK': 'IMAGE_SAVE_FITS',
        'DEW_HEATER__TEMP_USER_VAR_SLOT': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__DEWPOINT_USER_VAR_SLOT': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__MANUAL_TARGET': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__LEVEL_LOW': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__LEVEL_MED': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__LEVEL_HIGH': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__THOLD_DIFF_LOW': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__THOLD_DIFF_MED': 'DEW_HEATER__THOLD_ENABLE',
        'DEW_HEATER__THOLD_DIFF_HIGH': 'DEW_HEATER__THOLD_ENABLE',
        'FAN__TEMP_USER_VAR_SLOT': 'FAN__THOLD_ENABLE',
        'FAN__TARGET': 'FAN__THOLD_ENABLE',
        'FAN__LEVEL_LOW': 'FAN__THOLD_ENABLE',
        'FAN__LEVEL_MED': 'FAN__THOLD_ENABLE',
        'FAN__LEVEL_HIGH': 'FAN__THOLD_ENABLE',
        'FAN__THOLD_DIFF_LOW': 'FAN__THOLD_ENABLE',
        'FAN__THOLD_DIFF_MED': 'FAN__THOLD_ENABLE',
        'FAN__THOLD_DIFF_HIGH': 'FAN__THOLD_ENABLE',
        'CCD_TEMP': 'CCD_COOLING',
        'CCD_TEMP_DAY': 'CCD_COOLING_DAY',
        'FOCUS_DELAY': 'FOCUS_MODE',
        'STARTRAILS_MOON_ALT_THOLD': 'STARTRAILS_MOONMODE_THOLD',
        'STARTRAILS_MOON_PHASE_THOLD': 'STARTRAILS_MOONMODE_THOLD',
        'LIBCAMERA__AWB': 'LIBCAMERA__AWB_ENABLE',
        'LIBCAMERA__AWB_DAY': 'LIBCAMERA__AWB_ENABLE_DAY',
        'DAYTIME_TIMELAPSE': 'TIMELAPSE_ENABLE',
        'WEB_LOCAL_IMAGES_ADMIN': 'WEB_NONLOCAL_IMAGES',
        'FISH2PANO__ENABLE_CARDINAL_DIRS': 'CARDINAL_DIRS__ENABLE',
        'IMAGE_EXPORT_FOLDER': 'IMAGE_EXPORT_RAW',
    };

    function findParentToggle(fieldId) {
        if (!fieldId) return null;

        let candidateId = KNOWN_PARENT_MAP[fieldId];
        if (!candidateId) {
            if (fieldId.startsWith('FITSHEADERS__')) {
                candidateId = 'IMAGE_SAVE_FITS';
            } else if (fieldId.startsWith('TIMELAPSE_') && fieldId !== 'TIMELAPSE_ENABLE') {
                candidateId = 'TIMELAPSE_ENABLE';
            } else if (fieldId.startsWith('STARTRAILS_') && fieldId !== 'STARTRAILS_TIMELAPSE') {
                candidateId = 'STARTRAILS_TIMELAPSE';
            } else if (fieldId.startsWith('FILETRANSFER_') && fieldId !== 'FILETRANSFER_ENABLE') {
                candidateId = 'FILETRANSFER_ENABLE';
            } else if (fieldId.includes('__')) {
                const prefix = fieldId.split('__')[0];
                if (fieldId !== prefix + '__ENABLE') {
                    candidateId = prefix + '__ENABLE';
                }
            }
        }

        if (candidateId) {
            const parentEl = document.getElementById(candidateId);
            if (parentEl && parentEl.type === 'checkbox' && !parentEl.checked) {
                return parentEl;
            }
        }
        return null;
    }

    function getElementLabel(el) {
        if (!el) return '';
        const explicitLabel = document.querySelector('label[for="' + el.id + '"]');
        if (explicitLabel) return explicitLabel.textContent.trim();
        const findFn = (window.indiAllskyTabs && window.indiAllskyTabs.findSettingContainer)
            ? window.indiAllskyTabs.findSettingContainer
            : function(node) { return node.closest('.tw\\:flex, .tw\\:grid, .form-group') || node; };
        const row = findFn(el);
        if (row) {
            const span = row.querySelector('span.tw\\:font-bold, span.tw\\:tracking-wider, label');
            if (span) return span.textContent.trim();
        }
        return el.id;
    }

    function clearParentToggleFlash() {
        if (activeFlashingRow) {
            activeFlashingRow.classList.remove('parent-toggle-flashing');
            activeFlashingRow = null;
        }
        document.querySelectorAll('.parent-toggle-hint').forEach(function(h) {
            h.remove();
        });
        if (flashCleanupTimer) {
            clearTimeout(flashCleanupTimer);
            flashCleanupTimer = null;
        }
    }

    function flashParentToggle(parentEl, childLabel, targetEl) {
        clearParentToggleFlash();

        const findContainer = (window.indiAllskyTabs && window.indiAllskyTabs.findSettingContainer)
            ? window.indiAllskyTabs.findSettingContainer
            : function(node) { return node.closest('.tw\\:flex, .tw\\:grid, .form-group') || node; };

        const parentRow = findContainer(parentEl);
        if (parentRow) {
            parentRow.classList.add('parent-toggle-flashing');
            activeFlashingRow = parentRow;

            // Full-width guidance banner on the parent toggle row
            if (!parentRow.querySelector('.parent-toggle-hint')) {
                const parentHint = document.createElement('div');
                parentHint.className = 'parent-toggle-hint tw:alert tw:alert-warning tw:py-2 tw:px-3 tw:text-xs tw:mt-2.5 tw:w-full tw:flex tw:items-center tw:gap-2 tw:rounded-[var(--radius-box)]';
                parentHint.innerHTML = '<i class="tw:icon-[lucide--info] tw:w-4 tw:h-4 tw:shrink-0 tw:text-warning-content"></i><span class="tw:text-warning-content">Enable this toggle to activate dependent setting <strong>' + escapeHtml(childLabel) + '</strong></span>';
                parentRow.appendChild(parentHint);
            }
        }

        const parentLabel = getElementLabel(parentEl) || parentEl.id;

        // Actionable guidance banner attached directly to the target child setting
        const targetRow = targetEl ? findContainer(targetEl) : null;
        if (targetRow && !targetRow.querySelector('.parent-toggle-hint')) {
            const childHint = document.createElement('div');
            childHint.className = 'parent-toggle-hint tw:alert tw:alert-warning tw:py-2 tw:px-3 tw:text-xs tw:mt-2.5 tw:w-full tw:flex tw:items-center tw:justify-between tw:gap-3 tw:rounded-[var(--radius-box)] tw:shadow-sm';

            const hintBody = document.createElement('div');
            hintBody.className = 'tw:flex tw:items-center tw:gap-2 tw:min-w-0';
            hintBody.innerHTML = '<i class="tw:icon-[lucide--alert-triangle] tw:w-4 tw:h-4 tw:shrink-0 tw:text-warning-content"></i>' +
                '<span class="tw:text-warning-content">Setting is currently inactive because <strong>' + escapeHtml(parentLabel) + '</strong> is disabled.</span>';
            childHint.appendChild(hintBody);

            const enableBtn = document.createElement('button');
            enableBtn.type = 'button';
            enableBtn.className = 'btn-enable-parent tw:btn tw:btn-xs tw:btn-neutral tw:shrink-0 tw:gap-1';
            enableBtn.innerHTML = '<i class="tw:icon-[lucide--power] tw:w-3 tw:h-3"></i>Enable Now';

            enableBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                parentEl.checked = true;
                const changeEvt = typeof Event !== 'undefined' ? new Event('change', { bubbles: true }) : { type: 'change' };
                parentEl.dispatchEvent(changeEvt);
                if (typeof window.jQuery !== 'undefined') {
                    window.jQuery(parentEl).trigger('change');
                }
                childHint.className = 'parent-toggle-hint tw:alert tw:alert-success tw:py-2 tw:px-3 tw:text-xs tw:mt-2.5 tw:w-full tw:flex tw:items-center tw:gap-2 tw:rounded-[var(--radius-box)]';
                childHint.innerHTML = '<i class="tw:icon-[lucide--check-circle-2] tw:w-4 tw:h-4 tw:shrink-0 tw:text-success-content"></i><span class="tw:text-success-content"><strong>' + escapeHtml(parentLabel) + '</strong> enabled successfully.</span>';
                if (activeFlashingRow) {
                    activeFlashingRow.classList.remove('parent-toggle-flashing');
                    activeFlashingRow = null;
                }
                setTimeout(function() {
                    childHint.remove();
                }, 2000);
            });

            childHint.appendChild(enableBtn);
            targetRow.appendChild(childHint);
        }

        function handleDismiss() {
            if (isSelectingResult) return;
            clearParentToggleFlash();
            document.removeEventListener('click', handleDismiss);
            document.removeEventListener('keydown', handleDismiss);
            parentEl.removeEventListener('change', handleDismiss);
        }

        setTimeout(function() {
            document.addEventListener('click', handleDismiss, { once: true });
            document.addEventListener('keydown', handleDismiss, { once: true });
            parentEl.addEventListener('change', handleDismiss, { once: true });
        }, 150);

        flashCleanupTimer = setTimeout(clearParentToggleFlash, 15000);
    }

    function highlightMatches(text, queryTokens) {
        if (!text) return '';
        let escaped = escapeHtml(text);
        if (!queryTokens.length) return escaped;

        queryTokens.forEach(function(token) {
            if (!token) return;
            const regex = new RegExp('(' + token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
            escaped = escaped.replace(regex, '<mark class="tw:bg-primary/20 tw:text-primary tw:font-semibold tw:rounded-xs tw:px-0.5">$1</mark>');
        });
        return escaped;
    }

    function search(query) {
        const trimmed = query.trim().toLowerCase();
        if (!trimmed) return [];

        const tokens = trimmed.split(/\s+/).filter(Boolean);

        const scored = [];
        searchIndex.forEach(function(item) {
            let score = 0;
            const idLower = item.id.toLowerCase();
            const labelLower = item.label.toLowerCase();
            const descLower = item.desc.toLowerCase();
            const secLower = item.section.toLowerCase();
            const tabLower = item.tabLabel.toLowerCase();

            let allMatched = true;
            for (let i = 0; i < tokens.length; i++) {
                const t = tokens[i];
                if (!item.searchText.includes(t)) {
                    allMatched = false;
                    break;
                }
                if (idLower === t) score += 100;
                else if (idLower.includes(t)) score += 30;

                if (labelLower.startsWith(t)) score += 60;
                else if (labelLower.includes(t)) score += 40;

                if (secLower.includes(t)) score += 15;
                if (tabLower.includes(t)) score += 10;
                if (descLower.includes(t)) score += 5;
            }

            if (allMatched) {
                scored.push({ item: item, score: score });
            }
        });

        scored.sort(function(a, b) {
            return b.score - a.score;
        });

        return scored.slice(0, 15).map(function(s) { return s.item; });
    }

    function getSuggestedResults() {
        const results = [];
        SUGGESTED_SETTINGS.forEach(function(id) {
            const item = searchIndex.find(function(it) { return it.id === id; });
            if (item) results.push(item);
        });
        return results;
    }

    function renderResults(results, query, isSuggestions) {
        const dropdown = document.getElementById('config-search-dropdown');
        const container = document.getElementById('config-search-results');
        const countSpan = document.getElementById('config-search-count');
        const titleSpan = document.getElementById('config-search-header-title');
        const tokens = (query || '').trim().toLowerCase().split(/\s+/).filter(Boolean);

        currentResults = results;
        selectedIndex = results.length > 0 ? 0 : -1;
        isShowingSuggestions = !!isSuggestions;

        if (titleSpan) {
            titleSpan.textContent = isSuggestions ? 'Suggested Settings' : 'Matching Settings';
        }

        if (!results.length) {
            container.innerHTML = '<div class="tw:px-4 tw:py-6 tw:text-center tw:text-sm tw:text-base-content/60">' +
                '<i class="tw:icon-[lucide--search-x] tw:w-8 tw:h-8 tw:mx-auto tw:mb-2 tw:opacity-40 tw:block"></i>' +
                'No configuration settings found matching <span class="tw:font-semibold tw:text-base-content">&ldquo;' + escapeHtml(query) + '&rdquo;</span>' +
                '</div>';
            if (countSpan) countSpan.textContent = '0 results';
            dropdown.style.display = 'block';
            return;
        }

        let html = '';
        results.forEach(function(item, idx) {
            const isSelected = idx === selectedIndex;
            const expertBadge = item.isExpert
                ? '<span class="tw:badge tw:badge-warning tw:badge-outline tw:badge-xs tw:font-bold tw:uppercase tw:tracking-wider tw:py-0.5">Advanced</span>'
                : '';
            const sectionText = item.section ? escapeHtml(item.section) + ' &rsaquo; ' : '';
            const descOrId = item.desc ? highlightMatches(item.desc, tokens) : '<span class="tw:font-mono tw:text-[0.6875rem] tw:opacity-60">' + escapeHtml(item.name) + '</span>';
            const valueBadge = getElementValueBadge(item.id);

            html += '<div class="config-search-item tw:px-3.5 tw:py-2.5 tw:cursor-pointer tw:border-b tw:border-base-200/80 last:tw:border-b-0 tw:transition-all ' +
                (isSelected ? 'tw:bg-primary/10 tw:border-l-4 tw:border-l-primary' : 'hover:tw:bg-base-200/70') +
                '" role="option" data-index="' + idx + '" id="config-search-opt-' + idx + '">' +
                '<div class="tw:flex tw:items-center tw:justify-between tw:gap-2">' +
                '  <div class="tw:flex tw:items-center tw:gap-2 tw:min-w-0">' +
                '    <i class="tw:icon-[lucide--sliders-horizontal] tw:w-3.5 tw:h-3.5 tw:text-primary tw:shrink-0"></i>' +
                '    <span class="tw:font-semibold tw:text-sm tw:text-base-content tw:truncate">' + highlightMatches(item.label, tokens) + '</span>' +
                '  </div>' +
                '  <div class="tw:flex tw:items-center tw:gap-1.5 tw:shrink-0">' +
                valueBadge +
                expertBadge +
                '    <span class="tw:badge tw:badge-neutral tw:badge-xs tw:font-bold tw:uppercase tw:tracking-wider tw:py-0.5">' + escapeHtml(item.tabLabel) + '</span>' +
                '  </div>' +
                '</div>' +
                '<div class="tw:text-xs tw:text-base-content/60 tw:mt-1 tw:pl-5.5 tw:truncate">' +
                '  <span class="tw:text-base-content/40">' + sectionText + '</span>' + descOrId +
                '</div>' +
                '</div>';
        });

        container.innerHTML = html;
        if (countSpan) {
            countSpan.textContent = isSuggestions
                ? results.length + ' suggestions'
                : results.length + (results.length === 15 ? '+ results' : ' results');
        }
        dropdown.style.display = 'block';

        const itemEls = container.querySelectorAll('.config-search-item');
        itemEls.forEach(function(el) {
            el.addEventListener('mouseenter', function() {
                const idx = parseInt(el.getAttribute('data-index'), 10);
                setSelectedItem(idx, false);
            });
            el.addEventListener('mousedown', function(e) {
                e.preventDefault();
                const idx = parseInt(el.getAttribute('data-index'), 10);
                if (currentResults[idx]) {
                    selectResult(currentResults[idx]);
                }
            });
            el.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
            });
        });
    }

    function setSelectedItem(idx, scrollIntoView) {
        const container = document.getElementById('config-search-results');
        if (!container) return;

        selectedIndex = idx;
        const items = container.querySelectorAll('.config-search-item');
        items.forEach(function(el, i) {
            const isMatch = i === selectedIndex;
            el.classList.toggle('tw:bg-primary/10', isMatch);
            el.classList.toggle('tw:border-l-4', isMatch);
            el.classList.toggle('tw:border-l-primary', isMatch);
            el.setAttribute('aria-selected', isMatch ? 'true' : 'false');
            if (isMatch && scrollIntoView) {
                el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        });
    }

    function selectResult(item) {
        if (!item) return;

        isSelectingResult = true;
        setTimeout(function() {
            isSelectingResult = false;
        }, 300);

        const dropdown = document.getElementById('config-search-dropdown');
        if (dropdown) dropdown.style.display = 'none';

        // 1. Promote to Expert mode if item is an expert setting and view is in simple mode
        const form = document.getElementById('form_config');
        if (item.isExpert && form && form.classList.contains('mode-simple') && typeof window.setConfigMode === 'function') {
            window.setConfigMode('expert');
        }

        // 2. Switch to the tab containing the field
        if (window.indiAllskyTabs && typeof window.indiAllskyTabs.showTab === 'function') {
            window.indiAllskyTabs.showTab(item.tab);
        } else {
            const tabBtn = document.querySelector('[data-tab-target="nav-' + item.tab + '"]');
            if (tabBtn) tabBtn.click();
        }

        // 3. Expand accordion if the field is inside a collapsed section
        const targetEl = document.getElementById(item.id);
        if (targetEl) {
            const collapse = targetEl.closest('.tw\\:collapse, .collapse');
            if (collapse) {
                collapse.classList.add('tw:collapse-open');
                const cb = collapse.querySelector('input[type="checkbox"]');
                if (cb) cb.checked = true;
            }
        }

        // 4. Highlight field container and scroll into view
        if (window.indiAllskyTabs && typeof window.indiAllskyTabs.highlightField === 'function') {
            window.indiAllskyTabs.highlightField(item.id);
        }

        // 5. Check if parent master toggle is disabled and flash it with guidance hint
        const parentToggle = findParentToggle(item.id);
        if (parentToggle) {
            flashParentToggle(parentToggle, item.label, targetEl);
        } else {
            clearParentToggleFlash();
        }

        // 6. Update browser URL hash
        history.replaceState(null, '', '#' + item.tab + '-' + item.id);

        // 7. Focus target element for immediate editing (preventScroll preserves smooth center alignment)
        setTimeout(function() {
            if (targetEl && typeof targetEl.focus === 'function') {
                targetEl.focus({ preventScroll: true });
            }
        }, 200);
    }

    function init() {
        const input = document.getElementById('config-search-input');
        const dropdown = document.getElementById('config-search-dropdown');
        const clearBtn = document.getElementById('config-search-clear');
        const wrapper = document.getElementById('config-search-wrapper');

        if (!input || !dropdown) return;

        // Build index from the configuration DOM
        searchIndex = buildSearchIndex();

        // Expose dynamic re-indexing hook
        window.reindexConfigSearch = function() {
            searchIndex = buildSearchIndex();
        };

        // MutationObserver to automatically re-index if hardware rows/tabs are dynamically inserted
        const tabContent = document.getElementById('nav-tabContent');
        if (tabContent && typeof MutationObserver !== 'undefined') {
            let debounceTimer = null;
            const observer = new MutationObserver(function() {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(function() {
                    searchIndex = buildSearchIndex();
                }, 300);
            });
            observer.observe(tabContent, { childList: true, subtree: true });
        }

        // Focus event: show suggested settings if input is empty
        input.addEventListener('focus', function() {
            if (!input.value.trim()) {
                const suggestions = getSuggestedResults();
                if (suggestions.length) {
                    renderResults(suggestions, '', true);
                }
            }
        });

        input.addEventListener('input', function() {
            const query = input.value;
            if (clearBtn) {
                clearBtn.style.display = query.length > 0 ? 'flex' : 'none';
            }

            if (!query.trim()) {
                const suggestions = getSuggestedResults();
                if (suggestions.length) {
                    renderResults(suggestions, '', true);
                } else {
                    dropdown.style.display = 'none';
                    currentResults = [];
                    selectedIndex = -1;
                }
                return;
            }

            const results = search(query);
            renderResults(results, query, false);
        });

        input.addEventListener('keydown', function(e) {
            if (dropdown.style.display === 'none' || !currentResults.length) {
                if (e.key === 'ArrowDown') {
                    if (input.value.trim()) {
                        const results = search(input.value);
                        renderResults(results, input.value, false);
                    } else {
                        const suggestions = getSuggestedResults();
                        if (suggestions.length) {
                            renderResults(suggestions, '', true);
                        }
                    }
                    e.preventDefault();
                }
                return;
            }

            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    setSelectedItem((selectedIndex + 1) % currentResults.length, true);
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    setSelectedItem((selectedIndex - 1 + currentResults.length) % currentResults.length, true);
                    break;
                case 'Enter':
                    e.preventDefault();
                    if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
                        selectResult(currentResults[selectedIndex]);
                    }
                    break;
                case 'Escape':
                    e.preventDefault();
                    dropdown.style.display = 'none';
                    input.blur();
                    break;
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function(e) {
                e.preventDefault();
                input.value = '';
                clearBtn.style.display = 'none';
                dropdown.style.display = 'none';
                currentResults = [];
                selectedIndex = -1;
                input.focus();
            });
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            if (wrapper && !wrapper.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });

        // Global hotkey: Ctrl+K, Cmd+K, or "/" to focus search
        document.addEventListener('keydown', function(e) {
            const isCtrlK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k';
            const isSlash = e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

            if (isCtrlK || isSlash) {
                e.preventDefault();
                input.focus();
                input.select();
                if (input.value.trim()) {
                    const results = search(input.value);
                    renderResults(results, input.value, false);
                } else {
                    const suggestions = getSuggestedResults();
                    if (suggestions.length) {
                        renderResults(suggestions, '', true);
                    }
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
