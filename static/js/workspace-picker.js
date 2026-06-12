(function workspacePickerModule(window, document) {
    function createWorkspacePickerController({ state, elements, utils, callbacks }) {
        const { escapeHtml } = utils;
        const icons = window.AssistantMDIcons;

        function syncControls() {
            const input = elements.workspacePathInput;
            if (!input) return;

            const hasSession = Boolean(state.sessionId);
            const hasWorkspace = Boolean(input.value.trim());
            const locked = state.isLoading || (hasSession && hasWorkspace && !state.isWorkspaceUnlocked);

            input.disabled = locked;
            input.title = locked
                ? 'Workspace is locked for this session. Unlock to edit.'
                : '';

            if (elements.workspacePickerBtn) {
                elements.workspacePickerBtn.disabled = state.isLoading || (locked && !state.isWorkspaceUnlocked);
            }
            if (elements.workspaceUnlockBtn) {
                elements.workspaceUnlockBtn.classList.toggle('hidden', !(hasSession && hasWorkspace && locked));
                elements.workspaceUnlockBtn.disabled = state.isLoading;
            }
        }

        function currentPath() {
            return (elements.workspacePathInput?.value || '').trim();
        }

        async function savePath() {
            const input = elements.workspacePathInput;
            const vault = elements.vaultSelector?.value || '';
            const sessionId = state.sessionId || '';
            if (!input || !vault || !sessionId || state.isLoading) return;

            const path = currentPath();
            try {
                const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/workspace`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vault_name: vault, path }),
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                const payload = await response.json().catch(() => null);
                input.value = payload?.path || '';
                state.isWorkspaceUnlocked = false;
                await callbacks.fetchSessions(vault, sessionId);
            } catch (error) {
                console.error('Failed to save workspace path:', error);
                callbacks.addChatErrorMessage(`Workspace not saved: ${error.message}`);
            } finally {
                syncControls();
            }
        }

        function unlockPath() {
            if (!elements.workspacePathInput || state.isLoading) return;
            const confirmed = window.confirm(
                'Unlock workspace editing for this session? Future turns will use the updated workspace path.'
            );
            if (!confirmed) return;
            state.isWorkspaceUnlocked = true;
            syncControls();
            elements.workspacePathInput.focus();
        }

        function openModal() {
            if (!elements.workspacePathInput) return;
            const vault = elements.vaultSelector?.value || '';
            if (!vault) {
                alert('Select a vault before choosing a workspace.');
                return;
            }
            closeModal();

            const overlay = document.createElement('div');
            overlay.id = 'workspace-picker-modal';
            overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
            overlay.innerHTML = `
                <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="workspace-picker-modal-title">
                    <div class="app-modal-header flex-none">
                        <div class="app-modal-title-block">
                            <h2 id="workspace-picker-modal-title" class="text-lg font-semibold text-txt-primary">Workspace</h2>
                            <p class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(elements.vaultSelector?.value || 'No vault selected')}</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-compact" data-workspace-picker-close aria-label="Close" title="Close">${icons.X_ICON_SVG}</button>
                        </div>
                    </div>
                    <div id="workspace-picker-body" class="p-4 flex-1 overflow-y-auto">
                        <div class="text-sm text-txt-secondary">Loading folders...</div>
                    </div>
                </section>
            `;

            overlay.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (event.target === overlay || event.target.closest('[data-workspace-picker-close]')) {
                    closeModal();
                    return;
                }
                const toggle = target.closest('[data-workspace-toggle]');
                if (toggle instanceof HTMLElement) {
                    await toggleTreeNode(toggle);
                    return;
                }
                const selectPath = target.closest('[data-workspace-select]')?.getAttribute('data-workspace-select');
                if (selectPath !== null && selectPath !== undefined) {
                    elements.workspacePathInput.value = selectPath;
                    elements.workspacePathInput.dispatchEvent(new Event('input', { bubbles: true }));
                    state.isWorkspaceUnlocked = true;
                    syncControls();
                    await savePath();
                    closeModal();
                }
            });

            document.body.appendChild(overlay);
            loadDirectory(overlay).catch((error) => {
                const body = overlay.querySelector('#workspace-picker-body');
                if (body) {
                    body.innerHTML = `<p class="state-error">Unable to load folders: ${escapeHtml(error.message)}</p>`;
                }
            });
        }

        function closeModal() {
            document.getElementById('workspace-picker-modal')?.remove();
        }

        async function loadDirectory(modal, path) {
            const body = modal.querySelector('#workspace-picker-body');
            const vault = elements.vaultSelector?.value || '';
            if (!body || !vault) return;

            body.innerHTML = '<div class="text-sm text-txt-secondary">Loading folders...</div>';
            const payload = await fetchDirectories(path || '');
            const directories = Array.isArray(payload.directories) ? payload.directories : [];
            const selectedPath = currentPath();

            body.innerHTML = `
                <div class="space-y-3">
                    <div class="p-3 rounded border border-border-primary bg-app-elevated">
                        <div class="text-xs uppercase text-txt-secondary">Selected workspace</div>
                        <div class="mt-1 text-sm cell-mono text-txt-primary">${escapeHtml(selectedPath || 'No workspace')}</div>
                    </div>
                    <div class="workspace-tree" role="tree">
                        ${directories.length ? directories.map((directory) => renderDirectoryRow(directory, 0)).join('') : '<p class="text-sm text-txt-secondary">No folders available.</p>'}
                    </div>
                </div>
            `;
        }

        async function fetchDirectories(path) {
            const vault = elements.vaultSelector?.value || '';
            const params = new URLSearchParams();
            if (path) params.set('path', path);
            const suffix = params.toString() ? `?${params.toString()}` : '';
            const response = await fetch(`api/vaults/${encodeURIComponent(vault)}/directories${suffix}`);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        async function toggleTreeNode(toggle) {
            const row = toggle.closest('[data-workspace-row]');
            if (!(row instanceof HTMLElement)) return;

            const path = row.getAttribute('data-workspace-row') || '';
            const children = row.querySelector(':scope > [data-workspace-children]');
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

            children.innerHTML = '<div class="py-1 text-xs text-txt-secondary">Loading...</div>';
            try {
                const payload = await fetchDirectories(path);
                const directories = Array.isArray(payload.directories) ? payload.directories : [];
                const depth = Number.parseInt(row.getAttribute('data-workspace-depth') || '0', 10) + 1;
                children.innerHTML = directories.length
                    ? directories.map((directory) => renderDirectoryRow(directory, depth)).join('')
                    : '<div class="py-1 text-xs text-txt-secondary">No child folders.</div>';
                children.dataset.loaded = 'true';
            } catch (error) {
                children.innerHTML = `<div class="py-1 text-xs state-error">Unable to load folders: ${escapeHtml(error.message)}</div>`;
            }
        }

        function renderDirectoryRow(directory, depth) {
            const path = String(directory.path || '');
            const name = String(directory.name || path || 'Folder');
            const indent = Math.min(Math.max(depth, 0) * 1.25, 5);
            return `
                <div data-workspace-row="${escapeHtml(path)}" data-workspace-depth="${depth}">
                    <div class="workspace-tree-row" role="treeitem" style="padding-left: ${indent}rem;">
                        ${directory.has_children
                            ? `<button type="button" class="workspace-tree-toggle" data-workspace-toggle aria-expanded="false" aria-label="Expand ${escapeHtml(name)}">
                                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                                    <path d="M7.25 4.75 12.75 10l-5.5 5.25" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                                </svg>
                            </button>`
                            : '<span class="workspace-tree-spacer" aria-hidden="true"></span>'}
                        <button type="button" class="workspace-tree-select" data-workspace-select="${escapeHtml(path)}">
                            <svg class="workspace-tree-folder-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                                <path d="M2 10h20" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
                            </svg>
                            <span class="workspace-tree-label min-w-0">
                                <span class="workspace-tree-name">${escapeHtml(name)}</span>
                            </span>
                        </button>
                    </div>
                    <div class="workspace-tree-children hidden" data-workspace-children></div>
                </div>
            `;
        }

        return Object.freeze({
            syncControls,
            currentPath,
            savePath,
            unlockPath,
            openModal,
            closeModal,
        });
    }

    window.WorkspacePicker = Object.freeze({
        create: createWorkspacePickerController,
    });
})(window, document);
