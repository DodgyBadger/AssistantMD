(function vaultPathPickerModule(window, document) {
    function createVaultPathPickerController({ elements, icons, utils }) {
        const { escapeHtml, flashCopyFeedback, handleCopy } = utils;
        let activePickerId = '';
        let activeOnClose = null;
        let activeOptions = null;
        let rootLoadGeneration = 0;
        let rootAbortController = null;
        let activeUploadFiles = [];
        let uploadInProgress = false;

        function selectedVault() {
            return elements.vaultSelector?.value || '';
        }

        function workspacePath() {
            return (elements.workspacePathInput?.value || '').trim();
        }

        function isReadOnly(options) {
            return Boolean(options?.isReadOnly?.());
        }

        function open(options = {}) {
            const vault = options.vaultName || selectedVault();
            if (!vault) {
                alert(options.missingVaultMessage || 'Select a vault first.');
                return;
            }
            close();
            const id = options.id || 'vault-path-picker-modal';
            activePickerId = id;
            activeOnClose = typeof options.onClose === 'function' ? options.onClose : null;
            activeOptions = options;
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
                            ${options.explorer ? `
                                <form class="vault-explorer-header-create hidden" data-vault-explorer-header-create data-direct-path="true">
                                    <label class="vault-explorer-visually-hidden" data-vault-explorer-header-create-label for="${escapeHtml(id)}-create-path">New path</label>
                                    <input id="${escapeHtml(id)}-create-path" name="value" class="vault-explorer-header-create-input" autocomplete="off" required />
                                    <button type="submit" class="ui-icon-button is-primary is-compact" aria-label="Create" title="Create">${icons.CHECK_ICON_SVG}</button>
                                    <button type="button" class="ui-icon-button is-compact" data-vault-explorer-header-create-cancel aria-label="Cancel creation" title="Cancel creation">${icons.X_ICON_SVG}</button>
                                </form>
                                <div class="vault-explorer-header-new">
                                    <button type="button" class="ui-icon-button is-compact" data-vault-explorer-new aria-label="Create file or folder" title="Create file or folder">${icons.PLUS_ICON_SVG}</button>
                                    <div class="vault-explorer-header-new-menu hidden" data-vault-explorer-new-menu>
                                        <button type="button" data-vault-explorer-create-kind="file">New file</button>
                                        <button type="button" data-vault-explorer-create-kind="directory">New folder</button>
                                    </div>
                                </div>
                                <input type="file" class="hidden" data-vault-explorer-upload-input multiple />
                                <button type="button" class="ui-icon-button is-compact" data-vault-explorer-upload aria-label="Upload files" title="Upload files">${icons.IMPORT_ICON_SVG}</button>
                                <button type="button" class="ui-icon-button is-compact" data-vault-explorer-refresh aria-label="Refresh vault" title="Refresh vault">${icons.REFRESH_ICON_SVG}</button>
                            ` : ''}
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
                                <select data-vault-path-picker-scope class="file-reference-scope" aria-label="Search scope">
                                    <option value="workspace">Workspace only</option>
                                    <option value="vault">Entire vault</option>
                                </select>
                                <input data-vault-path-picker-query type="search" class="file-reference-search" placeholder="${escapeHtml(options.searchPlaceholder || 'Search workspace...')}" aria-label="Search files" />
                            </div>
                        ` : ''}
                        ${options.explorer ? '<div class="vault-explorer-action-panel hidden" data-vault-explorer-action-panel></div>' : ''}
                        <div data-vault-path-picker-status class="text-sm text-txt-secondary">Loading...</div>
                        <div data-vault-path-picker-results class="workspace-tree flex-1 min-h-0 overflow-y-auto" role="tree"></div>
                    </div>
                </section>
            `;
            document.body.appendChild(overlay);
            syncInteractionLocks();

            const queryInput = overlay.querySelector('[data-vault-path-picker-query]');
            const scopeSelect = overlay.querySelector('[data-vault-path-picker-scope]');
            const headerCreateInput = overlay.querySelector('.vault-explorer-header-create-input');
            const uploadInput = overlay.querySelector('[data-vault-explorer-upload-input]');
            if (scopeSelect instanceof HTMLSelectElement) {
                scopeSelect.value = options.initialScope || (workspacePath() ? 'workspace' : 'vault');
            }
            headerCreateInput?.addEventListener('input', () => {
                headerCreateInput.setCustomValidity('');
            });

            function syncSearchPlaceholder() {
                if (!(queryInput instanceof HTMLInputElement) || options.searchPlaceholder) return;
                queryInput.placeholder = scopeSelect?.value === 'vault'
                    ? 'Search entire vault...'
                    : 'Search workspace...';
            }
            syncSearchPlaceholder();

            overlay.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (!target.closest('.vault-explorer-header-new')) {
                    overlay.querySelector('[data-vault-explorer-new-menu]')?.classList.add('hidden');
                }
                if (event.target === overlay || target.closest('[data-vault-path-picker-close]')) {
                    if (uploadInProgress) return;
                    close();
                    return;
                }
                if (target.closest('[data-vault-explorer-header-create-cancel]')) {
                    closeHeaderCreateForm(overlay);
                    return;
                }
                if (target.closest('[data-vault-explorer-new]')) {
                    toggleHeaderCreateMenu(overlay);
                    return;
                }
                if (target.closest('[data-vault-explorer-upload]')) {
                    if (!isReadOnly(options) && uploadInput instanceof HTMLInputElement) {
                        uploadInput.click();
                    }
                    return;
                }
                const createKindButton = target.closest('[data-vault-explorer-create-kind]');
                if (createKindButton instanceof HTMLButtonElement) {
                    if (isReadOnly(options)) return;
                    showHeaderCreateForm(
                        overlay,
                        createKindButton.dataset.vaultExplorerCreateKind || 'file'
                    );
                    return;
                }
                if (target.closest('[data-vault-explorer-refresh]')) {
                    try {
                        await refreshExplorer(overlay, options);
                    } catch (error) {
                        setStatus(overlay, `Unable to refresh paths: ${error.message}`, true);
                    }
                    return;
                }
                const loadMoreButton = target.closest('[data-vault-path-picker-more]');
                if (loadMoreButton instanceof HTMLButtonElement) {
                    await loadMoreResults(loadMoreButton, options);
                    return;
                }
                if (target.closest('[data-vault-explorer-action-cancel]')) {
                    if (uploadInProgress) return;
                    closeActionPanel(overlay);
                    return;
                }
                const copyButton = target.closest('[data-vault-explorer-copy]');
                if (copyButton instanceof HTMLButtonElement) {
                    const path = copyButton.getAttribute('data-vault-explorer-copy') || '';
                    flashCopyFeedback(copyButton, await handleCopy(path));
                    return;
                }
                const moreButton = target.closest('[data-vault-explorer-more]');
                if (moreButton instanceof HTMLButtonElement) {
                    toggleRowMenu(overlay, moreButton);
                    return;
                }
                const rowAction = target.closest('[data-vault-explorer-row-action]');
                if (rowAction instanceof HTMLButtonElement) {
                    if (isReadOnly(options)) return;
                    await handleRowAction(overlay, rowAction, options);
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
                    if (moveForm(overlay)) {
                        if (kind === 'directory') selectMoveDestination(overlay, path);
                        return;
                    }
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
            overlay.addEventListener('submit', async (event) => {
                const form = event.target;
                if (form instanceof HTMLFormElement && form.matches('[data-vault-explorer-header-create]')) {
                    event.preventDefault();
                    await submitExplorerMutation(overlay, form, options);
                    return;
                }
                if (form instanceof HTMLFormElement && form.matches('[data-vault-explorer-upload-form]')) {
                    event.preventDefault();
                    await submitUploads(overlay, form, options);
                    return;
                }
                if (!(form instanceof HTMLFormElement) || !form.matches('[data-vault-explorer-mutation-form]')) return;
                event.preventDefault();
                await submitExplorerMutation(overlay, form, options);
            });
            overlay.addEventListener('input', (event) => {
                const input = event.target;
                if (
                    input instanceof HTMLInputElement
                    && input.matches('[data-vault-explorer-move-name]')
                ) {
                    input.setCustomValidity('');
                    updateMovePreview(overlay);
                }
            });

            const loadRoot = () => loadResults(overlay, options).catch((error) => {
                if (error.name !== 'AbortError') {
                    setStatus(overlay, `Unable to load paths: ${error.message}`, true);
                }
            });
            const debouncedLoad = debounce(loadRoot, 180);
            queryInput?.addEventListener('input', debouncedLoad);
            uploadInput?.addEventListener('change', () => {
                activeUploadFiles = Array.from(uploadInput.files || []);
                uploadInput.value = '';
                if (activeUploadFiles.length) showUploadForm(overlay);
            });
            scopeSelect?.addEventListener('change', () => {
                closeHeaderCreateForm(overlay);
                syncSearchPlaceholder();
                loadRoot();
            });
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
            rootAbortController?.abort();
            rootAbortController = null;
            rootLoadGeneration += 1;
            if (activePickerId) {
                document.getElementById(activePickerId)?.remove();
            }
            document.getElementById('vault-path-picker-modal')?.remove();
            activeOnClose?.();
            activePickerId = '';
            activeOnClose = null;
            activeOptions = null;
            activeUploadFiles = [];
            uploadInProgress = false;
        }

        function syncInteractionLocks() {
            if (!activePickerId || !activeOptions) return;
            const overlay = document.getElementById(activePickerId);
            if (!(overlay instanceof HTMLElement)) return;
            const readOnly = isReadOnly(activeOptions);
            const lockMessage = 'Available when the active response finishes.';
            overlay.querySelectorAll('[data-vault-explorer-more]').forEach((button) => {
                if (!(button instanceof HTMLButtonElement)) return;
                button.disabled = readOnly;
                button.title = readOnly ? lockMessage : 'More actions';
            });
            overlay.querySelectorAll('[data-vault-explorer-mutation-form] button[type="submit"]').forEach((button) => {
                if (button instanceof HTMLButtonElement) button.disabled = readOnly;
            });
            const newButton = overlay.querySelector('[data-vault-explorer-new]');
            if (newButton instanceof HTMLButtonElement) {
                newButton.disabled = readOnly;
                newButton.title = readOnly ? lockMessage : 'Create file or folder';
            }
            const uploadButton = overlay.querySelector('[data-vault-explorer-upload]');
            if (uploadButton instanceof HTMLButtonElement) {
                uploadButton.disabled = readOnly;
                uploadButton.title = readOnly ? lockMessage : 'Upload files';
            }
            if (readOnly) {
                closeActionPanel(overlay);
                closeHeaderCreateForm(overlay);
            }
        }

        async function loadResults(overlay, options, path = '') {
            const generation = ++rootLoadGeneration;
            rootAbortController?.abort();
            const controller = new AbortController();
            rootAbortController = controller;
            const mode = options.mode === 'directories' ? 'directories' : 'files';
            setStatus(overlay, 'Loading...');
            const results = overlay.querySelector('[data-vault-path-picker-results]');
            if (!(results instanceof HTMLElement)) return;
            results.innerHTML = '';
            if (mode === 'directories') {
                const payload = await fetchDirectories(path, controller.signal, options);
                if (generation !== rootLoadGeneration || !overlay.isConnected) return;
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
                signal: controller.signal,
                options,
            });
            if (generation !== rootLoadGeneration || !overlay.isConnected) return;
            const items = Array.isArray(payload.items) ? payload.items : [];
            setStatus(overlay, renderFileStatus(payload, items.length));
            results.innerHTML = items.length
                ? items.map((item) => renderRow(item, 0, options)).join('') + renderLoadMore(payload, 0, options)
                : `<p class="text-sm text-txt-secondary">${escapeHtml(options.emptyText || 'No matching files.')}</p>`;
        }

        async function fetchDirectories(path, signal = undefined, options = {}) {
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            const suffix = params.toString() ? `?${params.toString()}` : '';
            const vault = options.vaultName || selectedVault();
            const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/directories${suffix}`, { signal });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        async function fetchFileRefs({ path = '', query = '', scope = 'workspace', offset = 0, signal = undefined, options = {} } = {}) {
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            if (scope === 'workspace' && workspacePath()) {
                params.set('workspace_path', workspacePath());
            }
            if (query) params.set('query', query);
            if (offset) params.set('offset', String(offset));
            params.set('scope', scope || 'workspace');
            const vault = options.vaultName || selectedVault();
            const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/file-refs?${params.toString()}`, { signal });
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
                    const payload = await fetchDirectories(path, undefined, options);
                    const items = Array.isArray(payload.directories)
                        ? payload.directories.map((item) => ({ ...item, kind: 'directory' }))
                        : [];
                    children.innerHTML = items.length
                        ? items.map((item) => renderRow(item, depth, options)).join('')
                        : '<div class="py-1 text-xs text-txt-secondary">No child folders.</div>';
                } else {
                    const payload = await fetchFileRefs({ path, scope: 'vault', options });
                    const items = Array.isArray(payload.items) ? payload.items : [];
                    children.innerHTML = items.length
                        ? items.map((item) => renderRow(item, depth, options)).join('') + renderLoadMore(payload, depth, options)
                        : '<div class="py-1 text-xs text-txt-secondary">No child files.</div>';
                }
                children.dataset.loaded = 'true';
                syncMoveDestinationSelection(overlay);
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
            const readOnly = options.explorer && isReadOnly(options);
            const moreTitle = readOnly ? 'Available when the active response finishes.' : 'More actions';
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
                        ${options.explorer ? `
                            <div class="vault-explorer-row-actions">
                                <button type="button" class="ui-icon-button is-compact" data-vault-explorer-copy="${escapeHtml(path)}" aria-label="Copy path" title="Copy path">${icons.COPY_ICON_SVG}</button>
                                <button type="button" class="ui-icon-button is-compact" data-vault-explorer-more="${escapeHtml(path)}" aria-label="More actions" title="${moreTitle}" ${readOnly ? 'disabled' : ''}>${icons.MORE_HORIZONTAL_ICON_SVG}</button>
                                <div class="vault-explorer-row-menu hidden" data-vault-explorer-row-menu>
                                    <button type="button" data-vault-explorer-row-action="reference" data-path="${escapeHtml(path)}" data-kind="${kind}">Add to prompt</button>
                                    ${kind === 'directory' ? `<button type="button" data-vault-explorer-row-action="workspace" data-path="${escapeHtml(path)}" data-kind="${kind}">Set as workspace</button>` : ''}
                                    ${kind === 'directory' ? `<button type="button" data-vault-explorer-row-action="create_file" data-path="${escapeHtml(path)}" data-kind="${kind}">Create file</button>` : ''}
                                    ${kind === 'directory' ? `<button type="button" data-vault-explorer-row-action="create_directory" data-path="${escapeHtml(path)}" data-kind="${kind}">Create folder</button>` : ''}
                                    <button type="button" data-vault-explorer-row-action="rename" data-path="${escapeHtml(path)}" data-kind="${kind}">Rename</button>
                                    <button type="button" data-vault-explorer-row-action="move" data-path="${escapeHtml(path)}" data-kind="${kind}">Move</button>
                                    <button type="button" class="state-error" data-vault-explorer-row-action="delete" data-path="${escapeHtml(path)}" data-kind="${kind}">Delete</button>
                                </div>
                            </div>
                        ` : ''}
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
            const suffix = payload?.truncated && payload?.next_offset == null
                ? ' Refine the search to see more.'
                : '';
            return `${base} item${count === 1 ? '' : 's'} in ${scope}: ${root}.${suffix}`;
        }

        function renderLoadMore(payload, depth, options) {
            if (!Number.isInteger(payload?.next_offset)) return '';
            return `
                <button type="button" class="vault-path-picker-more" data-vault-path-picker-more
                    data-path="${escapeHtml(payload.path || '')}"
                    data-offset="${payload.next_offset}"
                    data-depth="${depth}">Load more</button>
            `;
        }

        async function loadMoreResults(button, options) {
            button.disabled = true;
            const path = button.dataset.path || '';
            const offset = Number.parseInt(button.dataset.offset || '0', 10);
            const depth = Number.parseInt(button.dataset.depth || '0', 10);
            try {
                const payload = await fetchFileRefs({ path, scope: 'vault', offset, options });
                const items = Array.isArray(payload.items) ? payload.items : [];
                button.insertAdjacentHTML(
                    'beforebegin',
                    items.map((item) => renderRow(item, depth, options)).join('')
                    + renderLoadMore(payload, depth, options)
                );
                button.remove();
            } catch (error) {
                button.disabled = false;
                button.textContent = `Retry: ${error.message}`;
            }
        }

        function setStatus(overlay, message, error = false) {
            const status = overlay.querySelector('[data-vault-path-picker-status]');
            if (!status) return;
            status.innerHTML = error ? `<span class="state-error">${escapeHtml(message)}</span>` : escapeHtml(message);
        }

        function actionPanel(overlay) {
            return overlay.querySelector('[data-vault-explorer-action-panel]');
        }

        function closeActionPanel(overlay, { restoreFocus = true } = {}) {
            const panel = actionPanel(overlay);
            if (!(panel instanceof HTMLElement)) return;
            const wasUpload = Boolean(
                panel.querySelector('[data-vault-explorer-upload-form]')
            );
            const sourcePath = panel.querySelector(
                '[data-vault-explorer-mutation-form]'
            )?.getAttribute('data-path') || '';
            panel.classList.add('hidden');
            panel.innerHTML = '';
            overlay.classList.remove('vault-explorer-choosing-destination');
            overlay.classList.remove('vault-explorer-preparing-upload');
            syncMoveDestinationSelection(overlay);
            if (wasUpload) activeUploadFiles = [];
            if (restoreFocus && sourcePath) {
                const sourceMenuButton = Array.from(
                    overlay.querySelectorAll('[data-vault-explorer-more]')
                ).find((button) => (
                    button.getAttribute('data-vault-explorer-more') === sourcePath
                ));
                sourceMenuButton?.focus();
            } else if (restoreFocus && wasUpload) {
                overlay.querySelector('[data-vault-explorer-upload]')?.focus();
            }
        }

        function showUploadForm(overlay) {
            const panel = actionPanel(overlay);
            if (!(panel instanceof HTMLElement) || !activeUploadFiles.length) return;
            const selectedFiles = activeUploadFiles;
            closeActionPanel(overlay, { restoreFocus: false });
            activeUploadFiles = selectedFiles;
            closeHeaderCreateForm(overlay);
            const scope = overlay.querySelector('[data-vault-path-picker-scope]');
            const initialDestination = scope instanceof HTMLSelectElement
                && scope.value === 'workspace'
                ? workspacePath()
                : '';
            panel.innerHTML = `
                <div class="vault-explorer-action-header">
                    <strong>Upload files</strong>
                    <button type="button" class="ui-icon-button is-compact" data-vault-explorer-action-cancel aria-label="Cancel" title="Cancel">${icons.X_ICON_SVG}</button>
                </div>
                <form class="vault-explorer-upload-form" data-vault-explorer-upload-form>
                    <label>Destination folder
                        <input name="destination" value="${escapeHtml(initialDestination)}" class="vault-explorer-path-input" autocomplete="off" placeholder="Vault root" />
                    </label>
                    <div class="vault-explorer-upload-list" data-vault-explorer-upload-list></div>
                    <p class="text-xs text-txt-secondary">To convert PDFs or images to Markdown, upload them to <span class="cell-mono">AssistantMD/Import</span>, then use Import Files.</p>
                    <div class="vault-explorer-form-actions">
                        <button type="button" class="ui-button-secondary" data-vault-explorer-action-cancel>Cancel</button>
                        <button type="submit" class="ui-button-primary">Upload</button>
                    </div>
                    <div class="text-sm" data-vault-explorer-form-status></div>
                </form>`;
            panel.classList.remove('hidden');
            overlay.classList.add('vault-explorer-preparing-upload');
            const destinationInput = panel.querySelector('input[name="destination"]');
            destinationInput?.addEventListener('input', () => {
                destinationInput.setCustomValidity('');
                renderUploadPaths(panel);
            });
            renderUploadPaths(panel);
            destinationInput?.focus();
            if (destinationInput instanceof HTMLInputElement) {
                destinationInput.setSelectionRange(
                    destinationInput.value.length,
                    destinationInput.value.length
                );
            }
        }

        function renderUploadPaths(panel) {
            const list = panel.querySelector('[data-vault-explorer-upload-list]');
            const destinationInput = panel.querySelector('input[name="destination"]');
            if (!(list instanceof HTMLElement)) return;
            const destination = destinationInput instanceof HTMLInputElement
                ? destinationInput.value.trim().replace(/\/+$/, '')
                : '';
            list.innerHTML = activeUploadFiles.map((file) => `
                <div class="vault-explorer-upload-item">
                    <span title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
                    <span class="cell-mono text-txt-secondary">${escapeHtml(joinPath(destination, file.name))}</span>
                    <span class="text-txt-secondary">${formatFileSize(file.size)}</span>
                </div>
            `).join('');
        }

        async function submitUploads(overlay, form, options) {
            if (isReadOnly(options) || !activeUploadFiles.length) return;
            const destinationInput = form.elements.namedItem('destination');
            const destination = destinationInput instanceof HTMLInputElement
                ? destinationInput.value.trim().replace(/\/+$/, '')
                : '';
            const invalidDestination = destination.startsWith('/')
                || destination.includes('\\')
                || destination.split('/').includes('..');
            if (invalidDestination) {
                const message = 'Enter a vault-relative destination folder.';
                if (destinationInput instanceof HTMLInputElement) {
                    destinationInput.setCustomValidity(message);
                    destinationInput.reportValidity();
                }
                return;
            }

            const submit = form.querySelector('button[type="submit"]');
            const status = form.querySelector('[data-vault-explorer-form-status]');
            setUploadInteractionState(overlay, form, true);
            const failures = [];
            const uploadedPaths = [];
            uploadInProgress = true;
            try {
                for (const file of activeUploadFiles) {
                    const path = joinPath(destination, file.name);
                    if (status) status.textContent = `Uploading ${file.name}...`;
                    try {
                        if (typeof options.onUpload !== 'function') {
                            throw new Error('File uploads are unavailable.');
                        }
                        const result = await options.onUpload(file, path);
                        uploadedPaths.push(result?.path || path);
                    } catch (error) {
                        failures.push({ file, message: error.message });
                    }
                }
            } finally {
                uploadInProgress = false;
                setUploadInteractionState(overlay, form, false);
            }

            if (uploadedPaths.length) {
                try {
                    await refreshExplorer(overlay, options, uploadedPaths[0]);
                } catch (refreshError) {
                    setStatus(
                        overlay,
                        `Upload succeeded, but the Explorer could not refresh: ${refreshError.message}`,
                        true
                    );
                }
            }
            if (!failures.length) {
                closeActionPanel(overlay, { restoreFocus: false });
                return;
            }

            activeUploadFiles = failures.map(({ file }) => file);
            renderUploadPaths(form);
            if (status) {
                status.innerHTML = failures.map(({ file, message }) => (
                    `<div class="state-error">${escapeHtml(file.name)}: ${escapeHtml(message)}</div>`
                )).join('');
            }
            if (submit instanceof HTMLButtonElement) submit.disabled = false;
        }

        function setUploadInteractionState(overlay, form, busy) {
            form.querySelectorAll('button, input').forEach((control) => {
                if (
                    control instanceof HTMLButtonElement
                    || control instanceof HTMLInputElement
                ) {
                    control.disabled = busy;
                }
            });
            const closeButton = overlay.querySelector('[data-vault-path-picker-close]');
            if (closeButton instanceof HTMLButtonElement) closeButton.disabled = busy;
            overlay.querySelectorAll(
                '[data-vault-explorer-upload], [data-vault-explorer-refresh]'
            ).forEach((control) => {
                if (control instanceof HTMLButtonElement) control.disabled = busy;
            });
            if (!busy) syncInteractionLocks();
        }

        function formatFileSize(bytes) {
            if (bytes < 1024) return `${bytes} B`;
            if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
            return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        }

        function toggleHeaderCreateMenu(overlay) {
            const menu = overlay.querySelector('[data-vault-explorer-new-menu]');
            if (!(menu instanceof HTMLElement)) return;
            closeHeaderCreateForm(overlay);
            menu.classList.toggle('hidden');
        }

        function closeHeaderCreateForm(overlay) {
            const form = overlay.querySelector('[data-vault-explorer-header-create]');
            const menu = overlay.querySelector('[data-vault-explorer-new-menu]');
            form?.classList.add('hidden');
            menu?.classList.add('hidden');
            if (form instanceof HTMLFormElement) {
                form.dataset.operation = '';
                form.querySelector('input')?.setCustomValidity('');
            }
        }

        function showHeaderCreateForm(overlay, kind) {
            const form = overlay.querySelector('[data-vault-explorer-header-create]');
            const input = form?.querySelector('input');
            const label = form?.querySelector('[data-vault-explorer-header-create-label]');
            if (!(form instanceof HTMLFormElement) || !(input instanceof HTMLInputElement)) return;

            const scope = overlay.querySelector('[data-vault-path-picker-scope]');
            const parent = scope instanceof HTMLSelectElement
                && scope.value === 'workspace'
                ? workspacePath()
                : '';
            const normalizedKind = kind === 'directory' ? 'directory' : 'file';
            const labelText = normalizedKind === 'directory' ? 'New folder path' : 'New file path';
            form.dataset.operation = normalizedKind === 'directory'
                ? 'create_directory'
                : 'create_file';
            input.value = parent ? `${parent}/` : '';
            input.placeholder = normalizedKind === 'directory'
                ? 'Folder/path'
                : 'Folder/file.md';
            input.setAttribute('aria-label', labelText);
            if (label instanceof HTMLElement) label.textContent = labelText;
            form.classList.remove('hidden');
            overlay.querySelector('[data-vault-explorer-new-menu]')?.classList.add('hidden');
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }

        function showCreateForm(overlay, kind, parent) {
            showMutationForm(overlay, {
                operation: kind === 'directory' ? 'create_directory' : 'create_file',
                title: kind === 'directory' ? 'Create folder' : 'Create file',
                label: kind === 'directory' ? 'Folder name' : 'File name',
                value: '',
                submitLabel: 'Create',
                parent,
            });
        }

        function showMutationForm(overlay, { operation, title, label = '', value = '', submitLabel, path = '', kind = '', parent = '' }) {
            const panel = actionPanel(overlay);
            if (!(panel instanceof HTMLElement)) return;
            const isDelete = operation === 'delete';
            panel.innerHTML = `
                <div class="vault-explorer-action-header">
                    <strong>${escapeHtml(title)}</strong>
                    <button type="button" class="ui-icon-button is-compact" data-vault-explorer-action-cancel aria-label="Cancel" title="Cancel">${icons.X_ICON_SVG}</button>
                </div>
                <form class="vault-explorer-mutation-form" data-vault-explorer-mutation-form data-operation="${operation}" data-path="${escapeHtml(path)}" data-kind="${escapeHtml(kind)}" data-parent="${escapeHtml(parent)}">
                    ${isDelete ? `<p>Delete <span class="cell-mono">${escapeHtml(path)}</span>?</p>` : `<label>${escapeHtml(label)}<input name="value" value="${escapeHtml(value)}" class="vault-explorer-path-input" autocomplete="off" required /></label>`}
                    <div class="vault-explorer-form-actions">
                        <button type="button" class="ui-button-secondary" data-vault-explorer-action-cancel>Cancel</button>
                        <button type="submit" class="${isDelete ? 'ui-button-danger' : 'ui-button-primary'}">${escapeHtml(submitLabel)}</button>
                    </div>
                    <div class="text-sm" data-vault-explorer-form-status></div>
                </form>`;
            panel.classList.remove('hidden');
            const input = panel.querySelector('input');
            input?.focus();
            if (
                operation === 'rename'
                && input instanceof HTMLInputElement
            ) {
                const extensionIndex = kind === 'file' ? value.lastIndexOf('.') : -1;
                input.setSelectionRange(
                    0,
                    extensionIndex > 0 ? extensionIndex : value.length
                );
            }
        }

        function showMoveForm(overlay, { path, kind }) {
            const panel = actionPanel(overlay);
            if (!(panel instanceof HTMLElement)) return;
            const initialParent = parentPath(path);
            const name = baseName(path);
            const workspace = workspacePath();
            panel.innerHTML = `
                <div class="vault-explorer-action-header">
                    <strong>Move ${escapeHtml(kind)}</strong>
                    <button type="button" class="ui-icon-button is-compact" data-vault-explorer-action-cancel aria-label="Cancel" title="Cancel">${icons.X_ICON_SVG}</button>
                </div>
                <form class="vault-explorer-mutation-form vault-explorer-move-form" data-vault-explorer-mutation-form data-operation="move" data-path="${escapeHtml(path)}" data-kind="${escapeHtml(kind)}" data-destination="${escapeHtml(initialParent)}">
                    <p class="text-txt-secondary">Choose a destination folder in the tree.</p>
                    <div class="vault-explorer-move-destination">
                        <span>Destination</span>
                        <strong class="cell-mono" data-vault-explorer-move-destination>${escapeHtml(initialParent || 'Vault root')}</strong>
                        ${workspace ? `<button type="button" class="ui-button-secondary" data-vault-explorer-move-shortcut="${escapeHtml(workspace)}">Workspace root</button>` : ''}
                        <button type="button" class="ui-button-secondary" data-vault-explorer-move-shortcut="">Vault root</button>
                    </div>
                    <label>${kind === 'directory' ? 'Folder name' : 'File name'}
                        <input name="value" value="${escapeHtml(name)}" class="vault-explorer-path-input" data-vault-explorer-move-name autocomplete="off" required />
                    </label>
                    <div class="vault-explorer-move-preview">
                        <span class="text-txt-secondary">New path</span>
                        <span class="cell-mono text-txt-primary" data-vault-explorer-move-preview></span>
                    </div>
                    <div class="vault-explorer-form-actions">
                        <button type="button" class="ui-button-secondary" data-vault-explorer-action-cancel>Cancel</button>
                        <button type="submit" class="ui-button-primary">Move</button>
                    </div>
                    <div class="text-sm" data-vault-explorer-form-status></div>
                </form>`;
            panel.classList.remove('hidden');
            overlay.classList.add('vault-explorer-choosing-destination');
            panel.querySelectorAll('[data-vault-explorer-move-shortcut]').forEach((button) => {
                button.addEventListener('click', () => {
                    selectMoveDestination(
                        overlay,
                        button.getAttribute('data-vault-explorer-move-shortcut') || ''
                    );
                });
            });
            updateMovePreview(overlay);
            syncMoveDestinationSelection(overlay);
        }

        function toggleRowMenu(overlay, button) {
            const menu = button.parentElement?.querySelector('[data-vault-explorer-row-menu]');
            overlay.querySelectorAll('[data-vault-explorer-row-menu]').forEach((candidate) => {
                if (candidate !== menu) candidate.classList.add('hidden');
            });
            menu?.classList.toggle('hidden');
        }

        async function handleRowAction(overlay, button, options) {
            const action = button.dataset.vaultExplorerRowAction || '';
            const path = button.dataset.path || '';
            const kind = button.dataset.kind || '';
            button.closest('[data-vault-explorer-row-menu]')?.classList.add('hidden');
            if (action === 'reference') return options.onAddReference?.(path);
            if (action === 'workspace') return options.onSetWorkspace?.(path);
            if (action === 'create_file') return showCreateForm(overlay, 'file', path);
            if (action === 'create_directory') return showCreateForm(overlay, 'directory', path);
            if (action === 'rename') {
                showMutationForm(overlay, {
                    operation: 'rename',
                    title: `Rename ${kind}`,
                    label: 'New name',
                    value: baseName(path),
                    submitLabel: 'Rename',
                    path,
                    kind,
                });
            } else if (action === 'move') {
                showMoveForm(overlay, { path, kind });
            } else if (action === 'delete') {
                showMutationForm(overlay, { operation: 'delete', title: `Delete ${kind}`, submitLabel: 'Delete', path, kind });
            }
        }

        async function submitExplorerMutation(overlay, form, options) {
            const operation = form.dataset.operation || '';
            const directPath = form.dataset.directPath === 'true';
            const sourcePath = form.dataset.path || '';
            const parent = form.dataset.parent || '';
            const valueInput = form.elements.namedItem('value');
            const value = valueInput instanceof HTMLInputElement ? valueInput.value.trim() : '';
            const status = form.querySelector('[data-vault-explorer-form-status]');
            const submit = form.querySelector('button[type="submit"]');
            if (isReadOnly(options)) {
                if (status) status.innerHTML = '<span class="state-error">Wait for the active response to finish.</span>';
                return;
            }
            if (submit instanceof HTMLButtonElement) submit.disabled = true;
            const invalidCreateValue = operation.startsWith('create_') && (
                !value
                || value === '.'
                || value === '..'
                || (!directPath && /[\\/]/.test(value))
            );
            const invalidLocalName = ['rename', 'move'].includes(operation) && (
                !value
                || value === '.'
                || value === '..'
                || /[\\/]/.test(value)
            );
            if (invalidCreateValue || invalidLocalName) {
                const message = directPath
                    ? 'Enter a vault-relative path.'
                    : 'Enter a name without path separators.';
                if (valueInput instanceof HTMLInputElement) {
                    valueInput.setCustomValidity(message);
                    valueInput.reportValidity();
                }
                if (status) status.innerHTML = `<span class="state-error">${escapeHtml(message)}</span>`;
                if (submit instanceof HTMLButtonElement) submit.disabled = false;
                return;
            }
            if (
                operation === 'rename'
                && joinPath(parentPath(sourcePath), value) === sourcePath
            ) {
                const message = 'Enter a different name.';
                if (valueInput instanceof HTMLInputElement) {
                    valueInput.setCustomValidity(message);
                    valueInput.reportValidity();
                }
                if (status) {
                    status.innerHTML = `<span class="state-error">${escapeHtml(message)}</span>`;
                }
                if (submit instanceof HTMLButtonElement) submit.disabled = false;
                return;
            }
            if (valueInput instanceof HTMLInputElement) valueInput.setCustomValidity('');
            if (status) status.textContent = 'Working...';
            try {
                const destination = operation === 'rename'
                    ? joinPath(parentPath(sourcePath), value)
                    : operation === 'move'
                        ? joinPath(form.dataset.destination || '', value)
                        : '';
                const targetPath = operation.startsWith('create_')
                    ? (directPath ? value : [parent, value].filter(Boolean).join('/'))
                    : sourcePath;
                const payload = {
                    operation: operation === 'rename' ? 'move' : operation,
                    path: targetPath,
                };
                if (['rename', 'move'].includes(operation)) payload.destination = destination;
                const result = await options.onMutate?.(payload);
                closeActionPanel(overlay, { restoreFocus: false });
                closeHeaderCreateForm(overlay);
                const reveal = ['rename', 'move'].includes(operation)
                    ? destination
                    : (operation.startsWith('create_') ? targetPath : parentPath(sourcePath));
                try {
                    await refreshExplorer(overlay, options, reveal);
                } catch (refreshError) {
                    setStatus(
                        overlay,
                        `The change succeeded, but the Explorer could not refresh: ${refreshError.message}`,
                        true
                    );
                }
                if (operation === 'create_file') options.onOpenFile?.(result?.path || targetPath);
            } catch (error) {
                if (directPath) setStatus(overlay, error.message, true);
                if (status) status.innerHTML = `<span class="state-error">${escapeHtml(error.message)}</span>`;
                if (submit instanceof HTMLButtonElement) submit.disabled = false;
            }
        }

        async function refreshExplorer(overlay, options, reveal = '') {
            const query = overlay.querySelector('[data-vault-path-picker-query]');
            const scope = overlay.querySelector('[data-vault-path-picker-scope]');
            if (query instanceof HTMLInputElement) query.value = '';
            if (scope instanceof HTMLSelectElement) scope.value = 'vault';
            await loadResults(overlay, options);
            if (reveal) await revealPath(overlay, options, reveal);
        }

        function parentPath(path) {
            const parts = String(path || '').split('/').filter(Boolean);
            parts.pop();
            return parts.join('/');
        }

        function baseName(path) {
            return String(path || '').split('/').filter(Boolean).pop() || '';
        }

        function joinPath(parent, name) {
            return [parent, name].filter(Boolean).join('/');
        }

        function moveForm(overlay) {
            const form = overlay.querySelector(
                '[data-vault-explorer-mutation-form][data-operation="move"]'
            );
            return form instanceof HTMLFormElement ? form : null;
        }

        function selectMoveDestination(overlay, destination) {
            const form = moveForm(overlay);
            if (!form) return;
            const source = form.dataset.path || '';
            const kind = form.dataset.kind || '';
            const status = form.querySelector('[data-vault-explorer-form-status]');
            if (
                kind === 'directory'
                && (destination === source || destination.startsWith(`${source}/`))
            ) {
                if (status) {
                    status.innerHTML = '<span class="state-error">A folder cannot be moved into itself.</span>';
                }
                return;
            }
            form.dataset.destination = destination;
            if (status) status.textContent = '';
            updateMovePreview(overlay);
            syncMoveDestinationSelection(overlay);
        }

        function updateMovePreview(overlay) {
            const form = moveForm(overlay);
            if (!form) return;
            const destination = form.dataset.destination || '';
            const nameInput = form.querySelector('[data-vault-explorer-move-name]');
            const name = nameInput instanceof HTMLInputElement ? nameInput.value.trim() : '';
            const destinationLabel = form.querySelector('[data-vault-explorer-move-destination]');
            const preview = form.querySelector('[data-vault-explorer-move-preview]');
            const submit = form.querySelector('button[type="submit"]');
            const newPath = joinPath(destination, name);
            if (destinationLabel) destinationLabel.textContent = destination || 'Vault root';
            if (preview) preview.textContent = newPath || 'Choose a name';
            if (submit instanceof HTMLButtonElement) {
                submit.disabled = !name || newPath === (form.dataset.path || '');
            }
        }

        function syncMoveDestinationSelection(overlay) {
            const form = moveForm(overlay);
            const destination = form?.dataset.destination;
            overlay.querySelectorAll('[data-vault-path-picker-row]').forEach((row) => {
                if (!(row instanceof HTMLElement)) return;
                const rowPath = row.getAttribute('data-vault-path-picker-row') || '';
                const rowButton = row.querySelector(
                    ':scope > .workspace-tree-row [data-vault-path-picker-select]'
                );
                const selected = destination !== undefined && rowPath === destination;
                rowButton?.classList.toggle(
                    'is-move-destination',
                    selected
                );
                rowButton?.setAttribute('aria-selected', selected ? 'true' : 'false');
            });
        }

        function debounce(fn, delayMs) {
            let timer = null;
            return (...args) => {
                if (timer) window.clearTimeout(timer);
                timer = window.setTimeout(() => fn(...args), delayMs);
            };
        }

        return Object.freeze({ open, close, syncInteractionLocks });
    }

    window.VaultPathPicker = Object.freeze({
        create: createVaultPathPickerController,
    });
})(window, document);
