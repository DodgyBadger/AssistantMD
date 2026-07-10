(function vaultPathPickerModule(window, document) {
    function createVaultPathPickerController({ elements, icons, utils }) {
        const { escapeHtml } = utils;
        let activePickerId = '';
        let activeOnClose = null;

        function selectedVault() {
            return elements.vaultSelector?.value || '';
        }

        function workspacePath() {
            return (elements.workspacePathInput?.value || '').trim();
        }

        function open(options = {}) {
            const vault = selectedVault();
            if (!vault) {
                alert(options.missingVaultMessage || 'Select a vault first.');
                return;
            }
            close();
            const id = options.id || 'vault-path-picker-modal';
            activePickerId = id;
            activeOnClose = typeof options.onClose === 'function' ? options.onClose : null;
            const mode = options.mode === 'directories' ? 'directories' : 'files';
            const titleId = `${id}-title`;
            const showSearch = mode === 'files';
            const overlay = document.createElement('div');
            overlay.id = id;
            overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
            overlay.innerHTML = `
                <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="${escapeHtml(titleId)}">
                    <div class="app-modal-header flex-none">
                        <div class="app-modal-title-block">
                            <h2 id="${escapeHtml(titleId)}" class="text-lg font-semibold text-txt-primary">${escapeHtml(options.title || 'Choose Path')}</h2>
                            <p class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(options.subtitle || vault)}</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-compact" data-vault-path-picker-close aria-label="Close" title="Close">${icons.X_ICON_SVG}</button>
                        </div>
                    </div>
                    <div class="p-4 flex-1 min-h-0 flex flex-col gap-3">
                        ${options.selectedLabel ? `
                            <div class="p-3 rounded border border-border-primary bg-app-elevated">
                                <div class="text-xs uppercase text-txt-secondary">${escapeHtml(options.selectedLabel)}</div>
                                <div class="mt-1 text-sm cell-mono text-txt-primary">${escapeHtml(options.selectedPath || 'None')}</div>
                            </div>
                        ` : ''}
                        ${showSearch ? `
                            <div class="file-reference-toolbar">
                                <input data-vault-path-picker-query type="search" class="file-reference-search" placeholder="${escapeHtml(options.searchPlaceholder || 'Search files in workspace or vault...')}" aria-label="Search files" />
                                <select data-vault-path-picker-scope class="file-reference-scope" aria-label="Search scope">
                                    <option value="workspace">Workspace</option>
                                    <option value="vault">Vault</option>
                                </select>
                            </div>
                        ` : ''}
                        <div data-vault-path-picker-status class="text-sm text-txt-secondary">Loading...</div>
                        <div data-vault-path-picker-results class="workspace-tree flex-1 min-h-0 overflow-y-auto" role="tree"></div>
                    </div>
                </section>
            `;
            document.body.appendChild(overlay);

            const queryInput = overlay.querySelector('[data-vault-path-picker-query]');
            const scopeSelect = overlay.querySelector('[data-vault-path-picker-scope]');
            if (scopeSelect instanceof HTMLSelectElement) {
                scopeSelect.value = options.initialScope || (workspacePath() ? 'workspace' : 'vault');
            }

            overlay.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (event.target === overlay || target.closest('[data-vault-path-picker-close]')) {
                    close();
                    return;
                }
                const toggle = target.closest('[data-vault-path-picker-toggle]');
                if (toggle instanceof HTMLElement) {
                    await toggleNode(overlay, toggle, options);
                    return;
                }
                const selectButton = target.closest('[data-vault-path-picker-select]');
                if (selectButton instanceof HTMLElement) {
                    const path = selectButton.getAttribute('data-vault-path-picker-select') || '';
                    const kind = selectButton.getAttribute('data-vault-path-picker-kind') || '';
                    if (kind === 'directory' && options.expandDirectoriesOnSelect) {
                        const row = selectButton.closest('[data-vault-path-picker-row]');
                        const rowToggle = row?.querySelector(':scope > .workspace-tree-row [data-vault-path-picker-toggle]');
                        if (rowToggle instanceof HTMLElement) {
                            await toggleNode(overlay, rowToggle, options);
                        }
                        return;
                    }
                    if (path || mode === 'directories') {
                        options.onSelect?.({ path, kind });
                        if (options.closeOnSelect !== false) close();
                    }
                }
            });

            const debouncedLoad = debounce(() => loadResults(overlay, options), 180);
            queryInput?.addEventListener('input', debouncedLoad);
            scopeSelect?.addEventListener('change', () => loadResults(overlay, options));
            const initialPath = options.revealInitialPath ? '' : (options.initialPath || '');
            loadResults(overlay, options, initialPath)
                .then(() => {
                    if (options.revealInitialPath) {
                        return revealPath(overlay, options, options.revealInitialPath);
                    }
                    return null;
                })
                .catch((error) => {
                    setStatus(overlay, `Unable to load paths: ${error.message}`, true);
                });
        }

        function close() {
            if (activePickerId) {
                document.getElementById(activePickerId)?.remove();
            }
            document.getElementById('vault-path-picker-modal')?.remove();
            activeOnClose?.();
            activePickerId = '';
            activeOnClose = null;
        }

        async function loadResults(overlay, options, path = '') {
            const mode = options.mode === 'directories' ? 'directories' : 'files';
            setStatus(overlay, 'Loading...');
            const results = overlay.querySelector('[data-vault-path-picker-results]');
            if (!(results instanceof HTMLElement)) return;
            results.innerHTML = '';
            if (mode === 'directories') {
                const payload = await fetchDirectories(path);
                const items = Array.isArray(payload.directories)
                    ? payload.directories.map((item) => ({ ...item, kind: 'directory' }))
                    : [];
                setStatus(overlay, items.length ? `Showing ${items.length} folder${items.length === 1 ? '' : 's'}.` : 'No folders available.');
                results.innerHTML = items.length
                    ? items.map((item) => renderRow(item, 0, options)).join('')
                    : `<p class="text-sm text-txt-secondary">${escapeHtml(options.emptyText || 'No folders available.')}</p>`;
                return;
            }

            const queryInput = overlay.querySelector('[data-vault-path-picker-query]');
            const scopeSelect = overlay.querySelector('[data-vault-path-picker-scope]');
            const payload = await fetchFileRefs({
                path,
                query: queryInput instanceof HTMLInputElement ? queryInput.value.trim() : '',
                scope: scopeSelect instanceof HTMLSelectElement ? scopeSelect.value : 'workspace',
            });
            const items = Array.isArray(payload.items) ? payload.items : [];
            setStatus(overlay, renderFileStatus(payload, items.length));
            results.innerHTML = items.length
                ? items.map((item) => renderRow(item, 0, options)).join('')
                : `<p class="text-sm text-txt-secondary">${escapeHtml(options.emptyText || 'No matching files.')}</p>`;
        }

        async function fetchDirectories(path) {
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            const suffix = params.toString() ? `?${params.toString()}` : '';
            const response = await fetch(`api/vaults/${encodeURIComponent(selectedVault())}/directories${suffix}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        async function fetchFileRefs({ path = '', query = '', scope = 'workspace' } = {}) {
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            if (workspacePath()) params.set('workspace_path', workspacePath());
            if (query) params.set('query', query);
            params.set('scope', scope || 'workspace');
            const response = await fetch(`api/vaults/${encodeURIComponent(selectedVault())}/file-refs?${params.toString()}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        async function toggleNode(overlay, toggle, options) {
            const row = toggle.closest('[data-vault-path-picker-row]');
            if (!(row instanceof HTMLElement)) return;
            const children = row.querySelector(':scope > [data-vault-path-picker-children]');
            if (!(children instanceof HTMLElement)) return;
            const expanded = toggle.getAttribute('aria-expanded') === 'true';
            if (expanded) {
                toggle.setAttribute('aria-expanded', 'false');
                children.classList.add('hidden');
                return;
            }
            toggle.setAttribute('aria-expanded', 'true');
            children.classList.remove('hidden');
            if (children.dataset.loaded === 'true') return;

            const path = row.getAttribute('data-vault-path-picker-row') || '';
            children.innerHTML = '<div class="py-1 text-xs text-txt-secondary">Loading...</div>';
            try {
                const mode = options.mode === 'directories' ? 'directories' : 'files';
                const depth = Number.parseInt(row.getAttribute('data-vault-path-picker-depth') || '0', 10) + 1;
                if (mode === 'directories') {
                    const payload = await fetchDirectories(path);
                    const items = Array.isArray(payload.directories)
                        ? payload.directories.map((item) => ({ ...item, kind: 'directory' }))
                        : [];
                    children.innerHTML = items.length
                        ? items.map((item) => renderRow(item, depth, options)).join('')
                        : '<div class="py-1 text-xs text-txt-secondary">No child folders.</div>';
                } else {
                    const payload = await fetchFileRefs({ path, scope: 'vault' });
                    const items = Array.isArray(payload.items) ? payload.items : [];
                    children.innerHTML = items.length
                        ? items.map((item) => renderRow(item, depth, options)).join('')
                        : '<div class="py-1 text-xs text-txt-secondary">No child files.</div>';
                }
                children.dataset.loaded = 'true';
            } catch (error) {
                children.innerHTML = `<div class="py-1 text-xs state-error">Unable to load paths: ${escapeHtml(error.message)}</div>`;
            }
        }

        async function revealPath(overlay, options, path) {
            const segments = String(path || '').split('/').filter(Boolean);
            let currentPath = '';
            let revealedRow = null;
            for (const segment of segments) {
                currentPath = currentPath ? `${currentPath}/${segment}` : segment;
                const row = Array.from(
                    overlay.querySelectorAll('[data-vault-path-picker-row]')
                ).find((candidate) => (
                    candidate instanceof HTMLElement
                    && candidate.getAttribute('data-vault-path-picker-row') === currentPath
                ));
                if (!(row instanceof HTMLElement)) return;
                revealedRow = row;
                const toggle = row.querySelector(
                    ':scope > .workspace-tree-row [data-vault-path-picker-toggle]'
                );
                if (
                    toggle instanceof HTMLElement
                    && toggle.getAttribute('aria-expanded') !== 'true'
                ) {
                    await toggleNode(overlay, toggle, options);
                }
            }
            revealedRow?.scrollIntoView({ block: 'nearest' });
        }

        function renderRow(item, depth, options) {
            const path = String(item.path || '');
            const name = String(item.name || path || 'Path');
            const kind = item.kind === 'directory' ? 'directory' : 'file';
            const indent = Math.min(Math.max(depth, 0) * 1.25, 5);
            const canExpand = kind === 'directory' && item.has_children;
            const icon = kind === 'directory' ? icons.FOLDER_ICON_SVG : fileIcon();
            return `
                <div data-vault-path-picker-row="${escapeHtml(path)}" data-vault-path-picker-depth="${depth}">
                    <div class="workspace-tree-row" role="treeitem" style="padding-left: ${indent}rem;">
                        ${canExpand
                            ? `<button type="button" class="workspace-tree-toggle" data-vault-path-picker-toggle aria-expanded="false" aria-label="Expand ${escapeHtml(name)}">
                                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                                    <path d="M7.25 4.75 12.75 10l-5.5 5.25" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                                </svg>
                            </button>`
                            : '<span class="workspace-tree-spacer" aria-hidden="true"></span>'}
                        <button type="button" class="workspace-tree-select" data-vault-path-picker-select="${escapeHtml(path)}" data-vault-path-picker-kind="${escapeHtml(kind)}">
                            <span class="file-reference-row-icon" aria-hidden="true">${icon}</span>
                            <span class="workspace-tree-label min-w-0">
                                <span class="workspace-tree-name">${escapeHtml(name)}</span>
                                ${options.showPath === false ? '' : `<span class="file-reference-path">${escapeHtml(path)}</span>`}
                            </span>
                        </button>
                    </div>
                    <div class="workspace-tree-children hidden" data-vault-path-picker-children></div>
                </div>
            `;
        }

        function fileIcon() {
            return icons.FILE_TEXT_ICON_SVG || `
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                    <path d="M14 2v4a2 2 0 0 0 2 2h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                </svg>
            `;
        }

        function renderFileStatus(payload, count) {
            const scope = payload?.scope === 'vault' ? 'vault' : 'workspace';
            const base = payload?.query ? `Found ${count}` : `Showing ${count}`;
            const root = payload?.path || (scope === 'workspace' ? workspacePath() : '') || 'vault root';
            return `${base} item${count === 1 ? '' : 's'} in ${scope}: ${root}`;
        }

        function setStatus(overlay, message, error = false) {
            const status = overlay.querySelector('[data-vault-path-picker-status]');
            if (!status) return;
            status.innerHTML = error ? `<span class="state-error">${escapeHtml(message)}</span>` : escapeHtml(message);
        }

        function debounce(fn, delayMs) {
            let timer = null;
            return (...args) => {
                if (timer) window.clearTimeout(timer);
                timer = window.setTimeout(() => fn(...args), delayMs);
            };
        }

        return Object.freeze({ open, close });
    }

    window.VaultPathPicker = Object.freeze({
        create: createVaultPathPickerController,
    });
})(window, document);
