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
            pickerOpen = true;
            callbacks.openPathPicker?.({
                id: 'file-reference-picker-modal',
                title: 'Add File Reference',
                mode: 'files',
                subtitle: selectedVault(),
                missingVaultMessage: 'Select a vault before adding file references.',
                initialScope: workspacePath() ? 'workspace' : 'vault',
                onSelect: ({ path }) => {
                    insertReference(path);
                    pickerOpen = false;
                },
                onClose: () => {
                    pickerOpen = false;
                },
            });
        }

        function closePicker() {
            callbacks.closePathPicker?.();
            pickerOpen = false;
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
