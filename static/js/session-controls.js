(function sessionControlsModule(window) {
    function createSessionControlsController({ state, elements, composeState, icons, utils, sessionSummary, callbacks }) {
        const { escapeHtml } = utils;
        let editingSessionId = '';

        function setMenuOpen(open) {
            composeState.sessionMenuOpen = Boolean(open);
            const hadEditingSession = Boolean(editingSessionId);
            if (!composeState.sessionMenuOpen) {
                editingSessionId = '';
                sessionSummary.closePreview();
            }
            if (elements.sessionDropdown) {
                elements.sessionDropdown.classList.toggle('open', composeState.sessionMenuOpen);
            }
            if (elements.sessionDropdownMenu) {
                elements.sessionDropdownMenu.classList.toggle('hidden', !composeState.sessionMenuOpen);
            }
            if (elements.sessionDropdownTrigger) {
                elements.sessionDropdownTrigger.setAttribute('aria-expanded', composeState.sessionMenuOpen ? 'true' : 'false');
            }
            if (elements.sessionDropdownChevronTrigger) {
                elements.sessionDropdownChevronTrigger.setAttribute('aria-expanded', composeState.sessionMenuOpen ? 'true' : 'false');
            }
            if (!composeState.sessionMenuOpen && hadEditingSession) {
                renderSelector();
            }
        }

        function title(session) {
            if (!session || !session.session_id) {
                return 'New session';
            }
            const sessionTitle = String(session.title || '').trim();
            return sessionTitle || session.session_id;
        }

        function activityLabel(session) {
            if (!session || !session.session_id) {
                return '';
            }
            const rawDate = session.last_activity_at || session.created_at || '';
            const parsed = rawDate ? new Date(rawDate.replace(' ', 'T')) : null;
            const activity = parsed && !Number.isNaN(parsed.getTime())
                ? parsed.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
                : rawDate;
            return activity ? `Updated ${activity}` : 'No activity yet';
        }

        function formatOptionLabel(session) {
            if (!session || !session.session_id) {
                return 'New session';
            }
            const meta = activityLabel(session);
            return meta ? `${title(session)} (${meta})` : title(session);
        }

        function renderSelector() {
            if (!elements.sessionDropdownMenu || !elements.sessionDropdownLabel) return;

            const activeSession = state.sessions.find((session) => session.session_id === state.sessionId) || null;
            const activeMeta = activityLabel(activeSession);
            const activeHasSummary = Boolean(activeSession?.has_summary);
            elements.sessionDropdownLabel.innerHTML = `
                <span class="session-dropdown-title-wrap">
                    <span class="session-dropdown-title">${escapeHtml(title(activeSession))}</span>
                    ${activeHasSummary ? '<span class="session-summary-marker" aria-hidden="true">✦</span>' : ''}
                </span>
            `;
            if (elements.sessionDropdownActiveActions) {
                elements.sessionDropdownActiveActions.innerHTML = activeSession
                    ? renderSessionActions(activeSession.session_id)
                    : '';
            }
            if (elements.sessionDropdownActiveMeta) {
                elements.sessionDropdownActiveMeta.textContent = activeMeta || '';
            }

            const rows = [
                renderDropdownRow(null, !activeSession),
                ...state.sessions.map((session) => renderDropdownRow(session, session.session_id === state.sessionId)),
            ];
            elements.sessionDropdownMenu.innerHTML = rows.join('');
            updateSummaryTrigger();
            focusEditingInput();
        }

        function renderDropdownRow(session, isActive) {
            const sessionId = session?.session_id || '';
            const hasSummary = Boolean(session?.has_summary);
            const meta = activityLabel(session);
            const isEditing = Boolean(sessionId && editingSessionId === sessionId);
            const previewAttribute = hasSummary ? ` data-session-summary-preview-id="${escapeHtml(sessionId)}"` : '';
            const previewFocusAttribute = hasSummary ? ` data-session-summary-preview-focus-id="${escapeHtml(sessionId)}"` : '';
            const marker = hasSummary ? '<span class="session-summary-marker" aria-hidden="true">✦</span>' : '';
            if (isEditing) {
                return renderEditingDropdownRow(session, isActive);
            }
            return `
                <div
                    class="session-dropdown-option${isActive ? ' is-active' : ''}"
                    role="option"
                    aria-selected="${isActive ? 'true' : 'false'}"
                    data-session-row-id="${escapeHtml(sessionId)}"
                >
                    <span class="session-dropdown-main">
                        <button type="button" class="session-dropdown-select-button" data-session-id="${escapeHtml(sessionId)}"${previewFocusAttribute}>
                            <span class="session-dropdown-title-wrap"${previewAttribute}>
                                <span class="session-dropdown-title">${escapeHtml(title(session))}</span>
                                ${marker}
                            </span>
                        </button>
                        ${sessionId ? renderSessionActions(sessionId) : ''}
                    </span>
                    ${meta ? `<span class="session-dropdown-meta">${escapeHtml(meta)}</span>` : ''}
                </div>
            `;
        }

        function renderEditingDropdownRow(session, isActive) {
            const sessionId = session?.session_id || '';
            return `
                <div
                    class="session-dropdown-option session-dropdown-option-editing${isActive ? ' is-active' : ''}"
                    role="option"
                    aria-selected="${isActive ? 'true' : 'false'}"
                    data-session-editing-id="${escapeHtml(sessionId)}"
                >
                    <input
                        type="text"
                        class="session-dropdown-title-input"
                        value="${escapeHtml(session?.title || '')}"
                        placeholder="Add a title..."
                        maxlength="120"
                        data-session-title-input="${escapeHtml(sessionId)}"
                        aria-label="Session title"
                    />
                    <div class="session-dropdown-row-actions">
                        ${renderRowActionButton('save-title', sessionId, 'Save title', icons.CHECK_ICON_SVG)}
                        ${renderRowActionButton('cancel-title', sessionId, 'Cancel title edit', icons.X_ICON_SVG)}
                    </div>
                </div>
            `;
        }

        function renderSessionActions(sessionId) {
            return `
                <div class="session-dropdown-row-actions" aria-label="Session actions">
                    ${renderRowActionButton('edit-title', sessionId, 'Edit title', icons.EDIT_ICON_SVG)}
                    ${renderRowActionButton('export', sessionId, 'Export transcript', icons.DOWNLOAD_ICON_SVG)}
                    ${renderRowActionButton('delete', sessionId, 'Delete session', icons.TRASH_ICON_SVG, 'is-danger')}
                </div>
            `;
        }

        function renderRowActionButton(action, sessionId, label, icon, extraClass = '') {
            const classes = ['session-dropdown-action', extraClass].filter(Boolean).join(' ');
            return `
                <button
                    type="button"
                    class="${classes}"
                    data-session-action="${action}"
                    data-session-action-id="${escapeHtml(sessionId)}"
                    title="${escapeHtml(label)}"
                    aria-label="${escapeHtml(label)}"
                >${icon}</button>
            `;
        }

        function focusEditingInput() {
            if (!editingSessionId || !elements.sessionDropdownMenu) return;
            window.requestAnimationFrame(() => {
                const input = elements.sessionDropdownMenu.querySelector(
                    `[data-session-title-input="${cssEscape(editingSessionId)}"]`
                );
                if (input instanceof HTMLInputElement) {
                    input.focus();
                    input.select();
                }
            });
        }

        function updateSummaryTrigger() {
            if (!elements.sessionSummaryTrigger) return;
            const session = sessionSummary.selectedSessionWithSummary();
            if (!session) {
                elements.sessionSummaryTrigger.classList.remove('is-visible');
                elements.sessionSummaryTrigger.setAttribute('aria-hidden', 'true');
                return;
            }
            elements.sessionSummaryTrigger.classList.add('is-visible');
            elements.sessionSummaryTrigger.removeAttribute('aria-hidden');
        }

        async function selectFromDropdown(sessionId) {
            setMenuOpen(false);
            editingSessionId = '';
            if (!sessionId) {
                await callbacks.clearSession(false);
            } else {
                await callbacks.loadSession(sessionId);
            }
        }

        function renderCompactionProgress(status) {
            const fill = elements.compactionFill;
            const track = elements.compactionTrack;
            if (!fill || !track) return;

            fill.classList.remove('compaction-warm', 'compaction-hot');
            if (!status || !status.compaction_token_threshold || status.compaction_type === 'none') {
                fill.style.width = '0%';
                track.title = status && status.compaction_type === 'none'
                    ? 'Chat history compaction is disabled'
                    : 'Chat history compaction status unavailable';
                return;
            }

            const threshold = Math.max(Number(status.compaction_token_threshold) || 0, 1);
            const tokens = Math.max(Number(status.estimated_tokens_before) || 0, 0);
            const percent = Math.round((tokens / threshold) * 100);
            const boundedPercent = tokens > 0 ? Math.max(2, Math.min(percent, 100)) : 0;
            fill.style.width = `${boundedPercent}%`;
            if (percent >= 100) {
                fill.classList.add('compaction-hot');
            } else if (percent >= 70) {
                fill.classList.add('compaction-warm');
            }
            const actionText = status.compaction_type === 'auto'
                ? 'Chat will be automatically compacted at 100%.'
                : 'Ask chat to compact when ready.';
            track.title = `${percent}% (${tokens.toLocaleString()} / ${threshold.toLocaleString()} threshold). ${actionText}`;
        }

        function clearCompactionProgress() {
            state.compactionStatusRequestId += 1;
            renderCompactionProgress(null);
        }

        async function refreshCompactionProgress() {
            const vault = elements.vaultSelector?.value || '';
            const sessionId = state.sessionId || '';
            if (!vault || !sessionId) {
                clearCompactionProgress();
                return;
            }

            const requestId = state.compactionStatusRequestId + 1;
            state.compactionStatusRequestId = requestId;
            try {
                const response = await fetch(
                    `api/chat/sessions/${encodeURIComponent(sessionId)}/compaction-status?vault_name=${encodeURIComponent(vault)}`
                );
                if (requestId !== state.compactionStatusRequestId) return;
                if (!response.ok) {
                    throw new Error('Failed to fetch chat compaction status');
                }
                renderCompactionProgress(await response.json());
            } catch (error) {
                if (requestId === state.compactionStatusRequestId) {
                    console.error('Error fetching chat compaction status:', error);
                    renderCompactionProgress(null);
                }
            }
        }

        function updateTitleRow() {
            renderSelector();
        }

        async function saveTitle(sessionId = state.sessionId, titleValue = '', btn = null) {
            const vault = elements.vaultSelector?.value || '';
            if (!sessionId || !vault) return;

            const nextTitle = String(titleValue || '').trim() || null;
            if (btn) btn.disabled = true;
            try {
                const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/title`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vault_name: vault, title: nextTitle }),
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const session = state.sessions.find((s) => s.session_id === sessionId);
                if (session) session.title = nextTitle;
                editingSessionId = '';
                renderSelector();
            } catch (error) {
                console.error('Failed to save session title:', error);
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        async function exportCurrent(sessionId = state.sessionId, btn = null) {
            const vault = elements.vaultSelector?.value || '';
            if (!sessionId || !vault) return;

            if (btn) btn.disabled = true;
            try {
                const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/export`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vault_name: vault }),
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const payload = await response.json();
                alert(`Transcript exported to ${payload.filename}`);
            } catch (error) {
                console.error('Failed to export session transcript:', error);
                alert('Failed to export transcript');
            } finally {
                if (btn) btn.disabled = false;
                callbacks.syncChatControlLocks();
            }
        }

        async function deleteCurrent(sessionId = state.sessionId, btn = null) {
            const vault = elements.vaultSelector?.value || '';
            if (!sessionId || !vault) return;

            if (!confirm(
                `Delete session "${sessionId}"? This removes it from the chat session list and database only. Exported transcripts are not deleted.`
            )) return;

            if (btn) btn.disabled = true;
            try {
                const response = await fetch(
                    `api/chat/sessions/${encodeURIComponent(sessionId)}?vault_name=${encodeURIComponent(vault)}`,
                    { method: 'DELETE' }
                );
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const deletedActiveSession = state.sessionId === sessionId;
                state.sessions = state.sessions.filter((s) => s.session_id !== sessionId);
                if (deletedActiveSession) {
                    state.sessionId = null;
                }
                editingSessionId = '';
                if (deletedActiveSession) {
                    callbacks.clearPendingAttachments();
                    callbacks.renderChatEmptyState();
                }
                renderSelector();
                callbacks.syncChatControlLocks();
                callbacks.updateStatus();
            } catch (error) {
                console.error('Failed to delete session:', error);
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        async function handleSessionAction(button) {
            const action = button.dataset.sessionAction || '';
            const sessionId = button.dataset.sessionActionId || '';
            if (!sessionId) return;
            if (action === 'delete' && state.isLoading && sessionId === state.sessionId) return;

            if (action === 'edit-title') {
                editingSessionId = sessionId;
                setMenuOpen(true);
                renderSelector();
                return;
            }
            if (action === 'cancel-title') {
                editingSessionId = '';
                renderSelector();
                return;
            }
            if (action === 'save-title') {
                const input = elements.sessionDropdownMenu?.querySelector(
                    `[data-session-title-input="${cssEscape(sessionId)}"]`
                );
                const titleValue = input instanceof HTMLInputElement ? input.value : '';
                await saveTitle(sessionId, titleValue, button);
                return;
            }
            if (action === 'export') {
                await exportCurrent(sessionId, button);
                return;
            }
            if (action === 'delete') {
                await deleteCurrent(sessionId, button);
            }
        }

        function cssEscape(value) {
            if (window.CSS && typeof window.CSS.escape === 'function') {
                return window.CSS.escape(value);
            }
            return String(value).replace(/"/g, '\\"');
        }

        function attachEventListeners() {
            const toggleSessionMenu = () => {
                if (elements.sessionDropdownTrigger?.disabled) {
                    return;
                }
                setMenuOpen(!composeState.sessionMenuOpen);
            };

            const handleClosedSelectorClick = (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (!target.closest('.session-dropdown-trigger')) return;
                if (target.closest('[data-session-action]')) return;
                event.stopPropagation();
                toggleSessionMenu();
            };

            if (elements.sessionDropdown) {
                elements.sessionDropdown.addEventListener('click', handleClosedSelectorClick);
            }

            if (elements.sessionDropdownTrigger) {
                elements.sessionDropdownTrigger.addEventListener('click', (event) => {
                    event.stopPropagation();
                    toggleSessionMenu();
                });
            }
            if (elements.sessionDropdownChevronTrigger) {
                elements.sessionDropdownChevronTrigger.addEventListener('click', (event) => {
                    event.stopPropagation();
                    toggleSessionMenu();
                });
            }

            if (elements.sessionDropdownMenu) {
                elements.sessionDropdownMenu.addEventListener('click', async (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const actionButton = target.closest('[data-session-action]');
                    if (actionButton instanceof HTMLButtonElement) {
                        event.preventDefault();
                        event.stopPropagation();
                        await handleSessionAction(actionButton);
                        return;
                    }
                    const option = target.closest('[data-session-row-id]');
                    if (option instanceof HTMLElement) {
                        event.preventDefault();
                        await selectFromDropdown(option.dataset.sessionRowId || '');
                    }
                });
                elements.sessionDropdownMenu.addEventListener('keydown', async (event) => {
                    const target = event.target;
                    if (!(target instanceof HTMLInputElement)) return;
                    const sessionId = target.dataset.sessionTitleInput || '';
                    if (!sessionId) return;
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        await saveTitle(sessionId, target.value);
                    } else if (event.key === 'Escape') {
                        event.preventDefault();
                        editingSessionId = '';
                        renderSelector();
                    }
                });
                elements.sessionDropdownMenu.addEventListener('mouseover', (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const previewTarget = target.closest('[data-session-summary-preview-id]');
                    if (!(previewTarget instanceof HTMLElement)) return;
                    const related = event.relatedTarget;
                    if (related instanceof Element && previewTarget.contains(related)) return;
                    const sessionId = previewTarget.dataset.sessionSummaryPreviewId || '';
                    const session = state.sessions.find((item) => item.session_id === sessionId);
                    sessionSummary.openPreview(previewTarget, session);
                });
                elements.sessionDropdownMenu.addEventListener('mouseout', (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const previewTarget = target.closest('[data-session-summary-preview-id]');
                    if (!(previewTarget instanceof HTMLElement)) return;
                    const related = event.relatedTarget;
                    if (related instanceof Element && previewTarget.contains(related)) return;
                    sessionSummary.closePreview();
                });
                elements.sessionDropdownMenu.addEventListener('focusin', (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const previewTarget = target.closest('[data-session-summary-preview-focus-id]');
                    if (!(previewTarget instanceof HTMLElement)) return;
                    const sessionId = previewTarget.dataset.sessionSummaryPreviewFocusId || '';
                    const session = state.sessions.find((item) => item.session_id === sessionId);
                    sessionSummary.openPreview(previewTarget, session);
                });
                elements.sessionDropdownMenu.addEventListener('focusout', (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    if (target.closest('[data-session-summary-preview-focus-id]')) {
                        sessionSummary.closePreview();
                    }
                });
            }

            if (elements.sessionDropdownActiveActions) {
                elements.sessionDropdownActiveActions.addEventListener('click', async (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const actionButton = target.closest('[data-session-action]');
                    if (actionButton instanceof HTMLButtonElement) {
                        event.preventDefault();
                        event.stopPropagation();
                        await handleSessionAction(actionButton);
                    }
                });
            }

            if (elements.sessionSummaryTrigger) {
                elements.sessionSummaryTrigger.addEventListener('mouseenter', () => sessionSummary.warmPreview(sessionSummary.selectedSessionWithSummary()));
                elements.sessionSummaryTrigger.addEventListener('focus', () => sessionSummary.warmPreview(sessionSummary.selectedSessionWithSummary()));
                elements.sessionSummaryTrigger.addEventListener('click', () => sessionSummary.openModalForSession(sessionSummary.selectedSessionWithSummary()));
            }

        }

        return Object.freeze({
            setMenuOpen,
            formatOptionLabel,
            renderSelector,
            clearCompactionProgress,
            refreshCompactionProgress,
            updateTitleRow,
            attachEventListeners,
            saveTitle,
            exportCurrent,
            deleteCurrent,
        });
    }

    window.SessionControls = Object.freeze({
        create: createSessionControlsController,
    });
})(window);
