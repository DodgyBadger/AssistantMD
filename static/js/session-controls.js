(function sessionControlsModule(window) {
    function createSessionControlsController({ state, elements, composeState, utils, sessionSummary, callbacks }) {
        const { escapeHtml } = utils;

        function setMenuOpen(open) {
            composeState.sessionMenuOpen = Boolean(open);
            if (!composeState.sessionMenuOpen) {
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
            elements.sessionDropdownLabel.innerHTML = `
                <span class="session-dropdown-title">${escapeHtml(title(activeSession))}</span>
                ${activeMeta ? `<span class="session-dropdown-meta">${escapeHtml(activeMeta)}</span>` : ''}
            `;

            const rows = [
                renderDropdownRow(null, !activeSession),
                ...state.sessions.map((session) => renderDropdownRow(session, session.session_id === state.sessionId)),
            ];
            elements.sessionDropdownMenu.innerHTML = rows.join('');
            updateSummaryTrigger();
        }

        function renderDropdownRow(session, isActive) {
            const sessionId = session?.session_id || '';
            const hasSummary = Boolean(session?.has_summary);
            const meta = activityLabel(session);
            const previewAttribute = hasSummary ? ` data-session-summary-preview-id="${escapeHtml(sessionId)}"` : '';
            const previewFocusAttribute = hasSummary ? ` data-session-summary-preview-focus-id="${escapeHtml(sessionId)}"` : '';
            const marker = hasSummary ? '<span class="session-summary-marker" aria-hidden="true">✦</span>' : '';
            return `
                <div
                    class="session-dropdown-option${isActive ? ' is-active' : ''}"
                    role="option"
                    aria-selected="${isActive ? 'true' : 'false'}"
                >
                    <button type="button" class="session-dropdown-select-button" data-session-id="${escapeHtml(sessionId)}"${previewFocusAttribute}>
                        <span class="session-dropdown-label">
                            <span class="session-dropdown-title-wrap"${previewAttribute}>
                                <span class="session-dropdown-title">${escapeHtml(title(session))}</span>
                                ${marker}
                            </span>
                            ${meta ? `<span class="session-dropdown-meta">${escapeHtml(meta)}</span>` : ''}
                        </span>
                    </button>
                </div>
            `;
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
            const row = elements.sessionTitleRow;
            const input = elements.sessionTitleInput;
            if (!row || !input) return;

            const sessionId = state.sessionId;
            if (!sessionId) {
                row.classList.add('hidden');
                input.value = '';
                return;
            }

            const session = state.sessions.find((s) => s.session_id === sessionId);
            input.value = session?.title || '';
            row.classList.remove('hidden');
        }

        async function saveTitle() {
            const sessionId = state.sessionId;
            const vault = elements.vaultSelector?.value || '';
            const input = elements.sessionTitleInput;
            const btn = elements.sessionTitleSave;
            if (!sessionId || !vault || !input || !btn) return;

            const nextTitle = input.value.trim() || null;
            btn.disabled = true;
            try {
                const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/title`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ vault_name: vault, title: nextTitle }),
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const session = state.sessions.find((s) => s.session_id === sessionId);
                if (session) session.title = nextTitle;
                renderSelector();
            } catch (error) {
                console.error('Failed to save session title:', error);
            } finally {
                btn.disabled = false;
            }
        }

        async function exportCurrent() {
            const sessionId = state.sessionId;
            const vault = elements.vaultSelector?.value || '';
            const btn = elements.sessionExportBtn;
            if (!sessionId || !vault || !btn) return;

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Exporting...';
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
                btn.textContent = originalText;
                callbacks.syncChatControlLocks();
            }
        }

        async function deleteCurrent() {
            const sessionId = state.sessionId;
            const vault = elements.vaultSelector?.value || '';
            const btn = elements.sessionDeleteBtn;
            if (!sessionId || !vault || !btn) return;

            if (!confirm(
                `Delete session "${sessionId}"? This removes it from the chat session list and database only. Exported transcripts are not deleted.`
            )) return;

            btn.disabled = true;
            try {
                const response = await fetch(
                    `api/chat/sessions/${encodeURIComponent(sessionId)}?vault_name=${encodeURIComponent(vault)}`,
                    { method: 'DELETE' }
                );
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                state.sessions = state.sessions.filter((s) => s.session_id !== sessionId);
                state.sessionId = null;
                callbacks.clearPendingAttachments();
                callbacks.renderChatEmptyState();
                renderSelector();
                updateTitleRow();
                callbacks.syncChatControlLocks();
                callbacks.updateStatus();
            } catch (error) {
                console.error('Failed to delete session:', error);
            } finally {
                btn.disabled = false;
            }
        }

        function attachEventListeners() {
            if (elements.sessionDropdownTrigger) {
                elements.sessionDropdownTrigger.addEventListener('click', (event) => {
                    event.stopPropagation();
                    if (elements.sessionDropdownTrigger.disabled) {
                        return;
                    }
                    setMenuOpen(!composeState.sessionMenuOpen);
                });
            }

            if (elements.sessionDropdownMenu) {
                elements.sessionDropdownMenu.addEventListener('click', async (event) => {
                    const target = event.target;
                    if (!(target instanceof Element)) return;
                    const option = target.closest('[data-session-id]');
                    if (option instanceof HTMLElement) {
                        event.preventDefault();
                        await selectFromDropdown(option.dataset.sessionId || '');
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

            if (elements.sessionSummaryTrigger) {
                elements.sessionSummaryTrigger.addEventListener('mouseenter', () => sessionSummary.warmPreview(sessionSummary.selectedSessionWithSummary()));
                elements.sessionSummaryTrigger.addEventListener('focus', () => sessionSummary.warmPreview(sessionSummary.selectedSessionWithSummary()));
                elements.sessionSummaryTrigger.addEventListener('click', () => sessionSummary.openModalForSession(sessionSummary.selectedSessionWithSummary()));
            }

            if (elements.sessionTitleSave) {
                elements.sessionTitleSave.addEventListener('click', saveTitle);
            }

            if (elements.sessionTitleInput) {
                elements.sessionTitleInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') saveTitle();
                });
            }

            if (elements.sessionDeleteBtn) {
                elements.sessionDeleteBtn.addEventListener('click', deleteCurrent);
            }

            if (elements.sessionExportBtn) {
                elements.sessionExportBtn.addEventListener('click', exportCurrent);
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
