(function fileReferencesModule(window, document) {
    function createFileReferencesController({ state, elements, icons, utils, callbacks }) {
        const { escapeHtml } = utils;
        let pickerOpen = false;

        function selectedVault() {
            return elements.vaultSelector?.value || '';
        }

        function workspacePath() {
            return (elements.workspacePathInput?.value || '').trim();
        }

        function insertReference(path) {
            const input = elements.chatInput;
            if (!(input instanceof HTMLTextAreaElement) || !path) return;

            const token = `@${path}`;
            const start = input.selectionStart ?? input.value.length;
            const end = input.selectionEnd ?? start;
            const before = input.value.slice(0, start);
            const after = input.value.slice(end);
            const prefix = before && !/\s$/.test(before) ? ' ' : '';
            const suffix = after && !/^\s/.test(after) ? ' ' : '';
            input.value = `${before}${prefix}${token}${suffix}${after}`;
            const cursor = before.length + prefix.length + token.length + suffix.length;
            input.focus();
            input.setSelectionRange(cursor, cursor);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }

        function openPicker() {
            const vault = selectedVault();
            if (!vault) {
                alert('Select a vault before adding file references.');
                return;
            }
            closePicker();
            pickerOpen = true;

            const overlay = document.createElement('div');
            overlay.id = 'file-reference-picker-modal';
            overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
            overlay.innerHTML = `
                <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="file-reference-picker-title">
                    <div class="app-modal-header flex-none">
                        <div class="app-modal-title-block">
                            <h2 id="file-reference-picker-title" class="text-lg font-semibold text-txt-primary">Add File Reference</h2>
                            <p class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(vault)}</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-compact" data-file-ref-close aria-label="Close" title="Close">${icons.X_ICON_SVG}</button>
                        </div>
                    </div>
                    <div class="p-4 flex-1 min-h-0 flex flex-col gap-3">
                        <div class="file-reference-toolbar">
                            <input id="file-reference-query" type="search" class="file-reference-search" placeholder="Search files in workspace or vault..." aria-label="Search files" />
                            <select id="file-reference-scope" class="file-reference-scope" aria-label="Reference search scope">
                                <option value="workspace">Workspace</option>
                                <option value="vault">Vault</option>
                            </select>
                        </div>
                        <div id="file-reference-status" class="text-sm text-txt-secondary">Loading files...</div>
                        <div id="file-reference-results" class="workspace-tree flex-1 min-h-0 overflow-y-auto" role="tree"></div>
                    </div>
                </section>
            `;
            document.body.appendChild(overlay);

            const queryInput = overlay.querySelector('#file-reference-query');
            const scopeSelect = overlay.querySelector('#file-reference-scope');
            if (scopeSelect instanceof HTMLSelectElement && !workspacePath()) {
                scopeSelect.value = 'vault';
            }

            overlay.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (event.target === overlay || target.closest('[data-file-ref-close]')) {
                    closePicker();
                    return;
                }
                const toggle = target.closest('[data-file-ref-toggle]');
                if (toggle instanceof HTMLElement) {
                    await togglePickerNode(overlay, toggle);
                    return;
                }
                const referenceButton = target.closest('[data-file-ref-select]');
                if (referenceButton instanceof HTMLElement) {
                    const path = referenceButton.getAttribute('data-file-ref-select') || '';
                    if (path) {
                        insertReference(path);
                        closePicker();
                    }
                }
            });

            const debouncedLoad = debounce(() => loadPickerResults(overlay), 180);
            queryInput?.addEventListener('input', debouncedLoad);
            scopeSelect?.addEventListener('change', () => loadPickerResults(overlay));
            loadPickerResults(overlay);
        }

        function closePicker() {
            document.getElementById('file-reference-picker-modal')?.remove();
            pickerOpen = false;
        }

        async function loadPickerResults(overlay, path = '') {
            const status = overlay.querySelector('#file-reference-status');
            const results = overlay.querySelector('#file-reference-results');
            const queryInput = overlay.querySelector('#file-reference-query');
            const scopeSelect = overlay.querySelector('#file-reference-scope');
            if (!status || !results) return;
            status.textContent = 'Loading files...';
            results.innerHTML = '';
            try {
                const payload = await fetchReferenceItems({
                    path,
                    query: queryInput instanceof HTMLInputElement ? queryInput.value.trim() : '',
                    scope: scopeSelect instanceof HTMLSelectElement ? scopeSelect.value : 'workspace',
                });
                const items = Array.isArray(payload.items) ? payload.items : [];
                status.textContent = renderPickerStatus(payload, items.length);
                results.innerHTML = items.length
                    ? items.map((item) => renderReferenceRow(item, 0)).join('')
                    : '<p class="text-sm text-txt-secondary">No matching files.</p>';
            } catch (error) {
                status.innerHTML = `<span class="state-error">Unable to load files: ${escapeHtml(error.message)}</span>`;
            }
        }

        async function fetchReferenceItems({ path = '', query = '', scope = 'workspace' } = {}) {
            const vault = selectedVault();
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            if (workspacePath()) params.set('workspace_path', workspacePath());
            if (query) params.set('query', query);
            params.set('scope', scope || 'workspace');
            const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/file-refs?${params.toString()}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        function renderPickerStatus(payload, count) {
            const scope = payload?.scope === 'vault' ? 'vault' : 'workspace';
            const base = payload?.query ? `Found ${count}` : `Showing ${count}`;
            const root = payload?.path || (scope === 'workspace' ? workspacePath() : '') || 'vault root';
            return `${base} item${count === 1 ? '' : 's'} in ${scope}: ${root}`;
        }

        async function togglePickerNode(overlay, toggle) {
            const row = toggle.closest('[data-file-ref-row]');
            if (!(row instanceof HTMLElement)) return;
            const children = row.querySelector(':scope > [data-file-ref-children]');
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
            const path = row.getAttribute('data-file-ref-row') || '';
            children.innerHTML = '<div class="py-1 text-xs text-txt-secondary">Loading...</div>';
            try {
                const payload = await fetchReferenceItems({ path, scope: 'vault' });
                const items = Array.isArray(payload.items) ? payload.items : [];
                children.innerHTML = items.length
                    ? items.map((item) => renderReferenceRow(item, 1)).join('')
                    : '<div class="py-1 text-xs text-txt-secondary">No child files.</div>';
                children.dataset.loaded = 'true';
            } catch (error) {
                children.innerHTML = `<div class="py-1 text-xs state-error">Unable to load files: ${escapeHtml(error.message)}</div>`;
            }
        }

        function renderReferenceRow(item, depth) {
            const path = String(item.path || '');
            const name = String(item.name || path || 'File');
            const kind = item.kind === 'directory' ? 'directory' : 'file';
            const indent = Math.min(Math.max(depth, 0) * 1.25, 5);
            const fileIcon = icons.FILE_TEXT_ICON_SVG || `
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                    <path d="M14 2v4a2 2 0 0 0 2 2h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                </svg>
            `;
            const icon = kind === 'directory' ? icons.FOLDER_ICON_SVG : fileIcon;
            return `
                <div data-file-ref-row="${escapeHtml(path)}">
                    <div class="workspace-tree-row" role="treeitem" style="padding-left: ${indent}rem;">
                        ${kind === 'directory' && item.has_children
                            ? `<button type="button" class="workspace-tree-toggle" data-file-ref-toggle aria-expanded="false" aria-label="Expand ${escapeHtml(name)}">
                                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                                    <path d="M7.25 4.75 12.75 10l-5.5 5.25" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                                </svg>
                            </button>`
                            : '<span class="workspace-tree-spacer" aria-hidden="true"></span>'}
                        <button type="button" class="workspace-tree-select" data-file-ref-select="${escapeHtml(path)}">
                            <span class="file-reference-row-icon" aria-hidden="true">${icon}</span>
                            <span class="workspace-tree-label min-w-0">
                                <span class="workspace-tree-name">${escapeHtml(name)}</span>
                                <span class="file-reference-path">${escapeHtml(path)}</span>
                            </span>
                        </button>
                    </div>
                    <div class="workspace-tree-children hidden" data-file-ref-children></div>
                </div>
            `;
        }

        async function openFile(path) {
            const vault = selectedVault();
            if (!vault || !path) return;
            closeFileModal();
            const overlay = document.createElement('div');
            overlay.id = 'vault-file-modal';
            overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
            overlay.innerHTML = `
                <div class="absolute inset-0" data-vault-file-close="true"></div>
                <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="vault-file-modal-title">
                    <div class="app-modal-header flex-none">
                        <div class="app-modal-title-block">
                            <h2 id="vault-file-modal-title" class="text-lg font-semibold text-txt-primary">${escapeHtml(path.split('/').pop() || path)}</h2>
                            <p id="vault-file-modal-path" class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(path)}</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-primary is-compact" data-vault-file-save="true" aria-label="Save file" title="Save file" disabled>${icons.SAVE_ICON_SVG}</button>
                            <button type="button" class="ui-icon-button is-compact" data-vault-file-close="true" aria-label="Close" title="Close">${icons.X_ICON_SVG}</button>
                        </div>
                    </div>
                    <div class="p-4 space-y-3 flex-1 min-h-0 flex flex-col">
                        <div id="vault-file-modal-status" class="text-sm text-txt-secondary">Loading file...</div>
                        <textarea
                            id="vault-file-modal-editor"
                            class="w-full flex-1 min-h-0 px-3 py-2 border border-border-secondary rounded-md bg-app-bg text-txt-primary font-mono text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                            spellcheck="false"
                            disabled
                        ></textarea>
                    </div>
                </section>
            `;
            document.body.appendChild(overlay);

            const editor = overlay.querySelector('#vault-file-modal-editor');
            const statusLabel = overlay.querySelector('#vault-file-modal-status');
            const saveButton = overlay.querySelector('[data-vault-file-save]');
            let sha256 = '';
            let createIfMissing = false;

            overlay.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (target.closest('[data-vault-file-close="true"]')) {
                    closeFileModal();
                    return;
                }
                if (target.closest('[data-vault-file-save="true"]') && editor instanceof HTMLTextAreaElement) {
                    await saveFile(path, editor, statusLabel, saveButton, () => createIfMissing, (nextHash) => {
                        sha256 = nextHash;
                        createIfMissing = false;
                    }, () => sha256);
                }
            });

            try {
                const data = await fetchVaultFile(path);
                sha256 = data.sha256 || '';
                if (editor instanceof HTMLTextAreaElement) {
                    editor.value = data.content || '';
                    editor.disabled = false;
                }
                if (statusLabel) {
                    statusLabel.textContent = `Editing ${data.path || path}.`;
                }
                if (saveButton instanceof HTMLButtonElement) {
                    saveButton.disabled = false;
                }
            } catch (error) {
                if (error.errorType === 'VaultFileNotFound') {
                    createIfMissing = true;
                    if (editor instanceof HTMLTextAreaElement) {
                        editor.value = '';
                        editor.disabled = false;
                    }
                    if (statusLabel) {
                        statusLabel.textContent = `${path} does not exist yet. Add content and save to create it.`;
                    }
                    if (saveButton instanceof HTMLButtonElement) {
                        saveButton.disabled = false;
                    }
                    return;
                }
                if (statusLabel) {
                    statusLabel.innerHTML = `<span class="state-error">Error: ${escapeHtml(error.message)}</span>`;
                }
            }
        }

        async function fetchVaultFile(path) {
            const vault = selectedVault();
            const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/files?path=${encodeURIComponent(path)}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const error = new Error(errorData.message || `HTTP ${response.status}`);
                error.errorType = errorData.error || errorData.details?.error_type || '';
                throw error;
            }
            return response.json();
        }

        async function saveFile(path, editor, statusLabel, saveButton, shouldCreate, setHash, getHash) {
            if (!(editor instanceof HTMLTextAreaElement)) return;
            if (saveButton instanceof HTMLButtonElement) saveButton.disabled = true;
            const createIfMissing = shouldCreate();
            if (statusLabel) statusLabel.textContent = createIfMissing ? 'Creating...' : 'Saving...';
            try {
                const vault = selectedVault();
                const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/files?path=${encodeURIComponent(path)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: editor.value,
                        expected_sha256: getHash(),
                        create_if_missing: createIfMissing,
                    }),
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                const data = await response.json();
                setHash(data.sha256 || '');
                if (statusLabel) statusLabel.textContent = data.message || 'Saved.';
            } catch (error) {
                if (statusLabel) {
                    statusLabel.innerHTML = `<span class="state-error">Error: ${escapeHtml(error.message)}</span>`;
                }
            } finally {
                if (saveButton instanceof HTMLButtonElement) saveButton.disabled = false;
            }
        }

        function closeFileModal() {
            document.getElementById('vault-file-modal')?.remove();
        }

        function enhanceFileLinks(container) {
            if (!container) return;
            enhanceInlineCodeFileRefs(container);
            const textNodes = [];
            const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
                acceptNode(node) {
                    const parent = node.parentElement;
                    if (!parent || parent.closest('a, button, code, pre, textarea')) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return /[\w .@-]+\/[\w .@/-]+\.(md|markdown|txt)/i.test(node.textContent || '')
                        ? NodeFilter.FILTER_ACCEPT
                        : NodeFilter.FILTER_REJECT;
                },
            });
            while (walker.nextNode()) {
                textNodes.push(walker.currentNode);
            }
            textNodes.forEach(replaceFilePathTextNode);
            container.querySelectorAll('a[href]').forEach((link) => {
                if (!(link instanceof HTMLAnchorElement)) return;
                if (link.dataset.vaultFileEnhanced === 'true') return;
                const path = pathFromLink(link.getAttribute('href') || link.textContent || '');
                if (!path) return;
                link.removeAttribute('target');
                link.removeAttribute('rel');
                link.href = '#';
                link.dataset.vaultFilePath = path;
                link.dataset.vaultFileEnhanced = 'true';
                link.addEventListener('click', (event) => {
                    event.preventDefault();
                    openFile(path);
                });
            });
        }

        function enhanceInlineCodeFileRefs(container) {
            container.querySelectorAll('code').forEach((code) => {
                if (!(code instanceof HTMLElement) || code.closest('pre')) return;
                if (code.dataset.vaultFileEnhanced === 'true') return;
                const path = pathFromLink(code.textContent || '');
                if (!path) return;
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'vault-file-link vault-file-link-code';
                button.textContent = `@${path}`;
                button.dataset.vaultFilePath = path;
                button.addEventListener('click', () => openFile(path));
                code.replaceWith(button);
            });
        }

        function replaceFilePathTextNode(node) {
            const text = node.textContent || '';
            const pattern = /(^|[\s([`])([\w .@-]+\/[\w .@/-]+\.(?:md|markdown|txt))(?=$|[\s).,;:`\]])/gi;
            let match;
            let cursor = 0;
            const fragment = document.createDocumentFragment();
            while ((match = pattern.exec(text)) !== null) {
                const prefix = match[1] || '';
                const rawPath = match[2] || '';
                const path = normalizeDisplayPath(rawPath);
                const start = match.index + prefix.length;
                if (start > cursor) {
                    fragment.appendChild(document.createTextNode(text.slice(cursor, start)));
                }
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'vault-file-link';
                button.textContent = `@${path}`;
                button.addEventListener('click', () => openFile(path));
                fragment.appendChild(button);
                cursor = start + rawPath.length;
            }
            if (cursor === 0) return;
            if (cursor < text.length) {
                fragment.appendChild(document.createTextNode(text.slice(cursor)));
            }
            node.parentNode?.replaceChild(fragment, node);
        }

        function pathFromLink(value) {
            const raw = normalizeDisplayPath(value || '');
            if (!raw || raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('#')) {
                return '';
            }
            if (!/\.(md|markdown|txt)$/i.test(raw) || !raw.includes('/')) {
                return '';
            }
            return raw;
        }

        function normalizeDisplayPath(value) {
            return String(value || '')
                .trim()
                .replace(/^@/, '')
                .replace(/^\.?\//, '')
                .replace(/[),.;:]+$/, '');
        }

        function debounce(fn, delayMs) {
            let timer = null;
            return (...args) => {
                if (timer) window.clearTimeout(timer);
                timer = window.setTimeout(() => fn(...args), delayMs);
            };
        }

        return Object.freeze({
            openPicker,
            closePicker,
            insertReference,
            openFile,
            closeFileModal,
            enhanceFileLinks,
            isPickerOpen: () => pickerOpen,
        });
    }

    window.FileReferences = Object.freeze({
        create: createFileReferencesController,
    });
})(window, document);
