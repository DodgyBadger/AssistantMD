(function editProposalsModule(window, document) {
    function createEditProposalsController({ state, elements, icons, utils, callbacks }) {
        const { escapeHtml } = utils;
        const renderedRefs = new WeakMap();

        function renderArtifact(container, artifactRef) {
            if (!(container instanceof HTMLElement) || !artifactRef) return;
            if (renderedRefs.get(container) === artifactRef) return;
            renderedRefs.set(container, artifactRef);
            container.innerHTML = '<div class="edit-proposal-card edit-proposal-loading">Loading edit proposal...</div>';
            fetchProposal(artifactRef)
                .then((proposal) => {
                    container.innerHTML = renderProposalCard(proposal);
                    bindProposalCard(container, proposal);
                    autosizeReplacementTextareas(container);
                })
                .catch((error) => {
                    container.innerHTML = `<div class="edit-proposal-card state-error">Unable to load edit proposal: ${escapeHtml(error.message)}</div>`;
                });
        }

        async function fetchProposal(artifactRef) {
            const vault = selectedVault();
            const sessionId = state.sessionId || '';
            if (!vault || !sessionId) {
                throw new Error('Missing active vault or chat session.');
            }
            const response = await fetch(
                `api/vaults/${encodeURIComponent(vault)}/chat/${encodeURIComponent(sessionId)}/edit-proposals/${encodePathArtifactRef(artifactRef)}`
            );
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return response.json();
        }

        function renderProposalCard(proposal) {
            const edits = Array.isArray(proposal.edits) ? proposal.edits : [];
            const applied = proposal.status === 'applied';
            const denied = proposal.status === 'denied';
            const locked = applied || denied;
            return `
                <section class="edit-proposal-card" data-edit-proposal-card="${escapeHtml(proposal.artifact_ref || '')}">
                    <div class="edit-proposal-header">
                        <button type="button" class="edit-proposal-toggle" data-edit-proposal-toggle aria-expanded="true">
                            <span class="edit-proposal-chevron" aria-hidden="true">▾</span>
                            <span class="edit-proposal-title-block">
                                <span class="edit-proposal-title">${escapeHtml(proposal.title || 'Proposed file edits')}</span>
                                ${proposal.summary ? `<span class="edit-proposal-summary">${escapeHtml(proposal.summary)}</span>` : ''}
                            </span>
                        </button>
                        <div class="edit-proposal-header-actions">
                            <label class="edit-proposal-select-all">
                                <input type="checkbox" data-edit-proposal-select-all ${locked ? 'disabled' : ''} />
                                <span>Select all</span>
                            </label>
                            <span class="edit-proposal-status">${escapeHtml(proposalStatusLabel(proposal.status))}</span>
                        </div>
                    </div>
                    <div class="edit-proposal-body" data-edit-proposal-body>
                        <div class="edit-proposal-edits">
                            ${edits.map((edit, index) => renderEdit(edit, index, locked)).join('')}
                        </div>
                        <div class="edit-proposal-footer">
                            <div class="edit-proposal-feedback" data-edit-proposal-feedback></div>
                            <div class="edit-proposal-actions">
                                <button type="button" class="ui-icon-button is-primary is-compact" data-edit-proposal-apply aria-label="Apply selected edits" title="Apply selected edits" ${locked ? 'disabled' : ''}>
                                    ${icons.CHECK_ICON_SVG || ''}
                                </button>
                                <button type="button" class="ui-icon-button is-compact" data-edit-proposal-deny aria-label="Deny proposal" title="Deny proposal" ${locked ? 'disabled' : ''}>
                                    ${icons.CIRCLE_X_ICON_SVG || icons.X_ICON_SVG || ''}
                                </button>
                            </div>
                        </div>
                    </div>
                </section>
            `;
        }

        function renderEdit(edit, index, applied) {
            const editId = String(edit.edit_id || `edit-${index + 1}`);
            const path = String(edit.path || '');
            return `
                <article class="edit-proposal-edit" data-edit-proposal-edit="${escapeHtml(editId)}">
                    <label class="edit-proposal-edit-top">
                        <input type="checkbox" data-edit-proposal-checkbox value="${escapeHtml(editId)}" ${applied ? 'disabled' : ''} />
                        <span class="edit-proposal-path-wrap">
                            <button type="button" class="vault-file-link" data-edit-proposal-open-file="${escapeHtml(path)}">@${escapeHtml(path)}</button>
                            ${edit.rationale ? `<span class="edit-proposal-rationale">${escapeHtml(edit.rationale)}</span>` : ''}
                        </span>
                    </label>
                    <div class="edit-proposal-diff">
                        <div>
                            <div class="edit-proposal-label">Original</div>
                            <pre>${escapeHtml(edit.original_text || '')}</pre>
                        </div>
                        <div>
                            <div class="edit-proposal-label">Replacement</div>
                            <textarea data-edit-proposal-replacement="${escapeHtml(editId)}" spellcheck="false" ${applied ? 'disabled' : ''}>${escapeHtml(edit.replacement_text || '')}</textarea>
                        </div>
                    </div>
                </article>
            `;
        }

        function bindProposalCard(container, proposal) {
            container.addEventListener('click', async (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                const fileButton = target.closest('[data-edit-proposal-open-file]');
                if (fileButton instanceof HTMLElement) {
                    callbacks.openFile?.(fileButton.getAttribute('data-edit-proposal-open-file') || '');
                    return;
                }
                const toggleButton = target.closest('[data-edit-proposal-toggle]');
                if (toggleButton instanceof HTMLButtonElement) {
                    toggleProposalBody(container, toggleButton);
                    return;
                }
                const applyButton = target.closest('[data-edit-proposal-apply]');
                if (applyButton instanceof HTMLButtonElement) {
                    await applySelected(container, proposal, applyButton);
                    return;
                }
                const denyButton = target.closest('[data-edit-proposal-deny]');
                if (denyButton instanceof HTMLButtonElement) {
                    await denyProposal(container, proposal, denyButton);
                }
            });
            container.addEventListener('change', (event) => {
                const target = event.target;
                if (!(target instanceof HTMLInputElement)) return;
                if (target.matches('[data-edit-proposal-select-all]')) {
                    setAllSelected(container, target.checked);
                    return;
                }
                if (target.matches('[data-edit-proposal-checkbox]')) {
                    syncSelectAll(container);
                }
            });
            container.addEventListener('input', (event) => {
                const target = event.target;
                if (target instanceof HTMLTextAreaElement && target.matches('[data-edit-proposal-replacement]')) {
                    autosizeTextarea(target);
                }
            });
        }

        async function applySelected(container, proposal, button) {
            const feedback = container.querySelector('[data-edit-proposal-feedback]');
            const selected = Array.from(container.querySelectorAll('[data-edit-proposal-checkbox]'))
                .filter((checkbox) => checkbox instanceof HTMLInputElement && checkbox.checked)
                .map((checkbox) => checkbox.value);
            const overrides = {};
            Array.from(container.querySelectorAll('[data-edit-proposal-replacement]')).forEach((textarea) => {
                if (!(textarea instanceof HTMLTextAreaElement)) return;
                const editId = textarea.getAttribute('data-edit-proposal-replacement') || '';
                if (editId && selected.includes(editId)) {
                    overrides[editId] = textarea.value;
                }
            });
            if (!selected.length) {
                setFeedback(feedback, 'Select at least one edit.', 'error');
                return;
            }
            button.disabled = true;
            setFeedback(feedback, 'Applying selected edits...', 'info');
            try {
                const response = await fetch(
                    `api/vaults/${encodeURIComponent(selectedVault())}/chat/${encodeURIComponent(state.sessionId || '')}/edit-proposals/${encodePathArtifactRef(proposal.artifact_ref || '')}/apply`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            selected_edit_ids: selected,
                            replacement_overrides: overrides,
                        }),
                    }
                );
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                await response.json();
                setFeedback(feedback, 'Applied selected edits.', 'success');
                setProposalLocked(container, 'Applied');
                callbacks.enhanceFileLinks?.(container);
            } catch (error) {
                button.disabled = false;
                setFeedback(feedback, error.message, 'error');
            }
        }

        async function denyProposal(container, proposal, button) {
            const feedback = container.querySelector('[data-edit-proposal-feedback]');
            button.disabled = true;
            setFeedback(feedback, 'Denying proposal...', 'info');
            try {
                const response = await fetch(
                    `api/vaults/${encodeURIComponent(selectedVault())}/chat/${encodeURIComponent(state.sessionId || '')}/edit-proposals/${encodePathArtifactRef(proposal.artifact_ref || '')}/deny`,
                    { method: 'POST' }
                );
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                await response.json();
                setFeedback(feedback, 'Denied proposal.', 'info');
                setProposalLocked(container, 'Denied');
            } catch (error) {
                button.disabled = false;
                setFeedback(feedback, error.message, 'error');
            }
        }

        function setProposalLocked(container, statusLabel) {
            const status = container.querySelector('.edit-proposal-status');
            if (status) status.textContent = statusLabel;
            container.querySelectorAll('input, textarea, [data-edit-proposal-apply], [data-edit-proposal-deny]').forEach((item) => {
                item.disabled = true;
            });
        }

        function setAllSelected(container, checked) {
            container.querySelectorAll('[data-edit-proposal-checkbox]').forEach((checkbox) => {
                if (checkbox instanceof HTMLInputElement && !checkbox.disabled) {
                    checkbox.checked = checked;
                }
            });
        }

        function syncSelectAll(container) {
            const selectAll = container.querySelector('[data-edit-proposal-select-all]');
            if (!(selectAll instanceof HTMLInputElement)) return;
            const checkboxes = Array.from(container.querySelectorAll('[data-edit-proposal-checkbox]'))
                .filter((checkbox) => checkbox instanceof HTMLInputElement && !checkbox.disabled);
            const checkedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
            selectAll.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
            selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
        }

        function toggleProposalBody(container, toggleButton) {
            const body = container.querySelector('[data-edit-proposal-body]');
            if (!(body instanceof HTMLElement)) return;
            const expanded = toggleButton.getAttribute('aria-expanded') !== 'false';
            const nextExpanded = !expanded;
            toggleButton.setAttribute('aria-expanded', nextExpanded ? 'true' : 'false');
            body.hidden = !nextExpanded;
            const chevron = toggleButton.querySelector('.edit-proposal-chevron');
            if (chevron) chevron.textContent = nextExpanded ? '▾' : '▸';
        }

        function autosizeReplacementTextareas(container) {
            container.querySelectorAll('[data-edit-proposal-replacement]').forEach((textarea) => {
                if (textarea instanceof HTMLTextAreaElement) {
                    autosizeTextarea(textarea);
                }
            });
        }

        function autosizeTextarea(textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, 68), 260)}px`;
        }

        function setFeedback(element, message, kind) {
            if (!element) return;
            element.textContent = message || '';
            element.className = `edit-proposal-feedback ${kind ? `state-${kind}` : ''}`;
        }

        function proposalStatusLabel(status) {
            if (status === 'applied') return 'Applied';
            if (status === 'denied') return 'Denied';
            return 'Pending';
        }

        function selectedVault() {
            return elements.vaultSelector?.value || '';
        }

        function encodePathArtifactRef(value) {
            return String(value || '')
                .split('/')
                .map((part) => encodeURIComponent(part))
                .join('/');
        }

        return Object.freeze({
            renderArtifact,
        });
    }

    window.EditProposals = Object.freeze({
        create: createEditProposalsController,
    });
})(window, document);
