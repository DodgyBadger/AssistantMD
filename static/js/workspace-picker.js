(function workspacePickerModule(window) {
    function createWorkspacePickerController({ state, elements, callbacks }) {
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
            callbacks.syncExplorerButtons?.();
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

        async function setPath(path) {
            if (!elements.workspacePathInput) return;
            elements.workspacePathInput.value = path || '';
            elements.workspacePathInput.dispatchEvent(new Event('input', { bubbles: true }));
            state.isWorkspaceUnlocked = true;
            syncControls();
            await savePath();
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
            callbacks.openVaultExplorer?.({
                revealPath: currentPath(),
                subtitle: vault,
            });
        }

        function closeModal() {
            callbacks.closePathPicker?.();
        }

        return Object.freeze({
            syncControls,
            currentPath,
            savePath,
            setPath,
            unlockPath,
            openModal,
            closeModal,
        });
    }

    window.WorkspacePicker = Object.freeze({
        create: createWorkspacePickerController,
    });
})(window);
