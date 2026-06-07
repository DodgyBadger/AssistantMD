// Shared SVG icon for copy buttons
const COPY_ICON_SVG = `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="8" y="8" width="14" height="14" rx="2" ry="2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></rect>
        <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>
`.trim();

const FORK_ICON_SVG = `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="18" r="3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></circle>
        <circle cx="6" cy="6" r="3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></circle>
        <circle cx="18" cy="6" r="3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></circle>
        <path d="M18 9v1a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M12 12v3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>
`.trim();

const SESSION_SUMMARY_ICON_SVG = `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M20 3v4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M22 5h-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M4 17v2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M5 18H3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>
`.trim();

const TYPING_DOTS_HTML = `
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
    <span class="typing-dot"></span>
`.trim();

const STATUS_EMOJIS = {
    thinking: '💬',
    tools: '🛠️',
    done: '✅',
    error: '⚠️'
};
const CHAT_EMPTY_STATE_MESSAGE = 'Start a conversation...';

// State management
const RESTART_NOTICE_TEXT = 'Restart the container to apply changes.';
const RESTART_STORAGE_KEY = 'assistantmd_restart_required';
const CHAT_COMPOSE_HEIGHT_STORAGE_KEY = 'assistantmd_chat_compose_height';
const CHAT_COMPOSE_DEFAULT_HEIGHT = 288;
const CHAT_COMPOSE_MIN_HEIGHT = 128;

const state = {
    sessionId: null,
    sessions: [],
    metadata: null,
    isLoading: false,
    isCancellingChat: false,
    activeChatSessionId: null,
    activeChatAbortController: null,
    systemStatus: null,
    sessionSummaryPreviewCache: {},
    sessionSummaryPreviewInFlight: {},
    vaultActivity: {},
    selectedActivityVault: '',
    dashboardVaultSort: { column: 'name', direction: 'asc' },
    dashboardWorkflowSort: { column: 'id', direction: 'asc' },
    workflowTasks: [],
    workflowTaskPollTimer: null,
    vaultActivitySort: { column: 'last_run', direction: 'desc' },
    vaultActivityMutationSort: { column: 'time', direction: 'desc' },
    restartRequired: false,
    shouldAutoScroll: true,
    compactionStatusRequestId: 0,
    isChatFocusMode: false,
    chatComposerResize: null,
    isWorkspaceUnlocked: false
};
const chatComposeState = {
    pendingAttachments: [],
    popoverOpen: false,
    toolMenuOpen: false,
    sessionMenuOpen: false
};

let mathTypesetQueue = Promise.resolve();

// DOM elements - Chat
const chatElements = {
    vaultSelector: document.getElementById('vault-selector'),
    workspacePathInput: document.getElementById('workspace-path-input'),
    workspacePickerBtn: document.getElementById('workspace-picker-btn'),
    workspaceUnlockBtn: document.getElementById('workspace-unlock-btn'),
    modelSelector: document.getElementById('model-selector'),
    templateSelector: document.getElementById('template-selector'),
    thinkingSelector: document.getElementById('thinking-selector'),
    sessionDropdown: document.getElementById('session-dropdown'),
    sessionDropdownTrigger: document.getElementById('session-dropdown-trigger'),
    sessionDropdownLabel: document.getElementById('session-dropdown-label'),
    sessionDropdownMenu: document.getElementById('session-dropdown-menu'),
    sessionSummaryTrigger: document.getElementById('session-summary-trigger'),
    toolDropdown: document.getElementById('tool-dropdown'),
    toolDropdownTrigger: document.getElementById('tool-dropdown-trigger'),
    toolDropdownMenu: document.getElementById('tool-dropdown-menu'),
    toolDropdownSummary: document.getElementById('tool-dropdown-summary'),
    toolsCheckboxes: document.getElementById('tools-checkboxes'),
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    attachBtn: document.getElementById('attach-btn'),
    attachInput: document.getElementById('attach-input'),
    attachCountBadge: document.getElementById('attach-count-badge'),
    attachmentPopover: document.getElementById('chat-attachment-popover'),
    sendBtn: document.getElementById('send-btn'),
    focusToggleInline: document.getElementById('chat-focus-toggle-inline'),
    focusDivider: document.getElementById('chat-focus-divider'),
    composer: document.getElementById('chat-composer'),
    compactionTrack: document.getElementById('chat-compaction-track'),
    compactionFill: document.getElementById('chat-compaction-fill'),
    sessionTitleRow: document.getElementById('session-title-row'),
    sessionTitleInput: document.getElementById('session-title-input'),
    sessionTitleSave: document.getElementById('session-title-save'),
    sessionExportBtn: document.getElementById('session-export-btn'),
    sessionDeleteBtn: document.getElementById('session-delete-btn'),
};

// DOM elements - Dashboard
const dashElements = {
    systemStatus: document.getElementById('system-status'),
    workflowsStatus: document.getElementById('dashboard-workflows-status'),
    workflowSchedulerBadge: document.getElementById('dashboard-workflows-scheduler-badge'),
    vaultActivityStatus: document.getElementById('dashboard-vault-activity-status'),
    rescanBtn: document.getElementById('rescan-btn'),
    rescanResult: document.getElementById('rescan-result'),
    executeWorkflowResult: document.getElementById('execute-workflow-result')
};

// DOM elements - Configuration
const configElements = {
    statusBanner: document.getElementById('config-status-banner'),
    statusMessages: document.getElementById('config-status-messages'),
    configTab: document.getElementById('configuration-tab')
};

function isChatNearBottom(element, threshold = 64) {
    if (!element) return true;
    const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
    return distance <= threshold;
}

function scrollChatToBottom(force = false) {
    const container = chatElements.chatMessages;
    if (!container) return;

    if (force) {
        state.shouldAutoScroll = true;
    }

    if (force || state.shouldAutoScroll) {
        container.scrollTop = container.scrollHeight;
    }
}

function getViewportHeight() {
    return window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight || 800;
}

function getChatComposerMaxHeight() {
    return Math.max(CHAT_COMPOSE_MIN_HEIGHT, Math.floor(getViewportHeight() * 0.72));
}

function clampChatComposerHeight(value) {
    const parsed = Number(value);
    const fallback = Math.min(CHAT_COMPOSE_DEFAULT_HEIGHT, getChatComposerMaxHeight());
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(Math.max(parsed, CHAT_COMPOSE_MIN_HEIGHT), getChatComposerMaxHeight());
}

function persistChatComposerHeight(height) {
    try {
        localStorage.setItem(CHAT_COMPOSE_HEIGHT_STORAGE_KEY, String(Math.round(height)));
    } catch (error) {
        console.warn('Failed to persist chat composer height:', error);
    }
}

function readStoredChatComposerHeight() {
    try {
        return localStorage.getItem(CHAT_COMPOSE_HEIGHT_STORAGE_KEY);
    } catch (error) {
        console.warn('Failed to read chat composer height:', error);
        return null;
    }
}

function setChatComposerHeight(height, { persist = true } = {}) {
    const clamped = clampChatComposerHeight(height);
    document.documentElement.style.setProperty('--chat-compose-height', `${clamped}px`);

    if (chatElements.focusDivider) {
        chatElements.focusDivider.setAttribute('aria-valuemin', String(CHAT_COMPOSE_MIN_HEIGHT));
        chatElements.focusDivider.setAttribute('aria-valuemax', String(getChatComposerMaxHeight()));
        chatElements.focusDivider.setAttribute('aria-valuenow', String(Math.round(clamped)));
    }

    if (persist) {
        persistChatComposerHeight(clamped);
    }

    return clamped;
}

function restoreChatComposerHeight() {
    setChatComposerHeight(readStoredChatComposerHeight(), { persist: false });
}

function syncChatFocusToggle() {
    const toggle = chatElements.focusToggleInline;
    if (!toggle) return;

    toggle.setAttribute('aria-pressed', state.isChatFocusMode ? 'true' : 'false');
    toggle.title = state.isChatFocusMode ? 'Return to normal chat layout' : 'Focus the chat workspace';
    toggle.setAttribute(
        'aria-label',
        state.isChatFocusMode ? 'Exit chat focus mode' : 'Focus chat workspace'
    );
}

function setChatFocusMode(enabled) {
    const nextValue = Boolean(enabled);
    if (state.isChatFocusMode === nextValue) return;

    state.isChatFocusMode = nextValue;
    document.body.classList.toggle('chat-focus-mode', state.isChatFocusMode);
    syncChatFocusToggle();

    if (state.isChatFocusMode) {
        restoreChatComposerHeight();
        window.requestAnimationFrame(() => {
            scrollChatToBottom();
            chatElements.chatInput?.focus();
        });
    } else {
        state.chatComposerResize = null;
    }
}

function toggleChatFocusMode() {
    setChatFocusMode(!state.isChatFocusMode);
}

function resizeFocusedChatComposerFromPointer(clientY) {
    if (!state.isChatFocusMode) return;
    const height = getViewportHeight() - Number(clientY || 0);
    setChatComposerHeight(height);
}

function handleChatFocusDividerPointerDown(event) {
    if (!state.isChatFocusMode || !chatElements.focusDivider) return;
    event.preventDefault();
    state.chatComposerResize = { pointerId: event.pointerId };
    chatElements.focusDivider.setPointerCapture?.(event.pointerId);
    resizeFocusedChatComposerFromPointer(event.clientY);
}

function handleChatFocusDividerPointerMove(event) {
    if (!state.chatComposerResize || state.chatComposerResize.pointerId !== event.pointerId) return;
    event.preventDefault();
    resizeFocusedChatComposerFromPointer(event.clientY);
}

function stopChatFocusDividerResize(event) {
    if (!state.chatComposerResize) return;
    if (event?.pointerId !== undefined && state.chatComposerResize.pointerId !== event.pointerId) return;

    if (event?.pointerId !== undefined) {
        chatElements.focusDivider?.releasePointerCapture?.(event.pointerId);
    }
    state.chatComposerResize = null;
}

function handleChatFocusDividerKeydown(event) {
    if (!state.isChatFocusMode) return;

    const current = clampChatComposerHeight(chatElements.composer?.getBoundingClientRect().height);
    const step = event.shiftKey ? 64 : 24;
    let nextHeight = null;

    if (event.key === 'ArrowUp') nextHeight = current + step;
    if (event.key === 'ArrowDown') nextHeight = current - step;
    if (event.key === 'Home') nextHeight = CHAT_COMPOSE_MIN_HEIGHT;
    if (event.key === 'End') nextHeight = getChatComposerMaxHeight();

    if (nextHeight === null) return;
    event.preventDefault();
    setChatComposerHeight(nextHeight);
}

function handleChatScroll() {
    const container = chatElements.chatMessages;
    if (!container) return;
    state.shouldAutoScroll = isChatNearBottom(container);
}

function isChatPlaceholderNode(node) {
    if (!node || !(node instanceof HTMLElement)) return false;
    return node.classList.contains('text-center') &&
        node.classList.contains('text-txt-secondary') &&
        node.classList.contains('text-sm');
}

function clearChatPlaceholderIfPresent() {
    const container = chatElements.chatMessages;
    if (!container) return;
    if (container.children.length !== 1) return;
    if (!isChatPlaceholderNode(container.children[0])) return;
    container.innerHTML = '';
}

function appendChatMessageNode(node, { forceScroll = true } = {}) {
    const container = chatElements.chatMessages;
    if (!container || !node) return;
    clearChatPlaceholderIfPresent();
    container.appendChild(node);
    scrollChatToBottom(forceScroll);
}

function renderChatEmptyState(message = CHAT_EMPTY_STATE_MESSAGE) {
    const container = chatElements.chatMessages;
    if (!container) return;
    container.innerHTML = '';
    const placeholder = document.createElement('div');
    placeholder.className = 'text-center text-txt-secondary text-sm';
    placeholder.textContent = message;
    container.appendChild(placeholder);
    state.shouldAutoScroll = true;
}

function addChatErrorMessage(errorText) {
    addMessage('error', `Error: ${errorText || 'Streaming failed'}`);
}

function formatAttachmentSize(sizeBytes) {
    if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = sizeBytes;
    let idx = 0;
    while (value >= 1024 && idx < units.length - 1) {
        value /= 1024;
        idx += 1;
    }
    const precision = idx === 0 ? 0 : 1;
    return `${value.toFixed(precision)} ${units[idx]}`;
}

function renderPendingAttachments() {
    const items = chatComposeState.pendingAttachments;
    const badge = chatElements.attachCountBadge;
    const popover = chatElements.attachmentPopover;
    const attachBtn = chatElements.attachBtn;

    if (badge) {
        if (!items.length) {
            badge.textContent = '';
            badge.style.display = 'none';
        } else {
            badge.textContent = String(items.length);
            badge.style.display = 'inline-flex';
        }
    }

    if (attachBtn) {
        attachBtn.classList.toggle('has-attachments', items.length > 0);
    }

    if (!popover) return;
    if (!items.length) {
        popover.classList.add('hidden');
        popover.innerHTML = '';
        popover.setAttribute('aria-hidden', 'true');
        chatComposeState.popoverOpen = false;
        if (attachBtn) {
            attachBtn.setAttribute('aria-expanded', 'false');
        }
        return;
    }

    const listHtml = items
        .map((item, index) => `
            <div class="chat-attachment-item">
                <span class="chat-attachment-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span>
                <span class="text-txt-secondary">${formatAttachmentSize(item.file.size)}</span>
                <button type="button" class="chat-attachment-remove" data-attachment-remove="${index}" aria-label="Remove attachment">✕</button>
            </div>
        `)
        .join('');
    popover.innerHTML = `
        <div class="chat-attachment-item">
            <button type="button" class="chat-attachment-remove" data-attachment-add="true" aria-label="Add images" style="padding:0.2rem 0.35rem;border-radius:0.35rem;border:1px solid rgb(var(--border-primary));">
                + Add images...
            </button>
        </div>
        ${listHtml}
    `;
    popover.setAttribute('aria-hidden', chatComposeState.popoverOpen ? 'false' : 'true');
}

function setAttachmentPopoverOpen(isOpen) {
    const popover = chatElements.attachmentPopover;
    const attachBtn = chatElements.attachBtn;
    if (!popover || !attachBtn) return;
    const shouldOpen = Boolean(isOpen) && chatComposeState.pendingAttachments.length > 0;
    chatComposeState.popoverOpen = shouldOpen;
    popover.classList.toggle('hidden', !shouldOpen);
    popover.setAttribute('aria-hidden', shouldOpen ? 'false' : 'true');
    attachBtn.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
}

function clearPendingAttachments() {
    chatComposeState.pendingAttachments = [];
    setAttachmentPopoverOpen(false);
    if (chatElements.attachInput) {
        chatElements.attachInput.value = '';
    }
    renderPendingAttachments();
}

function addPendingAttachments(fileList) {
    if (!fileList || !fileList.length) return;

    const existingKeys = new Set(
        chatComposeState.pendingAttachments.map(
            (item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`
        )
    );

    for (const file of Array.from(fileList)) {
        if (!file || !file.type || !file.type.startsWith('image/')) {
            continue;
        }
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (existingKeys.has(key)) {
            continue;
        }
        existingKeys.add(key);
        chatComposeState.pendingAttachments.push({ file, key });
    }
    renderPendingAttachments();
    if (chatComposeState.pendingAttachments.length > 0) {
        setAttachmentPopoverOpen(true);
    }
}

function openAttachmentPicker() {
    if (chatElements.attachInput) {
        chatElements.attachInput.click();
    }
}

function createClientSessionId(vault) {
    const safeVault = String(vault || 'chat').trim().replace(/[\s/\\]+/g, '_') || 'chat';
    const now = new Date();
    const pad = (value) => String(value).padStart(2, '0');
    const stamp = [
        now.getFullYear(),
        pad(now.getMonth() + 1),
        pad(now.getDate())
    ].join('') + '_' + [
        pad(now.getHours()),
        pad(now.getMinutes()),
        pad(now.getSeconds())
    ].join('');
    return `${safeVault}_${stamp}_${now.getMilliseconds()}_${Math.random().toString(36).slice(2, 6)}`;
}

function syncSendButtonState() {
    const btn = chatElements.sendBtn;
    if (!btn) return;

    btn.classList.toggle('chat-stop-btn', state.isLoading);
    btn.textContent = state.isLoading
        ? (state.isCancellingChat ? 'Stopping...' : 'Stop')
        : 'Send';
    btn.title = state.isLoading
        ? 'Stop the active response'
        : 'Send message';
    btn.setAttribute(
        'aria-label',
        state.isLoading ? 'Stop the active response' : 'Send message'
    );
    btn.disabled = state.isLoading && state.isCancellingChat;
}

function syncChatControlLocks() {
    if (!chatElements.vaultSelector) return;

    const lockVaultSelector = state.isLoading;
    chatElements.vaultSelector.disabled = lockVaultSelector;
    chatElements.vaultSelector.title = lockVaultSelector
        ? 'Vault is locked while a response is running.'
        : '';

    if (chatElements.toolDropdownTrigger) {
        chatElements.toolDropdownTrigger.disabled = state.isLoading;
    }
    if (chatElements.thinkingSelector) {
        chatElements.thinkingSelector.disabled = state.isLoading;
    }
    if (chatElements.sessionDropdownTrigger) {
        chatElements.sessionDropdownTrigger.disabled = state.isLoading;
    }
    if (chatElements.sessionSummaryTrigger) {
        chatElements.sessionSummaryTrigger.disabled = state.isLoading;
    }
    if (chatElements.sessionTitleInput) {
        chatElements.sessionTitleInput.disabled = state.isLoading;
    }
    if (chatElements.sessionTitleSave) {
        chatElements.sessionTitleSave.disabled = state.isLoading;
    }
    if (chatElements.sessionExportBtn) {
        chatElements.sessionExportBtn.disabled = state.isLoading || !state.sessionId;
    }
    if (chatElements.sessionDeleteBtn) {
        chatElements.sessionDeleteBtn.disabled = state.isLoading || !state.sessionId;
    }
    syncWorkspaceControlState();
    syncSendButtonState();
}

function syncWorkspaceControlState() {
    const input = chatElements.workspacePathInput;
    if (!input) return;

    const hasSession = Boolean(state.sessionId);
    const hasWorkspace = Boolean(input.value.trim());
    const locked = state.isLoading || (hasSession && hasWorkspace && !state.isWorkspaceUnlocked);

    input.disabled = locked;
    input.title = locked
        ? 'Workspace is locked for this session. Unlock to edit.'
        : '';

    if (chatElements.workspacePickerBtn) {
        chatElements.workspacePickerBtn.disabled = state.isLoading || (locked && !state.isWorkspaceUnlocked);
    }
    if (chatElements.workspaceUnlockBtn) {
        chatElements.workspaceUnlockBtn.classList.toggle('hidden', !(hasSession && hasWorkspace && locked));
        chatElements.workspaceUnlockBtn.disabled = state.isLoading;
    }
}

function currentWorkspacePath() {
    return (chatElements.workspacePathInput?.value || '').trim();
}

async function saveWorkspacePath() {
    const input = chatElements.workspacePathInput;
    const vault = chatElements.vaultSelector?.value || '';
    const sessionId = state.sessionId || '';
    if (!input || !vault || !sessionId || state.isLoading) return;

    const path = currentWorkspacePath();
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
        await fetchSessions(vault, sessionId);
    } catch (error) {
        console.error('Failed to save workspace path:', error);
        addChatErrorMessage(`Workspace not saved: ${error.message}`);
    } finally {
        syncWorkspaceControlState();
    }
}

function unlockWorkspacePath() {
    if (!chatElements.workspacePathInput || state.isLoading) return;
    const confirmed = window.confirm(
        'Unlock workspace editing for this session? Future turns will use the updated workspace path.'
    );
    if (!confirmed) return;
    state.isWorkspaceUnlocked = true;
    syncWorkspaceControlState();
    chatElements.workspacePathInput.focus();
}

function openWorkspacePickerModal() {
    if (!chatElements.workspacePathInput) return;
    const vault = chatElements.vaultSelector?.value || '';
    if (!vault) {
        alert('Select a vault before choosing a workspace.');
        return;
    }
    closeWorkspacePickerModal();

    const overlay = document.createElement('div');
    overlay.id = 'workspace-picker-modal';
    overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
    overlay.innerHTML = `
        <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="workspace-picker-modal-title">
            <div class="app-modal-header flex-none">
                <div class="app-modal-title-block">
                    <h2 id="workspace-picker-modal-title" class="text-lg font-semibold text-txt-primary">Workspace</h2>
                    <p class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(chatElements.vaultSelector?.value || 'No vault selected')}</p>
                </div>
                <div class="app-modal-actions">
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-workspace-picker-close>Close</button>
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
            closeWorkspacePickerModal();
            return;
        }
        const toggle = target.closest('[data-workspace-toggle]');
        if (toggle instanceof HTMLElement) {
            await toggleWorkspaceTreeNode(toggle);
            return;
        }
        const selectPath = target.closest('[data-workspace-select]')?.getAttribute('data-workspace-select');
        if (selectPath !== null && selectPath !== undefined) {
            chatElements.workspacePathInput.value = selectPath;
            state.isWorkspaceUnlocked = true;
            syncWorkspaceControlState();
            await saveWorkspacePath();
            closeWorkspacePickerModal();
        }
    });

    document.body.appendChild(overlay);
    loadWorkspaceDirectory(overlay).catch((error) => {
        const body = overlay.querySelector('#workspace-picker-body');
        if (body) {
            body.innerHTML = `<p class="state-error">Unable to load folders: ${escapeHtml(error.message)}</p>`;
        }
    });
}

function closeWorkspacePickerModal() {
    document.getElementById('workspace-picker-modal')?.remove();
}

async function loadWorkspaceDirectory(modal, path) {
    const body = modal.querySelector('#workspace-picker-body');
    const vault = chatElements.vaultSelector?.value || '';
    if (!body || !vault) return;

    body.innerHTML = '<div class="text-sm text-txt-secondary">Loading folders...</div>';
    const payload = await fetchWorkspaceDirectories(path || '');
    const directories = Array.isArray(payload.directories) ? payload.directories : [];
    const selectedPath = currentWorkspacePath();

    body.innerHTML = `
        <div class="space-y-3">
            <div class="p-3 rounded border border-border-primary bg-app-elevated">
                <div class="text-xs uppercase text-txt-secondary">Selected workspace</div>
                <div class="mt-1 text-sm cell-mono text-txt-primary">${escapeHtml(selectedPath || 'No workspace')}</div>
            </div>
            <div class="workspace-tree" role="tree">
                ${directories.length ? directories.map((directory) => renderWorkspaceDirectoryRow(directory, 0)).join('') : '<p class="text-sm text-txt-secondary">No folders available.</p>'}
            </div>
        </div>
    `;
}

async function fetchWorkspaceDirectories(path) {
    const vault = chatElements.vaultSelector?.value || '';
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

async function toggleWorkspaceTreeNode(toggle) {
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
        const payload = await fetchWorkspaceDirectories(path);
        const directories = Array.isArray(payload.directories) ? payload.directories : [];
        const depth = Number.parseInt(row.getAttribute('data-workspace-depth') || '0', 10) + 1;
        children.innerHTML = directories.length
            ? directories.map((directory) => renderWorkspaceDirectoryRow(directory, depth)).join('')
            : '<div class="py-1 text-xs text-txt-secondary">No child folders.</div>';
        children.dataset.loaded = 'true';
    } catch (error) {
        children.innerHTML = `<div class="py-1 text-xs state-error">Unable to load folders: ${escapeHtml(error.message)}</div>`;
    }
}

function renderWorkspaceDirectoryRow(directory, depth) {
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

function populateThinkingSelector() {
    if (!chatElements.thinkingSelector) return;
    const defaultThinking = state.metadata?.settings?.default_model_thinking || 'default';
    const allowed = new Set(Array.from(chatElements.thinkingSelector.options).map((option) => option.value));
    const selected = allowed.has(defaultThinking) ? defaultThinking : 'default';
    chatElements.thinkingSelector.value = selected;
}

function getSelectedToolNames() {
    return Array.from(chatElements.toolsCheckboxes?.querySelectorAll('input:checked') || [])
        .map((input) => input.value);
}

function updateToolDropdownSummary() {
    if (!chatElements.toolDropdownSummary) return;

    const selectedTools = getSelectedToolNames();
    if (selectedTools.length === 0) {
        chatElements.toolDropdownSummary.textContent = '(none selected)';
        return;
    }

    chatElements.toolDropdownSummary.textContent = `(${selectedTools.length} selected)`;
}

function setToolMenuOpen(open) {
    chatComposeState.toolMenuOpen = Boolean(open);
    if (chatElements.toolDropdown) {
        chatElements.toolDropdown.classList.toggle('open', chatComposeState.toolMenuOpen);
    }
    if (chatElements.toolDropdownMenu) {
        chatElements.toolDropdownMenu.classList.toggle('hidden', !chatComposeState.toolMenuOpen);
    }
    if (chatElements.toolDropdownTrigger) {
        chatElements.toolDropdownTrigger.setAttribute('aria-expanded', chatComposeState.toolMenuOpen ? 'true' : 'false');
    }
}

function setSessionMenuOpen(open) {
    chatComposeState.sessionMenuOpen = Boolean(open);
    if (!chatComposeState.sessionMenuOpen) {
        closeSessionSummaryPreview();
    }
    if (chatElements.sessionDropdown) {
        chatElements.sessionDropdown.classList.toggle('open', chatComposeState.sessionMenuOpen);
    }
    if (chatElements.sessionDropdownMenu) {
        chatElements.sessionDropdownMenu.classList.toggle('hidden', !chatComposeState.sessionMenuOpen);
    }
    if (chatElements.sessionDropdownTrigger) {
        chatElements.sessionDropdownTrigger.setAttribute('aria-expanded', chatComposeState.sessionMenuOpen ? 'true' : 'false');
    }
}

function sessionTitle(session) {
    if (!session || !session.session_id) {
        return 'New session';
    }
    const title = String(session.title || '').trim();
    return title || session.session_id;
}

function sessionActivityLabel(session) {
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

function formatSessionOptionLabel(session) {
    if (!session || !session.session_id) {
        return 'New session';
    }
    const meta = sessionActivityLabel(session);
    return meta ? `${sessionTitle(session)} (${meta})` : sessionTitle(session);
}

function sessionSummaryCacheKey(vault, sessionId) {
    return `${vault || ''}::${sessionId || ''}`;
}

function selectedSessionWithSummary() {
    if (!state.sessionId) return null;
    const session = state.sessions.find((item) => item.session_id === state.sessionId);
    return session?.has_summary ? session : null;
}

function renderSessionSelector() {
    if (!chatElements.sessionDropdownMenu || !chatElements.sessionDropdownLabel) return;

    const activeSession = state.sessions.find((session) => session.session_id === state.sessionId) || null;
    const activeMeta = sessionActivityLabel(activeSession);
    chatElements.sessionDropdownLabel.innerHTML = `
        <span class="session-dropdown-title">${escapeHtml(sessionTitle(activeSession))}</span>
        ${activeMeta ? `<span class="session-dropdown-meta">${escapeHtml(activeMeta)}</span>` : ''}
    `;

    const rows = [
        renderSessionDropdownRow(null, !activeSession),
        ...state.sessions.map((session) => renderSessionDropdownRow(session, session.session_id === state.sessionId)),
    ];
    chatElements.sessionDropdownMenu.innerHTML = rows.join('');
    updateSessionSummaryTrigger();
}

function renderSessionDropdownRow(session, isActive) {
    const sessionId = session?.session_id || '';
    const hasSummary = Boolean(session?.has_summary);
    const meta = sessionActivityLabel(session);
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
                        <span class="session-dropdown-title">${escapeHtml(sessionTitle(session))}</span>
                        ${marker}
                    </span>
                    ${meta ? `<span class="session-dropdown-meta">${escapeHtml(meta)}</span>` : ''}
                </span>
            </button>
        </div>
    `;
}

function updateSessionSummaryTrigger() {
    if (!chatElements.sessionSummaryTrigger) return;
    const session = selectedSessionWithSummary();
    if (!session) {
        chatElements.sessionSummaryTrigger.classList.remove('is-visible');
        chatElements.sessionSummaryTrigger.setAttribute('aria-hidden', 'true');
        return;
    }
    chatElements.sessionSummaryTrigger.classList.add('is-visible');
    chatElements.sessionSummaryTrigger.removeAttribute('aria-hidden');
}

async function selectSessionFromDropdown(sessionId) {
    setSessionMenuOpen(false);
    if (!sessionId) {
        await clearSession(false);
    } else {
        await loadSession(sessionId);
    }
}

async function fetchSessionSummaryPreview(session) {
    if (!session) return null;

    const vault = chatElements.vaultSelector?.value || '';
    const cacheKey = sessionSummaryCacheKey(vault, session.session_id);
    const cached = state.sessionSummaryPreviewCache[cacheKey];
    if (cached) {
        return cached;
    }
    if (state.sessionSummaryPreviewInFlight[cacheKey]) {
        return state.sessionSummaryPreviewInFlight[cacheKey];
    }

    state.sessionSummaryPreviewInFlight[cacheKey] = (async () => {
        const response = await fetch(
            `api/chat/sessions/${encodeURIComponent(session.session_id)}/summary?vault_name=${encodeURIComponent(vault)}`
        );
        if (!response.ok) {
            throw new Error('Failed to fetch session summary');
        }
        const data = await response.json();
        state.sessionSummaryPreviewCache[cacheKey] = data;
        return data;
    })();

    try {
        return await state.sessionSummaryPreviewInFlight[cacheKey];
    } finally {
        delete state.sessionSummaryPreviewInFlight[cacheKey];
    }
}

async function warmSessionSummaryPreview(session) {
    try {
        await fetchSessionSummaryPreview(session);
    } catch (error) {
        console.error('Error fetching session summary preview:', error);
    }
}

function renderSessionSummaryPreview(summary) {
    if (!summary?.has_summary) {
        return '<p class="session-summary-preview-text text-txt-secondary">No summary record found.</p>';
    }
    const rawSummaryText = String(summary.summary || summary.user_intent || '').trim();
    const summaryText = rawSummaryText
        ? truncateText(rawSummaryText, 520)
        : 'No summary text captured.';
    const workspacePath = String(summary.workspace_path || '').trim();
    return `
        <div class="session-summary-preview-title">Session Summary</div>
        <div class="session-summary-preview-text">${escapeHtml(summaryText)}</div>
        <div class="session-summary-preview-workspace">
            <span class="font-semibold text-txt-primary">Workspace:</span>
            ${escapeHtml(workspacePath || 'Not set')}
        </div>
    `;
}

function positionSessionSummaryPreview(popover, anchor) {
    const anchorRect = anchor.getBoundingClientRect();
    const margin = 8;
    const popoverRect = popover.getBoundingClientRect();
    let left = anchorRect.right + margin;
    let top = anchorRect.top;
    if (left + popoverRect.width > window.innerWidth - margin) {
        left = anchorRect.left - popoverRect.width - margin;
    }
    if (left < margin) {
        left = margin;
    }
    if (top + popoverRect.height > window.innerHeight - margin) {
        top = window.innerHeight - popoverRect.height - margin;
    }
    if (top < margin) {
        top = margin;
    }
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
}

function closeSessionSummaryPreview() {
    document.getElementById('session-summary-preview-popover')?.remove();
}

async function openSessionSummaryPreview(anchor, session) {
    if (!anchor || !session) return;
    closeSessionSummaryPreview();
    const popover = document.createElement('div');
    popover.id = 'session-summary-preview-popover';
    popover.className = 'session-summary-preview-popover';
    popover.innerHTML = '<p class="session-summary-preview-text text-txt-secondary">Loading summary...</p>';
    document.body.appendChild(popover);
    positionSessionSummaryPreview(popover, anchor);
    try {
        const summary = await fetchSessionSummaryPreview(session);
        if (!document.body.contains(popover)) return;
        popover.innerHTML = renderSessionSummaryPreview(summary);
        positionSessionSummaryPreview(popover, anchor);
    } catch (error) {
        console.error('Error fetching session summary preview:', error);
        if (document.body.contains(popover)) {
            popover.innerHTML = '<p class="session-summary-preview-text state-error">Unable to load summary preview.</p>';
            positionSessionSummaryPreview(popover, anchor);
        }
    }
}

function renderSessionSummaryDetails(summary) {
    const fields = sessionSummaryEditableFields();
    const artifacts = Array.isArray(summary.artifacts) ? summary.artifacts : [];
    const metadata = summary.metadata && typeof summary.metadata === 'object' ? summary.metadata : {};
    return `
        <div class="space-y-4">
            <div class="state-surface-warning p-3 rounded border text-sm">
                Manual edits update this derived session summary only. If this chat session is continued later, session summarization may replace these edits.
            </div>
            ${fields.map(field => renderSessionSummaryReadonlyField(summary, field)).join('')}
            <div>
                <p class="font-semibold text-txt-primary">Artifacts</p>
                ${artifacts.length
                    ? `<ul class="mt-1 list-disc list-inside text-sm text-txt-primary">${artifacts.map(artifact => `<li><span class="cell-mono">${escapeHtml(artifact.path || '')}</span>${artifact.artifact_role ? ` <span class="text-txt-secondary">(${escapeHtml(artifact.artifact_role)})</span>` : ''}</li>`).join('')}</ul>`
                    : '<p class="text-sm text-txt-secondary">No artifacts linked.</p>'}
            </div>
            <div>
                <p class="font-semibold text-txt-primary">Metadata</p>
                ${renderSessionSummaryVectorIndex(summary.vector_index)}
                <pre class="mt-1 whitespace-pre-wrap rounded-md border border-border-primary bg-app-bg p-3 text-xs text-txt-secondary">${escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
            </div>
            <div class="text-xs text-txt-secondary">
                Created ${escapeHtml(formatShortDate(summary.created_at || ''))} · Updated ${escapeHtml(formatShortDate(summary.updated_at || ''))}
            </div>
        </div>
    `;
}

function renderSessionSummaryVectorIndex(vectorIndex) {
    const status = vectorIndex && typeof vectorIndex === 'object' ? vectorIndex : {};
    const indexedFields = Number(status.indexed_fields || 0);
    const expectedFields = Number(status.expected_fields || 0);
    const indexedTypes = Array.isArray(status.indexed_field_types) ? status.indexed_field_types : [];
    const missingTypes = Array.isArray(status.missing_field_types) ? status.missing_field_types : [];
    const detail = [
        indexedTypes.length ? `indexed: ${indexedTypes.join(', ')}` : '',
        missingTypes.length ? `missing: ${missingTypes.join(', ')}` : '',
    ].filter(Boolean).join(' · ');
    return `
        <div class="mt-1 mb-2 rounded-md border border-border-primary bg-app-bg p-2 text-xs text-txt-secondary">
            <span class="font-semibold text-txt-primary">Vector index:</span>
            ${escapeHtml(String(indexedFields))}/${escapeHtml(String(expectedFields))} fields
            ${detail ? `<span class="block mt-1">${escapeHtml(detail)}</span>` : ''}
        </div>
    `;
}

function sessionSummaryEditableFields() {
    return [
        { key: 'summary', label: 'Summary', rows: 6 },
        { key: 'user_intent', label: 'User Intent', rows: 3 },
        { key: 'domain', label: 'Domain', rows: 2 },
        { key: 'work_product', label: 'Work Product', rows: 2 },
        { key: 'workspace_path', label: 'Workspace', rows: 2 },
        { key: 'named_entities', label: 'Named Entities', rows: 2 },
        { key: 'source_summary', label: 'Source Summary', rows: 6 },
    ];
}

function renderSessionSummaryReadonlyField(summary, field) {
    const value = String(summary?.[field.key] || '').trim();
    return `
        <div>
            <p class="font-semibold text-txt-primary">${escapeHtml(field.label)}</p>
            ${value
                ? `<p class="text-sm text-txt-primary whitespace-pre-wrap">${escapeHtml(value)}</p>`
                : '<p class="text-sm text-txt-secondary">Not captured.</p>'}
        </div>
    `;
}

function renderSessionSummaryEditForm(summary) {
    return `
        <div class="space-y-4">
            <div class="state-surface-warning p-3 rounded border text-sm">
                Manual edits update this derived session summary only. If this chat session is continued later, session summarization may replace these edits.
            </div>
            ${sessionSummaryEditableFields().map(field => `
                <label class="block">
                    <span class="font-semibold text-txt-primary">${escapeHtml(field.label)}</span>
                    <textarea
                        data-session-summary-field="${escapeHtml(field.key)}"
                        rows="${field.rows}"
                        class="mt-1 w-full px-3 py-2 border border-border-secondary rounded-md bg-app-bg text-txt-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                    >${escapeHtml(summary?.[field.key] || '')}</textarea>
                </label>
            `).join('')}
            <div>
                <p class="font-semibold text-txt-primary">Metadata</p>
                <pre class="mt-1 whitespace-pre-wrap rounded-md border border-border-primary bg-app-bg p-3 text-xs text-txt-secondary">${escapeHtml(JSON.stringify(summary?.metadata || {}, null, 2))}</pre>
            </div>
        </div>
    `;
}

async function openSessionSummaryModalForSession(session) {
    if (!session) return;

    closeSessionSummaryModal();
    const popover = document.createElement('div');
    popover.id = 'session-summary-modal';
    popover.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
    popover.innerHTML = `
        <div class="absolute inset-0" data-session-summary-close="true"></div>
        <section class="app-modal-panel relative overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="session-summary-modal-title">
            <div class="app-modal-header sticky top-0">
                <div class="app-modal-title-block">
                    <h2 id="session-summary-modal-title" class="text-lg font-semibold text-txt-primary inline-flex items-center gap-2">
                        <span class="session-summary-title-icon" aria-hidden="true">${SESSION_SUMMARY_ICON_SVG}</span>
                        <span>Session Summary</span>
                    </h2>
                    <p class="mt-1 text-xs text-txt-secondary cell-mono">${escapeHtml(session.session_id)}</p>
                </div>
                <div class="app-modal-actions">
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-state-error rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-state-error" data-session-summary-delete="true">
                        Delete Summary
                    </button>
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-session-summary-edit="true">
                        Edit
                    </button>
                    <button type="button" class="hidden px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-70 disabled:cursor-not-allowed" data-session-summary-save="true">
                        Save
                    </button>
                    <button type="button" class="hidden px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-session-summary-cancel-edit="true">
                        Cancel
                    </button>
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-session-summary-close="true">
                        Close
                    </button>
                </div>
            </div>
            <div id="session-summary-modal-body" class="p-4 text-sm text-txt-primary">
                <p class="text-txt-secondary">Loading summary details...</p>
            </div>
        </section>
    `;
    popover.addEventListener('click', (event) => {
        const target = event.target;
        if (target instanceof HTMLElement && target.dataset.sessionSummaryClose === 'true') {
            closeSessionSummaryModal();
            return;
        }
        if (target instanceof HTMLElement && target.dataset.sessionSummaryEdit === 'true') {
            const summary = currentSessionSummaryFromModal();
            setSessionSummaryModalEditing(popover, summary);
            return;
        }
        if (target instanceof HTMLElement && target.dataset.sessionSummarySave === 'true') {
            saveSessionSummaryModal(popover, target);
            return;
        }
        if (target instanceof HTMLElement && target.dataset.sessionSummaryCancelEdit === 'true') {
            cancelSessionSummaryEdit(popover);
            return;
        }
        if (target instanceof HTMLElement && target.dataset.sessionSummaryDelete === 'true') {
            deleteSessionSummaryFromModal(popover, target);
        }
    });
    document.body.appendChild(popover);

    const body = popover.querySelector('#session-summary-modal-body');
    try {
        const summary = await fetchSessionSummaryPreview(session);
        if (!body) return;
        popover._sessionSummary = summary;
        body.innerHTML = summary?.has_summary
            ? renderSessionSummaryDetails(summary)
            : '<p class="text-sm text-txt-secondary">No summary record found for this session.</p>';
    } catch (error) {
        console.error('Error opening session summary modal:', error);
        if (body) {
            body.innerHTML = '<p class="text-sm state-error">Unable to load summary details.</p>';
        }
    }
}

function closeSessionSummaryModal() {
    document.getElementById('session-summary-modal')?.remove();
}

function currentSessionSummaryFromModal() {
    return document.getElementById('session-summary-modal')?._sessionSummary || null;
}

function setSessionSummaryModalEditing(modal, summary) {
    const body = modal.querySelector('#session-summary-modal-body');
    const editButton = modal.querySelector('[data-session-summary-edit]');
    const saveButton = modal.querySelector('[data-session-summary-save]');
    const cancelButton = modal.querySelector('[data-session-summary-cancel-edit]');
    if (body) {
        body.innerHTML = renderSessionSummaryEditForm(summary);
    }
    editButton?.classList.add('hidden');
    saveButton?.classList.remove('hidden');
    cancelButton?.classList.remove('hidden');
}

function setSessionSummaryModalReadonly(modal, summary) {
    const body = modal.querySelector('#session-summary-modal-body');
    const editButton = modal.querySelector('[data-session-summary-edit]');
    const saveButton = modal.querySelector('[data-session-summary-save]');
    const cancelButton = modal.querySelector('[data-session-summary-cancel-edit]');
    if (body) {
        body.innerHTML = summary?.has_summary
            ? renderSessionSummaryDetails(summary)
            : '<p class="text-sm text-txt-secondary">No summary record found for this session.</p>';
    }
    editButton?.classList.remove('hidden');
    saveButton?.classList.add('hidden');
    cancelButton?.classList.add('hidden');
}

function cancelSessionSummaryEdit(modal) {
    setSessionSummaryModalReadonly(modal, currentSessionSummaryFromModal());
}

async function saveSessionSummaryModal(modal, triggerButton) {
    const vault = chatElements.vaultSelector?.value || '';
    const existing = currentSessionSummaryFromModal();
    const sessionId = existing?.session_id || '';
    if (!sessionId || !vault) return;
    triggerButton.disabled = true;
    triggerButton.textContent = 'Saving...';
    const payload = {};
    sessionSummaryEditableFields().forEach(field => {
        const input = modal.querySelector(`[data-session-summary-field="${field.key}"]`);
        payload[field.key] = input ? input.value : '';
    });
    payload.metadata = existing?.metadata || {};
    try {
        const response = await fetch(
            `api/chat/sessions/${encodeURIComponent(sessionId)}/summary?vault_name=${encodeURIComponent(vault)}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
        const summary = await response.json();
        const cacheKey = sessionSummaryCacheKey(vault, sessionId);
        state.sessionSummaryPreviewCache[cacheKey] = summary;
        modal._sessionSummary = summary;
        renderSessionSelector();
        setSessionSummaryModalReadonly(modal, summary);
    } catch (error) {
        console.error('Error saving session summary:', error);
        const body = modal.querySelector('#session-summary-modal-body');
        if (body) {
            body.insertAdjacentHTML('afterbegin', `<p class="mb-3 state-error">Unable to save summary: ${escapeHtml(error.message)}</p>`);
        }
    } finally {
        triggerButton.disabled = false;
        triggerButton.textContent = 'Save';
    }
}

async function deleteSessionSummaryFromModal(modal, triggerButton) {
    const vault = chatElements.vaultSelector?.value || '';
    const summary = currentSessionSummaryFromModal();
    const sessionId = summary?.session_id || '';
    if (!sessionId || !vault) return;
    const confirmed = window.confirm('Delete this derived summary record? The chat session will not be deleted.');
    if (!confirmed) return;
    triggerButton.disabled = true;
    triggerButton.textContent = 'Deleting...';
    try {
        const response = await fetch(
            `api/chat/sessions/${encodeURIComponent(sessionId)}/summary?vault_name=${encodeURIComponent(vault)}`,
            { method: 'DELETE' }
        );
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
        delete state.sessionSummaryPreviewCache[sessionSummaryCacheKey(vault, sessionId)];
        closeSessionSummaryModal();
        await fetchSessions(vault, state.sessionId || sessionId);
    } catch (error) {
        console.error('Error deleting session summary:', error);
        const body = modal.querySelector('#session-summary-modal-body');
        if (body) {
            body.insertAdjacentHTML('afterbegin', `<p class="mb-3 state-error">Unable to delete summary: ${escapeHtml(error.message)}</p>`);
        }
        triggerButton.disabled = false;
        triggerButton.textContent = 'Delete Summary';
    }
}

function renderCompactionProgress(status) {
    const fill = chatElements.compactionFill;
    const track = chatElements.compactionTrack;
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
    const vault = chatElements.vaultSelector?.value || '';
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

async function fetchSessions(vault, preferredSessionId = '') {
    state.sessions = [];
    renderSessionSelector();
    if (!vault) {
        clearCompactionProgress();
        return;
    }
    try {
        const response = await fetch(`api/chat/sessions?vault_name=${encodeURIComponent(vault)}`);
        if (!response.ok) {
            throw new Error('Failed to fetch chat sessions');
        }
        state.sessions = await response.json();
        renderSessionSelector();
        if (preferredSessionId && state.sessions.some((session) => session.session_id === preferredSessionId)) {
            state.sessionId = preferredSessionId;
            renderSessionSelector();
        }
        await refreshCompactionProgress();
    } catch (error) {
        console.error('Error fetching chat sessions:', error);
    }
}

async function loadSession(sessionId) {
    const vault = chatElements.vaultSelector?.value || '';
    if (!vault || !sessionId) {
        return;
    }
    try {
        state.sessionId = sessionId;
        renderSessionSelector();
        refreshCompactionProgress();
        state.isLoading = true;
        syncChatControlLocks();
        const response = await fetch(
            `api/chat/sessions/${encodeURIComponent(sessionId)}?vault_name=${encodeURIComponent(vault)}`
        );
        if (!response.ok) {
            throw new Error('Failed to load chat session');
        }
        const payload = await response.json();
        state.sessionId = payload.session_id || sessionId;
        state.isWorkspaceUnlocked = false;
        if (chatElements.workspacePathInput) {
            chatElements.workspacePathInput.value = payload.workspace?.path || '';
        }
        renderPersistedSession(payload);
        renderSessionSelector();
        updateSessionTitleRow();
        updateStatus();
        await refreshCompactionProgress();
    } catch (error) {
        console.error('Error loading chat session:', error);
        addChatErrorMessage(error.message);
    } finally {
        state.isLoading = false;
        syncChatControlLocks();
    }
}

function renderPersistedSession(payload) {
    chatElements.chatMessages.innerHTML = '';

    const messages = Array.isArray(payload?.messages) ? payload.messages : [];
    const toolEventsQueue = Array.isArray(payload?.tool_events) ? [...payload.tool_events] : [];
    const pendingToolEvents = [];

    if (messages.length === 0) {
        renderChatEmptyState('Selected session has no persisted messages.');
        return;
    }

    messages.forEach((message) => {
        if (message.is_tool_message) {
            const nextToolEvent = toolEventsQueue.shift();
            if (nextToolEvent) {
                pendingToolEvents.push(nextToolEvent);
            }
            return;
        }

        if (message.role === 'assistant') {
            const assistantToolEvents = pendingToolEvents.splice(0, pendingToolEvents.length);
            renderPersistedAssistantMessage(message.content || '', assistantToolEvents, {
                sequenceIndex: message.sequence_index
            });
            return;
        }

        addMessage('user', message.content || '', {
            sequenceIndex: message.sequence_index
        });
    });

    if (pendingToolEvents.length > 0) {
        renderPersistedAssistantMessage('', pendingToolEvents.splice(0, pendingToolEvents.length));
    }
}

function renderPersistedAssistantMessage(content, toolEvents, options = {}) {
    const context = createAssistantStreamingMessage();
    context.fullText = content || '';
    context.sequenceIndex = Number.isInteger(options.sequenceIndex) ? options.sequenceIndex : null;
    renderAssistantMarkdown(context, { finalize: true });
    hydratePersistedToolEvents(context, toolEvents);
    finalizeAssistantMessage(context, {
        sessionId: state.sessionId || 'unknown',
        messageCount: 1,
        toolCount: Array.isArray(toolEvents) ? toolEvents.length : 0,
        status: 'done'
    });
}

function hydratePersistedToolEvents(context, toolEvents) {
    if (!context || !Array.isArray(toolEvents) || toolEvents.length === 0) {
        return;
    }

    toolEvents.forEach((event) => {
        if (!event || !event.tool_call_id) {
            return;
        }

        let entry = context.toolStatusMap.get(event.tool_call_id);
        if (!entry) {
            ensureToolCallsSection(context);
            entry = createToolStatusEntry(context, event.tool_call_id, {
                tool_name: event.tool_name,
                arguments: event.args || null
            });
        }

        entry.container.classList.remove('tool-status-running');
        entry.container.classList.add('tool-status-complete');

        if (event.args) {
            entry.args = event.args;
        }

        if (event.event_type !== 'call') {
            const resultPayload = {};
            if (event.result_text) {
                resultPayload.text = event.result_text;
            }
            if (event.artifact_ref) {
                resultPayload.artifact_ref = event.artifact_ref;
            }
            if (event.result_metadata && Object.keys(event.result_metadata).length > 0) {
                resultPayload.metadata = event.result_metadata;
            }
            entry.result = Object.keys(resultPayload).length > 0 ? resultPayload : event.event_type;
        }

        updateToolDetail(entry);
        entry.chevron.textContent = entry.container.open ? '▾' : '▸';
    });

    updateToolCallsSummary(context);
}

// Tab management
const tabs = {
    chat: {
        button: document.getElementById('chat-tab'),
        content: document.getElementById('chat-content')
    },
    dashboard: {
        button: document.getElementById('dashboard-tab'),
        content: document.getElementById('dashboard-content')
    },
    configuration: {
        button: document.getElementById('configuration-tab'),
        content: document.getElementById('configuration-content')
    }
};

// Theme management
const themeManager = {
    themes: [
        { name: 'light', label: 'Light' },
        { name: 'dark', label: 'Dark' },
        { name: 'ocean', label: 'Ocean' },
        { name: 'sunset', label: 'Sunset' },
        { name: 'lavender', label: 'Lavender' },
        { name: 'forest', label: 'Forest' }
    ],

    current: null,

    safeGet(key) {
        try {
            return localStorage.getItem(key);
        } catch {
            return null;
        }
    },

    safeSet(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch {
            // Ignore storage errors (e.g., private mode) but keep UI responsive
        }
    },

    init() {
        const saved = this.safeGet('theme');
        let initialTheme = saved;

        if (!saved) {
            // No saved preference - check system preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            initialTheme = prefersDark ? 'dark' : 'light';
        }

        this.apply(initialTheme);

        // Set up click handler
        const button = document.getElementById('theme-toggle');
        if (button) {
            button.addEventListener('click', () => this.cycle());
        }
    },

    apply(themeName) {
        const theme = this.themes.find(t => t.name === themeName) || this.themes[0];
        this.current = theme;

        // Update DOM
        document.documentElement.setAttribute('data-theme', theme.name);

        // Update button title
        const button = document.getElementById('theme-toggle');
        if (button) {
            button.title = `Theme: ${theme.label} (click to change)`;
        }

        // Save preference (best-effort)
        this.safeSet('theme', theme.name);
    },

    cycle() {
        const currentIndex = this.themes.findIndex(t => t.name === this.current?.name);
        const nextIndex = (currentIndex + 1) % this.themes.length;
        this.apply(this.themes[nextIndex].name);
    }
};

// Initialize app
async function init() {
    themeManager.init();
    setupTabs();
    setupEventListeners();
    restoreChatComposerHeight();
    syncChatFocusToggle();
    if (window.ConfigurationPanel) {
        window.ConfigurationPanel.init({
            refreshMetadata: () => fetchMetadata(),
            refreshStatus: () => fetchSystemStatus()
        });
    }
    await fetchMetadata();
    await fetchSystemStatus();
    renderPendingAttachments();
    updateCollapsibleArrows();
}

// Setup tab switching
function setupTabs() {
    Object.entries(tabs).forEach(([name, tabControls]) => {
        if (tabControls.button) {
            tabControls.button.addEventListener('click', () => switchTab(name));
        } else {
            console.error(`Tab button not found for ${name}`, tabControls);
        }
    });
}

function switchTab(tabName) {
    Object.entries(tabs).forEach(([name, tabControls]) => {
        if (!tabControls.button || !tabControls.content) return;

        const isActive = name === tabName;
        tabControls.button.classList.toggle('border-accent', isActive);
        tabControls.button.classList.toggle('text-accent', isActive);
        tabControls.button.classList.toggle('border-transparent', !isActive);
        tabControls.button.classList.toggle('text-txt-secondary', !isActive);
        tabControls.content.classList.toggle('hidden', !isActive);
    });

    if (tabName === 'dashboard') {
        fetchSystemStatus();
        if (window.ConfigurationPanel) {
            window.ConfigurationPanel.onDashboardActivated();
        }
    } else if (tabName === 'configuration') {
        fetchSystemStatus();
        if (window.ConfigurationPanel) {
            window.ConfigurationPanel.onTabActivated();
        }
    }
}

// Update collapsible section arrows (placeholder)
function updateCollapsibleArrows() {}

function getConfigurationWarnings() {
    const status = state.systemStatus;
    if (!status || !status.configuration_status) return [];
    const issues = status.configuration_status.issues || [];
    return issues.filter((issue) => {
        const severity = (issue.severity || '').toLowerCase();
        if (severity !== 'warning' && severity !== 'error') {
            return false;
        }
        const name = issue.name || '';
        if (name.startsWith('model:') || name.startsWith('tool:')) {
            return false;
        }
        return true;
    });
}

// Fetch metadata from API
async function fetchMetadata() {
    try {
        const response = await fetch('api/metadata');
        if (!response.ok) throw new Error('Failed to fetch metadata');

        state.metadata = await response.json();
        // Expose for other modules (e.g., configuration import panel) to avoid duplicate fetches.
        window.App = window.App || {};
        window.App.metadata = state.metadata;
        populateSelectors();
        updateStatus();
    } catch (error) {
        console.error('Error fetching metadata:', error);
        // Connection failure - could add a warning here if needed
        updateStatus();
    }
}

// Populate selectors with metadata
function populateSelectors() {
    const previousVault = chatElements.vaultSelector?.value || '';
    const previousModel = chatElements.modelSelector?.value || '';
    const previousTemplate = chatElements.templateSelector?.value || '';
    const previousTools = new Set(getSelectedToolNames());
    const configuredDefaultTools = new Set(
        Array.isArray(state.metadata?.settings?.default_chat_tools)
            ? state.metadata.settings.default_chat_tools
            : []
    );

    chatElements.vaultSelector.innerHTML = '<option value="">Select vault...</option>';
    chatElements.modelSelector.innerHTML = '<option value="">Select model...</option>';
    chatElements.toolsCheckboxes.innerHTML = '';
    if (chatElements.templateSelector) {
        chatElements.templateSelector.innerHTML = '<option value="">Select template...</option>';
        chatElements.templateSelector.disabled = true;
    }
    populateThinkingSelector();

    state.metadata.vaults.forEach(vault => {
        const option = document.createElement('option');
        option.value = vault;
        option.textContent = vault;
        chatElements.vaultSelector.appendChild(option);
    });

    if (previousVault && state.metadata.vaults.includes(previousVault)) {
        chatElements.vaultSelector.value = previousVault;
    }

    let firstAvailableModel = null;
    const envDefaultModel = state.systemStatus && state.systemStatus.configuration_status
        ? state.systemStatus.configuration_status.default_model
        : null;

    const chatModels = state.metadata.models.filter(isChatSelectableModel);

    chatModels.forEach(model => {
        const option = document.createElement('option');
        option.value = model.name;
        const displayModelName = model.model_string || model.model || model.provider;
        option.textContent = `${model.name} (${displayModelName})${model.available ? '' : ' (unavailable)'}`;
        option.disabled = model.available === false;
        chatElements.modelSelector.appendChild(option);

        if (model.available && !firstAvailableModel) {
            firstAvailableModel = model.name;
        }
    });

    if (
        previousModel &&
        chatModels.some(m => m.name === previousModel && m.available !== false)
    ) {
        chatElements.modelSelector.value = previousModel;
    } else if (envDefaultModel && chatModels.some(m => m.name === envDefaultModel && m.available)) {
        chatElements.modelSelector.value = envDefaultModel;
    } else if (firstAvailableModel) {
        chatElements.modelSelector.value = firstAvailableModel;
    }

    // Trigger template fetch if a vault is already selected (e.g., persisted UI state in future)
    if (chatElements.vaultSelector && chatElements.vaultSelector.value) {
        fetchTemplates(chatElements.vaultSelector.value, previousTemplate);
        fetchSessions(chatElements.vaultSelector.value, state.sessionId || '');
    }

    const toolMap = new Map(state.metadata.tools.map(tool => [tool.name, tool]));
    const handledTools = new Set();

    const createToolElement = (tool) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'tool-checkbox-wrapper';

        const label = document.createElement('label');
        label.htmlFor = `tool-${tool.name}`;

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `tool-${tool.name}`;
        checkbox.value = tool.name;
        checkbox.disabled = tool.available === false;

        if (!checkbox.disabled) {
            if (previousTools.size > 0) {
                checkbox.checked = previousTools.has(tool.name);
            } else {
                checkbox.checked = configuredDefaultTools.has(tool.name);
            }
        }

        const nameSpan = document.createElement('span');
        nameSpan.className = 'tool-checkbox-name';
        nameSpan.textContent = `${tool.name}${checkbox.disabled ? ' (unavailable)' : ''}`;
        label.appendChild(checkbox);
        label.appendChild(nameSpan);

        wrapper.appendChild(label);
        return wrapper;
    };

    const toolOrder = [
        'web_search_duckduckgo',
        'web_search_tavily',
        'browser',
        'session_ops',
        'file_ops_safe',
        'file_ops_unsafe',
        'tavily_extract',
        'tavily_crawl',
        'code_execution'
    ];

    toolOrder.forEach(name => {
        const tool = toolMap.get(name);
        if (!tool) return;
        chatElements.toolsCheckboxes.appendChild(createToolElement(tool));
        handledTools.add(name);
    });

    state.metadata.tools.forEach(tool => {
        if (handledTools.has(tool.name)) {
            return;
        }
        chatElements.toolsCheckboxes.appendChild(createToolElement(tool));
    });

    updateToolDropdownSummary();
    renderSessionSelector();
    syncChatControlLocks();
}

function isChatSelectableModel(model) {
    const capabilities = Array.isArray(model?.capabilities)
        ? model.capabilities.map(capability => String(capability || '').trim().toLowerCase())
        : [];
    return !capabilities.includes('embedding');
}

// Fetch system status
async function fetchSystemStatus() {
    try {
        const response = await fetch('api/status');
        if (!response.ok) throw new Error('Failed to fetch status');

        state.systemStatus = await response.json();
        const envDefaultModel = state.systemStatus && state.systemStatus.configuration_status
            ? state.systemStatus.configuration_status.default_model
            : null;
        if (envDefaultModel && state.metadata && chatElements.modelSelector) {
            const availableModels = state.metadata.models
                .filter(isChatSelectableModel)
                .filter(m => m.available !== false);
            const firstAvailableModel = availableModels.length ? availableModels[0].name : null;
            const currentValue = chatElements.modelSelector.value;
            const hasEnvDefault = availableModels.some(m => m.name === envDefaultModel);
            if (hasEnvDefault && (!currentValue || currentValue === firstAvailableModel)) {
                chatElements.modelSelector.value = envDefaultModel;
            }
        }
        syncRestartFlagWithStorage();
        await fetchWorkflowTasks({ render: false });
        displaySystemStatus();
        updateStatus();
    } catch (error) {
        console.error('Error fetching status:', error);
        dashElements.systemStatus.innerHTML = '<p class="state-error text-sm">Failed to fetch system status</p>';
        if (dashElements.workflowsStatus) {
            dashElements.workflowsStatus.innerHTML = '<p class="state-error text-sm">Failed to fetch workflow status</p>';
        }
        if (dashElements.vaultActivityStatus) {
            dashElements.vaultActivityStatus.innerHTML = '<p class="state-error text-sm">Failed to fetch AssistantMD activity</p>';
        }
    }
}

async function fetchWorkflowTasks({ render = true } = {}) {
    try {
        const response = await fetch('api/tasks?kind=workflow&include_terminal=false');
        if (!response.ok) throw new Error('Failed to fetch workflow tasks');
        const data = await response.json();
        state.workflowTasks = data.tasks || [];
        syncWorkflowTaskPolling();
        if (render) {
            displaySystemStatus();
        }
    } catch (error) {
        console.error('Error fetching workflow tasks:', error);
        state.workflowTasks = [];
        syncWorkflowTaskPolling();
        if (render && dashElements.executeWorkflowResult) {
            dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
        }
    }
}

// Display system status information
function displaySystemStatus() {
    const status = state.systemStatus;
    if (!status) return;
    renderDashboardVaults(status);
    renderDashboardWorkflows(status);
    renderDashboardVaultActivity(status);
}

function renderDashboardVaults(status) {
    if (!dashElements.systemStatus) return;
    const sortedVaults = sortDashboardVaults(status.vaults || []);

    dashElements.systemStatus.innerHTML = `
        <div class="dashboard-table-wrap" role="region" aria-label="Vaults" tabindex="0">
            <table class="dashboard-table">
                <thead>
                    <tr>
                        ${renderDashboardVaultSortHeader('name', 'Name')}
                        ${renderDashboardVaultSortHeader('path', 'Path inside container')}
                        ${renderDashboardVaultSortHeader('workflows', 'Workflows', 'cell-center')}
                        ${renderDashboardVaultSortHeader('files', 'Files', 'cell-center')}
                        ${renderDashboardVaultSortHeader('file_delta', '+/- 7d', 'cell-center')}
                        ${renderDashboardVaultSortHeader('latest_change', 'Latest Change')}
                    </tr>
                </thead>
                <tbody>
                    ${sortedVaults.map(v => `
                        <tr>
                            <td><strong>${escapeHtml(v.name)}</strong></td>
                            <td class="cell-mono cell-xs subtle">${escapeHtml(v.path)}</td>
                            <td class="cell-center">${v.workflow_count}</td>
                            <td class="cell-center">${v.tracked_files ?? '—'}</td>
                            <td class="cell-center">${formatVaultFileDelta(v)}</td>
                            <td class="cell-xs">${formatShortDate(v.latest_vault_change_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderDashboardWorkflows(status) {
    if (!dashElements.workflowsStatus) return;
    const enabledWorkflows = status.enabled_workflows || [];
    const disabledWorkflows = status.disabled_workflows || [];
    const systemWorkflowTemplates = status.system_workflow_templates || [];
    const templateWorkflows = systemWorkflowTemplates.map(template => ({
        global_id: `system/${template.name}`,
        name: template.name,
        vault: 'system',
        enabled: Boolean(template.enabled),
        run_type: template.run_type || 'workflow',
        schedule_cron: template.schedule_cron || '',
        description: template.description || '',
        is_system_template: true
    }));
    const combinedWorkflows = [...enabledWorkflows, ...disabledWorkflows, ...templateWorkflows];
    const schedulerJobs = status.scheduler?.job_details || [];
    const schedulerRunning = Boolean(status.scheduler?.running);
    const jobByWorkflowId = new Map(
        schedulerJobs.map(job => [job.id.replace('__', '/'), job])
    );
    const schedulerBadge = schedulerRunning
        ? '<span class="badge badge-scheduler-running">SCHEDULER RUNNING</span>'
        : '<span class="badge badge-scheduler-stopped">SCHEDULER STOPPED</span>';
    if (dashElements.workflowSchedulerBadge) {
        dashElements.workflowSchedulerBadge.innerHTML = schedulerBadge;
    }
    if (combinedWorkflows.length === 0) {
        dashElements.workflowsStatus.innerHTML = `
            ${renderDashboardBadgeStyles()}
            ${renderRunningWorkflowTasks()}
            <p class="text-sm text-txt-secondary">No workflows loaded.</p>
        `;
        return;
    }
    const sortedWorkflows = sortDashboardWorkflows(combinedWorkflows, jobByWorkflowId);

    dashElements.workflowsStatus.innerHTML = `
        ${renderDashboardBadgeStyles()}
        ${renderRunningWorkflowTasks()}
        <div class="dashboard-table-wrap" role="region" aria-label="Workflows" tabindex="0">
            <table class="dashboard-table">
                <thead>
                    <tr>
                        ${renderDashboardWorkflowSortHeader('id', 'ID')}
                        ${renderDashboardWorkflowSortHeader('status', 'Status')}
                        ${renderDashboardWorkflowSortHeader('last_run', 'Last Run')}
                        ${renderDashboardWorkflowSortHeader('next_run', 'Next Run')}
                        <th>Description</th>
                        <th class="cell-center" aria-label="Run"></th>
                    </tr>
                </thead>
                <tbody>
                    ${sortedWorkflows.map(workflow => {
                        const job = workflow.is_system_template
                            ? dashboardSystemWorkflowTemplateJob(workflow, schedulerJobs)
                            : jobByWorkflowId.get(workflow.global_id);
                        const nextRun = job?.next_run_time
                            ? new Date(job.next_run_time).toLocaleString('en-US', {
                                month: 'short',
                                day: 'numeric',
                                hour: 'numeric',
                                minute: '2-digit'
                            })
                            : '—';
                        const lastRun = job?.last_run_time
                            ? new Date(job.last_run_time).toLocaleString('en-US', {
                                month: 'short',
                                day: 'numeric',
                                hour: 'numeric',
                                minute: '2-digit'
                            })
                            : '—';
                        const description = workflow.description || '—';
                        const { statusLabel, statusClass } = dashboardWorkflowStatus(workflow, job);
                        const toggleLabel = workflow.enabled ? 'Disable workflow' : 'Enable workflow';
                        const nextEnabled = workflow.enabled ? 'false' : 'true';
                        const statusButton = `
                            <button
                                type="button"
                                class="badge ${statusClass}"
                                data-dashboard-workflow-toggle="${escapeHtml(workflow.global_id)}"
                                data-dashboard-workflow-enabled="${nextEnabled}"
                                title="${toggleLabel}"
                                aria-label="${toggleLabel}"
                            >
                                ${statusLabel}
                            </button>
                        `;
                        const runButton = renderDashboardWorkflowRunButton(workflow);
                        return `
                            <tr>
                                <td>
                                    <button
                                        type="button"
                                        class="font-semibold text-accent hover:underline focus:outline-none focus:ring-2 focus:ring-accent rounded-sm text-left"
                                        data-dashboard-workflow-edit="${escapeHtml(workflow.global_id)}"
                                    >
                                        ${escapeHtml(workflow.global_id)}
                                    </button>
                                </td>
                                <td>${statusButton}</td>
                                <td class="cell-xs">${lastRun}</td>
                                <td class="cell-xs">${nextRun}</td>
                                <td class="cell-xs subtle">${escapeHtml(description)}</td>
                                <td class="cell-center">${runButton}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderDashboardVaultActivity(status) {
    if (!dashElements.vaultActivityStatus) return;
    const activityVaults = status.vaults || [];
    const selectedActivityVault = state.selectedActivityVault && activityVaults.some(v => v.name === state.selectedActivityVault)
        ? state.selectedActivityVault
        : activityVaults[0]?.name || '';
    state.selectedActivityVault = selectedActivityVault;

    dashElements.vaultActivityStatus.innerHTML = `
        <div class="flex flex-col md:flex-row md:items-end gap-3">
            <div class="flex-1 min-w-0">
                <select id="vault-activity-selector" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent bg-app-bg text-txt-primary">
                    ${activityVaults.length ? activityVaults.map(v => `
                        <option value="${escapeHtml(v.name)}" ${v.name === selectedActivityVault ? 'selected' : ''}>${escapeHtml(v.name)}</option>
                    `).join('') : '<option value="">No vaults detected</option>'}
                </select>
            </div>
            <button id="vault-activity-refresh" type="button" class="w-full md:w-auto px-4 py-2 bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent self-start md:self-auto">
                Refresh Activity
            </button>
        </div>
        <div id="vault-activity-result" class="mt-3">
            ${renderVaultActivityResult(selectedActivityVault)}
        </div>
    `;

    if (selectedActivityVault && !state.vaultActivity[selectedActivityVault]) {
        loadVaultActivity(selectedActivityVault);
    }
}

function renderDashboardBadgeStyles() {
    return `
        <style>
            .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
            button.badge { cursor: pointer; border: 1px solid currentColor; line-height: 1.2; transition: filter 120ms ease, box-shadow 120ms ease; }
            button.badge:hover { filter: brightness(1.06); box-shadow: 0 0 0 2px rgb(var(--accent-primary) / 0.18); }
            button.badge:focus-visible { outline: 2px solid rgb(var(--accent-primary)); outline-offset: 2px; }
            button.badge:disabled { cursor: not-allowed; opacity: 0.65; }
            .badge-scheduler-running { background: rgb(var(--accent-primary)); color: rgb(var(--text-on-accent)); }
            .badge-scheduler-stopped { background: rgb(var(--state-warning) / 0.2); color: rgb(var(--state-warning)); }
            .badge-scheduled { background: rgb(var(--accent-primary) / 0.14); color: rgb(var(--accent-primary)); }
            .badge-enabled { background: rgb(var(--bg-elevated)); color: rgb(var(--text-primary)); }
            .badge-disabled { background: rgb(var(--text-secondary) / 0.14); color: rgb(var(--text-secondary)); }
        </style>
    `;
}

function renderDashboardVaultSortHeader(column, label, className = '') {
    const sort = state.dashboardVaultSort || { column: 'name', direction: 'asc' };
    const active = sort.column === column;
    const indicator = active ? (sort.direction === 'asc' ? '▲' : '▼') : '↕';
    const nextDirection = active && sort.direction === 'asc' ? 'desc' : 'asc';
    return `
        <th class="${className}" aria-sort="${active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}">
            <button
                type="button"
                class="inline-flex items-center gap-1 text-left font-semibold whitespace-nowrap hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
                data-dashboard-vault-sort="${column}"
                data-dashboard-vault-sort-next="${nextDirection}"
            >
                <span>${escapeHtml(label)}</span>
                <span class="cell-xs subtle" aria-hidden="true">${indicator}</span>
            </button>
        </th>
    `;
}

function renderDashboardWorkflowSortHeader(column, label) {
    const sort = state.dashboardWorkflowSort || { column: 'id', direction: 'asc' };
    const active = sort.column === column;
    const indicator = active ? (sort.direction === 'asc' ? '▲' : '▼') : '↕';
    const nextDirection = active && sort.direction === 'asc' ? 'desc' : 'asc';
    return `
        <th aria-sort="${active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}">
            <button
                type="button"
                class="inline-flex items-center gap-1 text-left font-semibold whitespace-nowrap hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
                data-dashboard-workflow-sort="${column}"
                data-dashboard-workflow-sort-next="${nextDirection}"
            >
                <span>${escapeHtml(label)}</span>
                <span class="cell-xs subtle" aria-hidden="true">${indicator}</span>
            </button>
        </th>
    `;
}

function sortDashboardVaults(vaults) {
    const sort = state.dashboardVaultSort || { column: 'name', direction: 'asc' };
    const direction = sort.direction === 'asc' ? 1 : -1;
    return [...vaults].sort((a, b) => {
        const compared = compareDashboardVaults(a, b, sort.column);
        if (compared !== 0) return compared * direction;
        return String(a.name || '').localeCompare(String(b.name || ''));
    });
}

function compareDashboardVaults(a, b, column) {
    if (column === 'path') {
        return String(a.path || '').localeCompare(String(b.path || ''));
    }
    if (column === 'workflows') {
        return (Number(a.workflow_count) || 0) - (Number(b.workflow_count) || 0);
    }
    if (column === 'files') {
        return compareNullableNumbers(a.tracked_files, b.tracked_files);
    }
    if (column === 'file_delta') {
        return compareVaultFileDelta(a, b);
    }
    if (column === 'latest_change') {
        return compareOptionalDates(a.latest_vault_change_at, b.latest_vault_change_at);
    }
    return String(a.name || '').localeCompare(String(b.name || ''));
}

function formatVaultFileDelta(vault) {
    const created = Number(vault?.files_created_recent) || 0;
    const deleted = Number(vault?.files_deleted_recent) || 0;
    if (created === 0 && deleted === 0) {
        return '<span class="subtle">0</span>';
    }
    return `<span class="text-state-success">+${created}</span> <span class="text-txt-secondary">/</span> <span class="text-state-error">-${deleted}</span>`;
}

function compareVaultFileDelta(a, b) {
    const aCreated = Number(a?.files_created_recent) || 0;
    const aDeleted = Number(a?.files_deleted_recent) || 0;
    const bCreated = Number(b?.files_created_recent) || 0;
    const bDeleted = Number(b?.files_deleted_recent) || 0;
    const netCompared = (aCreated - aDeleted) - (bCreated - bDeleted);
    if (netCompared !== 0) return netCompared;
    return (aCreated + aDeleted) - (bCreated + bDeleted);
}

function compareNullableNumbers(a, b) {
    const aMissing = a === null || a === undefined || Number.isNaN(Number(a));
    const bMissing = b === null || b === undefined || Number.isNaN(Number(b));
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    return Number(a) - Number(b);
}

function sortDashboardWorkflows(workflows, jobByWorkflowId) {
    const sort = state.dashboardWorkflowSort || { column: 'id', direction: 'asc' };
    const direction = sort.direction === 'asc' ? 1 : -1;
    return [...workflows].sort((a, b) => {
        const compared = compareDashboardWorkflows(a, b, jobByWorkflowId, sort.column);
        if (compared !== 0) return compared * direction;
        return String(a.global_id || '').localeCompare(String(b.global_id || ''));
    });
}

function compareDashboardWorkflows(a, b, jobByWorkflowId, column) {
    const aJob = jobByWorkflowId.get(a.global_id);
    const bJob = jobByWorkflowId.get(b.global_id);
    if (column === 'status') {
        return dashboardWorkflowStatus(a, aJob).statusLabel.localeCompare(
            dashboardWorkflowStatus(b, bJob).statusLabel
        );
    }
    if (column === 'last_run') {
        return compareOptionalDates(aJob?.last_run_time, bJob?.last_run_time);
    }
    if (column === 'next_run') {
        return compareOptionalDates(aJob?.next_run_time, bJob?.next_run_time);
    }
    return String(a.global_id || '').localeCompare(String(b.global_id || ''));
}

function dashboardWorkflowStatus(workflow, job) {
    if (!workflow.enabled) {
        return { statusLabel: 'disabled', statusClass: 'badge-disabled' };
    }
    if (job) {
        return { statusLabel: 'scheduled', statusClass: 'badge-scheduled' };
    }
    return { statusLabel: 'enabled', statusClass: 'badge-enabled' };
}

function renderDashboardWorkflowRunButton(workflow) {
    const systemAttribute = workflow.is_system_template
        ? ' data-dashboard-workflow-system-template="true"'
        : '';
    return `
        <button
            type="button"
            class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-70 disabled:cursor-not-allowed"
            data-dashboard-workflow-run="${escapeHtml(workflow.global_id)}"${systemAttribute}
        >
            Run
        </button>
    `;
}

function renderRunningWorkflowTasks() {
    const tasks = activeWorkflowTasks();
    if (!tasks.length) {
        return `
            <div class="mb-3 rounded-md border border-border-primary bg-app-elevated p-3 text-sm text-txt-secondary">
                No workflows are currently running.
            </div>
        `;
    }

    return `
        <div class="mb-4 rounded-md border border-border-primary bg-app-elevated p-3">
            <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                    <p class="font-semibold text-txt-primary">Running Workflows</p>
                    <p class="text-xs text-txt-secondary">${tasks.length} active workflow task${tasks.length === 1 ? '' : 's'}</p>
                </div>
                <button
                    type="button"
                    class="chat-stop-btn px-3 py-1.5 text-sm text-white rounded-md focus:outline-none focus:ring-2 focus:ring-state-error disabled:opacity-70 disabled:cursor-not-allowed"
                    data-dashboard-workflow-stop-all="true"
                >
                    Stop All
                </button>
            </div>
            <div class="dashboard-table-wrap" role="region" aria-label="Running workflows" tabindex="0">
                <table class="dashboard-table">
                    <thead>
                        <tr>
                            <th>Workflow</th>
                            <th>Vault</th>
                            <th>Status</th>
                            <th>Started</th>
                            <th>Source</th>
                            <th class="cell-center" aria-label="Stop"></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${tasks.map(task => `
                            <tr>
                                <td class="cell-xs">
                                    <strong>${escapeHtml(workflowTaskName(task))}</strong>
                                    <div class="cell-mono subtle">${escapeHtml(task.task_id || '')}</div>
                                </td>
                                <td class="cell-xs">${escapeHtml(workflowTaskVault(task))}</td>
                                <td class="cell-xs">${escapeHtml(task.status || 'running')}</td>
                                <td class="cell-xs">${formatShortDate(task.started_at || task.created_at)}</td>
                                <td class="cell-xs">${escapeHtml(task.source || 'unknown')}</td>
                                <td class="cell-center">
                                    <button
                                        type="button"
                                        class="chat-stop-btn px-3 py-1.5 text-sm text-white rounded-md focus:outline-none focus:ring-2 focus:ring-state-error disabled:opacity-70 disabled:cursor-not-allowed"
                                        data-dashboard-workflow-stop="${escapeHtml(task.task_id || '')}"
                                    >
                                        Stop
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function activeWorkflowTasks() {
    return (state.workflowTasks || []).filter(task => !isTerminalTaskStatus(task.status));
}

function workflowTaskName(task) {
    return task?.metadata?.workflow_id || task?.label || '';
}

function workflowTaskVault(task) {
    const scope = String(task?.scope || '');
    const prefix = 'workflow_vault:';
    return scope.startsWith(prefix) ? scope.slice(prefix.length) : '';
}

function syncWorkflowTaskPolling() {
    const hasActiveWorkflowTasks = activeWorkflowTasks().length > 0;
    if (hasActiveWorkflowTasks && !state.workflowTaskPollTimer) {
        state.workflowTaskPollTimer = window.setInterval(() => {
            fetchWorkflowTasks({ render: true });
        }, 2000);
    } else if (!hasActiveWorkflowTasks && state.workflowTaskPollTimer) {
        window.clearInterval(state.workflowTaskPollTimer);
        state.workflowTaskPollTimer = null;
    }
}

function dashboardSystemWorkflowTemplateJob(workflow, schedulerJobs) {
    const templateName = String(workflow?.name || '').replace(/\//g, '__');
    if (!templateName) return null;
    const jobSuffix = `__system__${templateName}`;
    const matchingJobs = schedulerJobs.filter(job => String(job.id || '').endsWith(jobSuffix));
    if (!matchingJobs.length) return null;
    return matchingJobs.reduce((best, job) => {
        const bestTime = Date.parse(best?.next_run_time || '') || Number.POSITIVE_INFINITY;
        const jobTime = Date.parse(job?.next_run_time || '') || Number.POSITIVE_INFINITY;
        return jobTime < bestTime ? job : best;
    }, matchingJobs[0]);
}

function compareOptionalDates(a, b) {
    const aTime = Date.parse(a || '') || 0;
    const bTime = Date.parse(b || '') || 0;
    return aTime - bTime;
}

function renderVaultActivityResult(vaultName) {
    if (!vaultName) {
        return '<p class="text-sm text-txt-secondary">No vault selected.</p>';
    }
    const activity = state.vaultActivity[vaultName];
    if (!activity) {
        return '<p class="text-sm text-txt-secondary">Loading task file mutations...</p>';
    }
    if (activity.error) {
        return `<p class="state-error text-sm">${escapeHtml(activity.error)}</p>`;
    }
    const groups = activity.groups || [];
    if (!groups.length) {
        return '<p class="text-sm text-txt-secondary">No retained task file mutations for this vault.</p>';
    }
    const sortedGroups = sortVaultActivityGroups(groups);
    return `
        <div class="dashboard-table-wrap" role="region" aria-label="AssistantMD activity" tabindex="0">
            <table class="dashboard-table">
                <thead>
                    <tr>
                        ${renderVaultActivitySortHeader('type', 'Type', 'cell-center')}
                        ${renderVaultActivitySortHeader('task', 'Task')}
                        ${renderVaultActivitySortHeader('last_run', 'Last Run')}
                        ${renderVaultActivitySortHeader('files', 'Files Mutated')}
                    </tr>
                </thead>
                <tbody>
                    ${sortedGroups.map(group => `
                        <tr>
                            <td class="cell-center">
                                <span title="${escapeHtml(renderActivityKindLabel(group))}" aria-label="${escapeHtml(renderActivityKindLabel(group))}">${renderActivityKindEmoji(group)}</span>
                            </td>
                            <td>
                                <span>${escapeHtml(renderActivityTaskTitle(group))}</span>
                            </td>
                            <td class="cell-xs">${formatShortDate(group.last_mutation_at)}</td>
                            <td>
                                <button
                                    type="button"
                                    class="text-accent hover:underline focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
                                    data-vault-activity-vault="${escapeHtml(vaultName)}"
                                    data-vault-activity-id="${escapeHtml(group.activity_id || group.task_id)}"
                                >
                                    ${group.mutation_count || 0} file${group.mutation_count === 1 ? '' : 's'}
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderVaultActivitySortHeader(column, label, className = '') {
    const sort = state.vaultActivitySort || { column: 'last_run', direction: 'desc' };
    const active = sort.column === column;
    const indicator = active ? (sort.direction === 'asc' ? '▲' : '▼') : '↕';
    const nextDirection = active && sort.direction === 'asc' ? 'desc' : 'asc';
    return `
        <th class="${className}" aria-sort="${active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}">
            <button
                type="button"
                class="inline-flex items-center gap-1 text-left font-semibold hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
                data-vault-activity-sort="${column}"
                data-vault-activity-sort-next="${nextDirection}"
            >
                <span>${escapeHtml(label)}</span>
                <span class="cell-xs subtle" aria-hidden="true">${indicator}</span>
            </button>
        </th>
    `;
}

function sortVaultActivityGroups(groups) {
    const sort = state.vaultActivitySort || { column: 'last_run', direction: 'desc' };
    const direction = sort.direction === 'asc' ? 1 : -1;
    return [...groups].sort((a, b) => {
        const compared = compareVaultActivityGroups(a, b, sort.column);
        if (compared !== 0) return compared * direction;
        const bTime = Date.parse(b.last_mutation_at || '') || 0;
        const aTime = Date.parse(a.last_mutation_at || '') || 0;
        if (bTime !== aTime) return bTime - aTime;
        return String(a.activity_id || a.task_id || '').localeCompare(String(b.activity_id || b.task_id || ''));
    });
}

function compareVaultActivityGroups(a, b, column) {
    if (column === 'type') {
        return renderActivityKindLabel(a).localeCompare(renderActivityKindLabel(b));
    }
    if (column === 'task') {
        return renderActivityTaskTitle(a).localeCompare(renderActivityTaskTitle(b));
    }
    if (column === 'files') {
        return (a.mutation_count || 0) - (b.mutation_count || 0);
    }
    const aTime = Date.parse(a.last_mutation_at || '') || 0;
    const bTime = Date.parse(b.last_mutation_at || '') || 0;
    return aTime - bTime;
}

function renderActivityTaskTitle(group) {
    if (group.activity_kind === 'chat' && group.chat_session_id) {
        return formatActivityChatSessionLabel({
            session_id: group.chat_session_id,
            created_at: group.chat_session_created_at,
            last_activity_at: group.chat_session_last_activity_at,
            title: group.chat_session_title
        });
    }
    return stripActivityKindPrefix(
        group.activity_label || `${group.task_kind || 'task'}: ${group.vault_name || state.selectedActivityVault || 'vault'}`
    );
}

function renderActivityKindEmoji(group) {
    const kind = normalizedActivityKind(group);
    if (kind === 'chat') return '💬';
    if (kind === 'workflow') return '⚙️';
    if (kind === 'context') return '🧩';
    if (kind === 'ingestion') return '📥';
    return '•';
}

function formatActivityChatSessionLabel(session) {
    const title = String(session?.title || '').trim();
    if (title) {
        return title;
    }
    return formatSessionOptionLabel(session);
}

function renderActivityKindLabel(group) {
    const kind = normalizedActivityKind(group);
    if (kind === 'chat') return 'Chat';
    if (kind === 'workflow') return 'Workflow';
    if (kind === 'context') return 'Context assembly';
    if (kind === 'ingestion') return 'Ingestion';
    return 'Task';
}

function normalizedActivityKind(group) {
    const rawKind = String(group.activity_kind || group.task_kind || '').trim().toLowerCase();
    if (rawKind === 'chat') return 'chat';
    if (rawKind === 'workflow') return 'workflow';
    if (rawKind === 'ingestion') return 'ingestion';
    if (rawKind === 'context' || rawKind === 'context_assembly' || rawKind === 'context assembly') {
        return 'context';
    }
    const label = String(group.activity_label || '').trim().toLowerCase();
    if (label.startsWith('chat:')) return 'chat';
    if (label.startsWith('workflow:')) return 'workflow';
    if (label.startsWith('ingestion:')) return 'ingestion';
    if (label.startsWith('context:') || label.startsWith('context assembly:')) return 'context';
    return rawKind || 'task';
}

function stripActivityKindPrefix(label) {
    return String(label || '').replace(/^(chat|workflow|ingestion|context|context assembly|context_assembly):\s*/i, '');
}

function renderMutationSnapshotLink(mutation) {
    if (!mutation.before_snapshot_id) {
        return '<span class="subtle">—</span>';
    }
    const snapshotUrl = `api/vault-state/snapshots/${encodeURIComponent(mutation.before_snapshot_id)}/content`;
    return `
        <a
            href="${snapshotUrl}"
            target="_blank"
            rel="noopener"
            class="text-accent hover:underline focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
        >
            Open
        </a>
    `;
}

function openVaultActivityDetails(vaultName, activityId) {
    if (!vaultName || !activityId) return;
    const activity = state.vaultActivity[vaultName];
    const group = (activity?.groups || []).find(item => (item.activity_id || item.task_id) === activityId);
    if (!group) {
        console.warn('AssistantMD activity group not found', { vaultName, activityId });
        return;
    }
    closeVaultActivityDetails();

    const mutations = sortVaultActivityMutations(group.mutations || []);

    const overlay = document.createElement('div');
    overlay.id = 'vault-activity-modal';
    overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
    overlay.innerHTML = `
        <div class="absolute inset-0" data-vault-activity-close="true"></div>
        <section class="app-modal-panel relative overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="vault-activity-modal-title">
            <div class="app-modal-header sticky top-0">
                <div class="app-modal-title-block">
                    <h2 id="vault-activity-modal-title" class="text-lg font-semibold text-txt-primary">${renderActivityKindEmoji(group)} ${escapeHtml(renderActivityTaskTitle(group))}</h2>
                </div>
                <div class="app-modal-actions">
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-vault-activity-close="true">
                        Close
                    </button>
                </div>
            </div>
            <div class="p-4">
                <div class="text-sm text-txt-secondary mb-3">
                    Last run ${formatShortDate(group.last_mutation_at)} · ${group.mutation_count || 0} file${group.mutation_count === 1 ? '' : 's'} mutated
                </div>
                <div class="dashboard-table-wrap" role="region" aria-label="AssistantMD activity files" tabindex="0">
                    <table class="dashboard-table">
                        <thead>
                            <tr>
                                ${renderVaultActivityMutationSortHeader('path', 'Path')}
                                ${renderVaultActivityMutationSortHeader('from', 'From')}
                                ${renderVaultActivityMutationSortHeader('operation', 'Operation')}
                                ${renderVaultActivityMutationSortHeader('time', 'Time')}
                                <th>Snapshot</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${mutations.map(mutation => `
                                <tr>
                                    <td class="cell-mono cell-xs">${escapeHtml(mutation.path)}</td>
                                    <td class="cell-mono cell-xs">${mutation.related_path ? escapeHtml(mutation.related_path) : '<span class="subtle">—</span>'}</td>
                                    <td>${escapeHtml(mutation.operation)}</td>
                                    <td class="cell-xs">${formatShortDate(mutation.created_at)}</td>
                                    <td>${renderMutationSnapshotLink(mutation)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    `;
    overlay.addEventListener('click', (event) => {
        const target = event.target;
        if (target instanceof HTMLElement) {
            const sortButton = target.closest('[data-vault-activity-mutation-sort]');
            if (sortButton instanceof HTMLElement) {
                state.vaultActivityMutationSort = {
                    column: sortButton.getAttribute('data-vault-activity-mutation-sort') || 'time',
                    direction: sortButton.getAttribute('data-vault-activity-mutation-sort-next') || 'asc'
                };
                openVaultActivityDetails(vaultName, activityId);
                return;
            }
        }
        if (target instanceof HTMLElement && target.dataset.vaultActivityClose === 'true') {
            closeVaultActivityDetails();
        }
    });
    document.body.appendChild(overlay);
}

function renderVaultActivityMutationSortHeader(column, label) {
    const sort = state.vaultActivityMutationSort || { column: 'time', direction: 'desc' };
    const active = sort.column === column;
    const indicator = active ? (sort.direction === 'asc' ? '▲' : '▼') : '↕';
    const nextDirection = active && sort.direction === 'asc' ? 'desc' : 'asc';
    return `
        <th aria-sort="${active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}">
            <button
                type="button"
                class="inline-flex items-center gap-1 text-left font-semibold hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent rounded-sm"
                data-vault-activity-mutation-sort="${column}"
                data-vault-activity-mutation-sort-next="${nextDirection}"
            >
                <span>${escapeHtml(label)}</span>
                <span class="cell-xs subtle" aria-hidden="true">${indicator}</span>
            </button>
        </th>
    `;
}

function sortVaultActivityMutations(mutations) {
    const sort = state.vaultActivityMutationSort || { column: 'time', direction: 'desc' };
    const direction = sort.direction === 'asc' ? 1 : -1;
    return [...mutations].sort((a, b) => {
        const compared = compareVaultActivityMutations(a, b, sort.column);
        if (compared !== 0) return compared * direction;
        const bTime = Date.parse(b.created_at || '') || 0;
        const aTime = Date.parse(a.created_at || '') || 0;
        if (bTime !== aTime) return bTime - aTime;
        return (b.id || 0) - (a.id || 0);
    });
}

function compareVaultActivityMutations(a, b, column) {
    if (column === 'path') {
        return String(a.path || '').localeCompare(String(b.path || ''));
    }
    if (column === 'from') {
        return String(a.related_path || '').localeCompare(String(b.related_path || ''));
    }
    if (column === 'operation') {
        return String(a.operation || '').localeCompare(String(b.operation || ''));
    }
    const aTime = Date.parse(a.created_at || '') || 0;
    const bTime = Date.parse(b.created_at || '') || 0;
    return aTime - bTime;
}

function handleVaultActivityClick(target) {
    const activityButton = target.closest('[data-vault-activity-id]');
    if (!(activityButton instanceof HTMLElement)) return;
    const vaultName = activityButton.getAttribute('data-vault-activity-vault') || state.selectedActivityVault;
    const activityId = activityButton.getAttribute('data-vault-activity-id') || '';
    openVaultActivityDetails(vaultName, activityId);
}

function closeVaultActivityDetails() {
    document.getElementById('vault-activity-modal')?.remove();
}

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        if (state.isChatFocusMode) {
            setChatFocusMode(false);
            return;
        }
        closeWorkspacePickerModal();
        closeVaultActivityDetails();
    }
});

function formatShortDate(value) {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '—';
    return parsed.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

async function loadVaultActivity(vaultName) {
    if (!vaultName) return;
    state.vaultActivity[vaultName] = { loading: true };
    updateVaultActivityContainer(vaultName);
    try {
        const response = await fetch(`api/vaults/${encodeURIComponent(vaultName)}/task-mutations?limit=25`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        state.vaultActivity[vaultName] = { groups: data.groups || [] };
    } catch (error) {
        console.error('Error loading AssistantMD activity:', error);
        state.vaultActivity[vaultName] = { error: `Failed to load AssistantMD activity: ${error.message}` };
    }
    updateVaultActivityContainer(vaultName);
}

function updateVaultActivityContainer(vaultName) {
    const container = document.getElementById('vault-activity-result');
    if (!container || state.selectedActivityVault !== vaultName) return;
    container.innerHTML = renderVaultActivityResult(vaultName);
}

// Setup event listeners
function setupEventListeners() {
    if (chatElements.sendBtn) {
        chatElements.sendBtn.addEventListener('click', () => {
            if (state.isLoading) {
                stopChatResponse();
                return;
            }
            sendMessage();
        });
    }

    if (chatElements.chatInput) {
        chatElements.chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    if (chatElements.focusToggleInline) {
        chatElements.focusToggleInline.addEventListener('click', toggleChatFocusMode);
    }

    if (chatElements.focusDivider) {
        chatElements.focusDivider.addEventListener('pointerdown', handleChatFocusDividerPointerDown);
        chatElements.focusDivider.addEventListener('pointermove', handleChatFocusDividerPointerMove);
        chatElements.focusDivider.addEventListener('pointerup', stopChatFocusDividerResize);
        chatElements.focusDivider.addEventListener('pointercancel', stopChatFocusDividerResize);
        chatElements.focusDivider.addEventListener('keydown', handleChatFocusDividerKeydown);
    }

    window.addEventListener('resize', () => {
        if (!state.isChatFocusMode) return;
        const current = chatElements.composer?.getBoundingClientRect().height;
        setChatComposerHeight(current, { persist: false });
    });

    if (chatElements.sessionDropdownTrigger) {
        chatElements.sessionDropdownTrigger.addEventListener('click', (event) => {
            event.stopPropagation();
            if (chatElements.sessionDropdownTrigger.disabled) {
                return;
            }
            setSessionMenuOpen(!chatComposeState.sessionMenuOpen);
        });
    }

    if (chatElements.sessionDropdownMenu) {
        chatElements.sessionDropdownMenu.addEventListener('click', async (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const option = target.closest('[data-session-id]');
            if (option instanceof HTMLElement) {
                event.preventDefault();
                await selectSessionFromDropdown(option.dataset.sessionId || '');
            }
        });
        chatElements.sessionDropdownMenu.addEventListener('mouseover', (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const previewTarget = target.closest('[data-session-summary-preview-id]');
            if (!(previewTarget instanceof HTMLElement)) return;
            const related = event.relatedTarget;
            if (related instanceof Element && previewTarget.contains(related)) return;
            const sessionId = previewTarget.dataset.sessionSummaryPreviewId || '';
            const session = state.sessions.find((item) => item.session_id === sessionId);
            openSessionSummaryPreview(previewTarget, session);
        });
        chatElements.sessionDropdownMenu.addEventListener('mouseout', (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const previewTarget = target.closest('[data-session-summary-preview-id]');
            if (!(previewTarget instanceof HTMLElement)) return;
            const related = event.relatedTarget;
            if (related instanceof Element && previewTarget.contains(related)) return;
            closeSessionSummaryPreview();
        });
        chatElements.sessionDropdownMenu.addEventListener('focusin', (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const previewTarget = target.closest('[data-session-summary-preview-focus-id]');
            if (!(previewTarget instanceof HTMLElement)) return;
            const sessionId = previewTarget.dataset.sessionSummaryPreviewFocusId || '';
            const session = state.sessions.find((item) => item.session_id === sessionId);
            openSessionSummaryPreview(previewTarget, session);
        });
        chatElements.sessionDropdownMenu.addEventListener('focusout', (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            if (target.closest('[data-session-summary-preview-focus-id]')) {
                closeSessionSummaryPreview();
            }
        });
    }

    if (chatElements.sessionSummaryTrigger) {
        chatElements.sessionSummaryTrigger.addEventListener('mouseenter', () => warmSessionSummaryPreview(selectedSessionWithSummary()));
        chatElements.sessionSummaryTrigger.addEventListener('focus', () => warmSessionSummaryPreview(selectedSessionWithSummary()));
        chatElements.sessionSummaryTrigger.addEventListener('click', () => openSessionSummaryModalForSession(selectedSessionWithSummary()));
    }

    if (chatElements.sessionTitleSave) {
        chatElements.sessionTitleSave.addEventListener('click', saveSessionTitle);
    }

    if (chatElements.sessionTitleInput) {
        chatElements.sessionTitleInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') saveSessionTitle();
        });
    }

    if (chatElements.sessionDeleteBtn) {
        chatElements.sessionDeleteBtn.addEventListener('click', deleteCurrentSession);
    }

    if (chatElements.sessionExportBtn) {
        chatElements.sessionExportBtn.addEventListener('click', exportCurrentSession);
    }

    if (chatElements.workspacePathInput) {
        chatElements.workspacePathInput.addEventListener('input', () => {
            syncWorkspaceControlState();
        });
        chatElements.workspacePathInput.addEventListener('blur', saveWorkspacePath);
        chatElements.workspacePathInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                saveWorkspacePath();
            }
        });
    }

    if (chatElements.workspacePickerBtn) {
        chatElements.workspacePickerBtn.addEventListener('click', openWorkspacePickerModal);
    }

    if (chatElements.workspaceUnlockBtn) {
        chatElements.workspaceUnlockBtn.addEventListener('click', unlockWorkspacePath);
    }

    if (chatElements.toolDropdownTrigger) {
        chatElements.toolDropdownTrigger.addEventListener('click', (event) => {
            event.stopPropagation();
            if (chatElements.toolDropdownTrigger.disabled) {
                return;
            }
            setToolMenuOpen(!chatComposeState.toolMenuOpen);
        });
    }

    if (chatElements.toolsCheckboxes) {
        chatElements.toolsCheckboxes.addEventListener('change', () => {
            updateToolDropdownSummary();
        });
    }

    if (chatElements.attachBtn && chatElements.attachInput) {
        chatElements.attachBtn.addEventListener('click', () => {
            if (chatComposeState.pendingAttachments.length > 0) {
                setAttachmentPopoverOpen(!chatComposeState.popoverOpen);
                return;
            }
            openAttachmentPicker();
        });
        chatElements.attachInput.addEventListener('change', (event) => {
            const input = event.target;
            addPendingAttachments(input?.files);
            if (input) {
                input.value = '';
            }
        });
        chatElements.attachBtn.addEventListener('mouseenter', () => {
            if (chatComposeState.pendingAttachments.length > 0) {
                setAttachmentPopoverOpen(true);
            }
        });
        chatElements.attachBtn.addEventListener('focus', () => {
            if (chatComposeState.pendingAttachments.length > 0) {
                setAttachmentPopoverOpen(true);
            }
        });
    }

    if (chatElements.attachmentPopover) {
        chatElements.attachmentPopover.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            const idxRaw = target.getAttribute('data-attachment-remove');
            const addAction = target.getAttribute('data-attachment-add');
            if (addAction === 'true') {
                openAttachmentPicker();
                return;
            }
            if (idxRaw === null) return;
            const idx = Number.parseInt(idxRaw, 10);
            if (Number.isNaN(idx) || idx < 0 || idx >= chatComposeState.pendingAttachments.length) return;
            chatComposeState.pendingAttachments.splice(idx, 1);
            renderPendingAttachments();
            if (chatComposeState.pendingAttachments.length === 0) {
                setAttachmentPopoverOpen(false);
            }
        });
        chatElements.attachmentPopover.addEventListener('mouseenter', () => {
            if (chatComposeState.pendingAttachments.length > 0) {
                setAttachmentPopoverOpen(true);
            }
        });
        chatElements.attachmentPopover.addEventListener('mouseleave', () => {
            if (chatComposeState.popoverOpen) {
                setAttachmentPopoverOpen(false);
            }
        });
    }

    document.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Node)) return;

        if (chatComposeState.popoverOpen) {
            const clickedAttachBtn = chatElements.attachBtn && chatElements.attachBtn.contains(target);
            const clickedPopover = chatElements.attachmentPopover && chatElements.attachmentPopover.contains(target);
            if (!clickedAttachBtn && !clickedPopover) {
                setAttachmentPopoverOpen(false);
            }
        }

        if (chatComposeState.toolMenuOpen) {
            const clickedToolDropdown = chatElements.toolDropdown && chatElements.toolDropdown.contains(target);
            if (!clickedToolDropdown) {
                setToolMenuOpen(false);
            }
        }

        if (chatComposeState.sessionMenuOpen) {
            const clickedSessionDropdown = chatElements.sessionDropdown && chatElements.sessionDropdown.contains(target);
            if (!clickedSessionDropdown) {
                setSessionMenuOpen(false);
                closeSessionSummaryPreview();
            }
        }
    });

    if (dashElements.rescanBtn) {
        dashElements.rescanBtn.addEventListener('click', rescanVaults);
    }

    if (dashElements.systemStatus) {
        dashElements.systemStatus.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            const vaultSortButton = target.closest('[data-dashboard-vault-sort]');
            if (vaultSortButton instanceof HTMLElement) {
                state.dashboardVaultSort = {
                    column: vaultSortButton.getAttribute('data-dashboard-vault-sort') || 'name',
                    direction: vaultSortButton.getAttribute('data-dashboard-vault-sort-next') || 'asc'
                };
                displaySystemStatus();
                return;
            }
        });
    }

    if (dashElements.workflowsStatus) {
        dashElements.workflowsStatus.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            const editButton = target.closest('[data-dashboard-workflow-edit]');
            if (editButton instanceof HTMLElement) {
                openWorkflowFileEditor(editButton.getAttribute('data-dashboard-workflow-edit') || '');
                return;
            }
            const toggleButton = target.closest('[data-dashboard-workflow-toggle]');
            if (toggleButton instanceof HTMLElement) {
                toggleWorkflowEnabled(
                    toggleButton.getAttribute('data-dashboard-workflow-toggle') || '',
                    toggleButton.getAttribute('data-dashboard-workflow-enabled') === 'true',
                    toggleButton
                );
                return;
            }
            const runButton = target.closest('[data-dashboard-workflow-run]');
            if (runButton instanceof HTMLElement) {
                executeWorkflow(
                    runButton.getAttribute('data-dashboard-workflow-run') || '',
                    runButton,
                    runButton.getAttribute('data-dashboard-workflow-system-template') === 'true'
                );
                return;
            }
            const stopButton = target.closest('[data-dashboard-workflow-stop]');
            if (stopButton instanceof HTMLElement) {
                stopWorkflow(
                    stopButton.getAttribute('data-dashboard-workflow-stop') || '',
                    stopButton
                );
                return;
            }
            const stopAllButton = target.closest('[data-dashboard-workflow-stop-all]');
            if (stopAllButton instanceof HTMLElement) {
                stopAllWorkflows(stopAllButton);
                return;
            }
            const workflowSortButton = target.closest('[data-dashboard-workflow-sort]');
            if (workflowSortButton instanceof HTMLElement) {
                state.dashboardWorkflowSort = {
                    column: workflowSortButton.getAttribute('data-dashboard-workflow-sort') || 'id',
                    direction: workflowSortButton.getAttribute('data-dashboard-workflow-sort-next') || 'asc'
                };
                displaySystemStatus();
                return;
            }
        });
    }

    if (dashElements.vaultActivityStatus) {
        dashElements.vaultActivityStatus.addEventListener('change', (event) => {
            if (event.target?.id !== 'vault-activity-selector') return;
            state.selectedActivityVault = event.target.value || '';
            loadVaultActivity(state.selectedActivityVault);
        });
        dashElements.vaultActivityStatus.addEventListener('click', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            const sortButton = target.closest('[data-vault-activity-sort]');
            if (sortButton instanceof HTMLElement) {
                state.vaultActivitySort = {
                    column: sortButton.getAttribute('data-vault-activity-sort') || 'last_run',
                    direction: sortButton.getAttribute('data-vault-activity-sort-next') || 'asc'
                };
                updateVaultActivityContainer(state.selectedActivityVault);
                return;
            }
            if (target.id === 'vault-activity-refresh') {
                if (state.selectedActivityVault) {
                    loadVaultActivity(state.selectedActivityVault);
                }
                return;
            }
            handleVaultActivityClick(target);
        });
    }

    if (chatElements.chatMessages) {
        chatElements.chatMessages.addEventListener('scroll', handleChatScroll, { passive: true });
    }

    if (chatElements.vaultSelector) {
        chatElements.vaultSelector.addEventListener('change', handleVaultChange);
    }
    syncChatControlLocks();
}

function handleVaultChange() {
    const vault = chatElements.vaultSelector ? chatElements.vaultSelector.value : '';
    state.sessionId = null;
    state.isWorkspaceUnlocked = false;
    state.sessions = [];
    if (chatElements.workspacePathInput) {
        chatElements.workspacePathInput.value = '';
    }
    clearCompactionProgress();
    renderSessionSelector();
    updateSessionTitleRow();
    renderChatEmptyState();
    updateStatus();
    populateTemplates([]); // reset while loading
    if (vault) {
        fetchTemplates(vault);
        fetchSessions(vault);
    }
}

function populateTemplates(templates, preferredTemplate = '') {
    if (!chatElements.templateSelector) return;
    const templateList = Array.isArray(templates) ? templates : [];
    chatElements.templateSelector.innerHTML = '<option value="">No template</option>';
    templateList.forEach((tmpl) => {
        const option = document.createElement('option');
        option.value = tmpl.name;
        option.textContent = `${tmpl.name} (${tmpl.source})`;
        chatElements.templateSelector.appendChild(option);
    });
    const configuredDefaultTemplate = state.metadata?.default_context_script || '';
    const fallbackCandidates = [
        preferredTemplate,
        configuredDefaultTemplate,
        'default.md'
    ].filter((value, index, values) => value && values.indexOf(value) === index);

    const selectedTemplate = fallbackCandidates.find((candidate) =>
        Array.from(chatElements.templateSelector.options).some((option) => option.value === candidate)
    );
    if (selectedTemplate) {
        chatElements.templateSelector.value = selectedTemplate;
    } else {
        chatElements.templateSelector.value = '';
    }
    chatElements.templateSelector.disabled = false;
}

async function fetchTemplates(vault, preferredTemplate = '') {
    if (!vault) {
        populateTemplates([], preferredTemplate);
        return;
    }
    try {
        const response = await fetch(`api/context/templates?vault_name=${encodeURIComponent(vault)}`);
        if (!response.ok) {
            throw new Error('Failed to fetch templates');
        }
        const templates = await response.json();
        populateTemplates(templates, preferredTemplate);
    } catch (error) {
        console.error('Error fetching templates:', error);
        populateTemplates([], preferredTemplate);
    }
}

// Send message handler with streaming response support
async function sendMessage() {
    const message = chatElements.chatInput.value.trim();
    const pendingUploads = chatComposeState.pendingAttachments.slice();
    if ((!message && pendingUploads.length === 0) || state.isLoading) return;
    const effectivePrompt = message || 'Please analyze the attached image(s).';

    const vault = chatElements.vaultSelector.value;
    const model = chatElements.modelSelector.value;
    const thinking = chatElements.thinkingSelector ? (chatElements.thinkingSelector.value || 'default') : 'default';

    if (!vault) {
        alert('Please select a vault');
        return;
    }

    if (!model) {
        alert('Please select a model');
        return;
    }

    const userMessageText = pendingUploads.length > 0
        ? `${effectivePrompt}\n\n[Attached images]\n${pendingUploads.map((item) => `- ${item.file.name}`).join('\n')}`
        : effectivePrompt;
    addMessage('user', userMessageText.trim());
    chatElements.chatInput.value = '';
    state.isLoading = true;
    chatElements.sendBtn.disabled = true;
    syncChatControlLocks();

    const selectedTools = Array.from(chatElements.toolsCheckboxes.querySelectorAll('input:checked'))
        .map(cb => cb.value);

    const contextTemplateValue = chatElements.templateSelector ? chatElements.templateSelector.value || null : null;
    const workspacePathValue = currentWorkspacePath() || null;
    const requestSessionId = state.sessionId || createClientSessionId(vault);
    state.sessionId = requestSessionId;
    state.isWorkspaceUnlocked = false;
    renderSessionSelector();
    updateSessionTitleRow();
    refreshCompactionProgress();
    syncChatControlLocks();
    state.activeChatSessionId = requestSessionId;
    const abortController = new AbortController();
    state.activeChatAbortController = abortController;

    const loadingMessage = addLoadingMessage();

    try {
        let response;
        if (pendingUploads.length > 0) {
            const formData = new FormData();
            formData.append('vault_name', vault);
            formData.append('prompt', effectivePrompt);
            formData.append('model', model);
            formData.append('thinking', thinking);
            formData.append('stream', 'true');
            if (contextTemplateValue) {
                formData.append('context_template', contextTemplateValue);
            }
            if (workspacePathValue) {
                formData.append('workspace_path', workspacePathValue);
            }
            selectedTools.forEach((toolName) => formData.append('tools', toolName));
            formData.append('session_id', requestSessionId);
            pendingUploads.forEach((item) => {
                formData.append('images', item.file, item.file.name);
            });
            response = await fetch('api/chat/execute', {
                method: 'POST',
                body: formData,
                signal: abortController.signal
            });
        } else {
            const requestData = {
                vault_name: vault,
                prompt: effectivePrompt,
                tools: selectedTools,
                model: model,
                thinking: thinking,
                context_template: contextTemplateValue,
                workspace_path: workspacePathValue,
                session_id: requestSessionId,
                stream: true
            };
            response = await fetch('api/chat/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestData),
                signal: abortController.signal
            });
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        clearPendingAttachments();

        removeLoadingMessage(loadingMessage);

        const sessionId = response.headers.get('X-Session-ID');
        if (sessionId) {
            state.sessionId = sessionId;
            syncChatControlLocks();
            renderSessionSelector();
            updateSessionTitleRow();
            refreshCompactionProgress();
        }

        // Fallback for environments that do not support streaming
        if (!response.body || !response.body.getReader) {
            const data = await response.json();
            const fallbackMessage = createAssistantStreamingMessage();
            fallbackMessage.fullText = data.response || 'No response content';
            renderAssistantMarkdown(fallbackMessage);
            finalizeAssistantMessage(fallbackMessage, {
                sessionId: data.session_id || state.sessionId || 'unknown',
                messageCount: data.message_count || (fallbackMessage.fullText ? 1 : 0),
                toolCount: 0,
                status: 'done'
            });
            if (vault && state.sessionId) {
                await fetchSessions(vault, state.sessionId);
                await loadSession(state.sessionId);
            }
            return;
        }

        const assistantMessage = createAssistantStreamingMessage();

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let messageCount = 0;
        let finished = false;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split(/\r?\n\r?\n/);
            buffer = events.pop() || '';

            for (const rawEvent of events) {
                const payload = parseSseEvent(rawEvent);
                if (!payload) continue;

                const eventType = payload.event || 'delta';
                if (eventType === 'delta') {
                    const delta = payload.choices?.[0]?.delta?.content;
                    if (delta) {
                        assistantMessage.fullText += delta;
                        renderAssistantMarkdown(assistantMessage);
                    }
                } else if (eventType === 'tool_call_started' || eventType === 'tool_call_finished') {
                    handleToolEvent(assistantMessage, payload);
                } else if (eventType === 'done') {
                    finished = true;
                    messageCount = Math.max(messageCount, 1);
                } else if (eventType === 'cancelled') {
                    finished = true;
                    state.isCancellingChat = false;
                    syncChatControlLocks();
                    setAssistantStatus(assistantMessage, 'Stopped', 'done');
                } else if (eventType === 'error') {
                    finished = true;
                    const errorDelta = payload.choices?.[0]?.delta?.content;
                    if (errorDelta) {
                        assistantMessage.fullText += `\n\n${errorDelta}`;
                        renderAssistantMarkdown(assistantMessage);
                    }
                    assistantMessage.errorMessages.push(errorDelta || 'Unknown streaming error.');
                    setAssistantStatus(assistantMessage, 'Something went wrong', 'error');
                }
            }
        }

        // Flush any remaining buffered data
        if (buffer.trim()) {
            const payload = parseSseEvent(buffer);
            if (payload) {
                const eventType = payload.event || 'delta';
                if (eventType === 'delta') {
                    const delta = payload.choices?.[0]?.delta?.content;
                    if (delta) {
                        assistantMessage.fullText += delta;
                        renderAssistantMarkdown(assistantMessage);
                    }
                } else if (eventType === 'done') {
                    finished = true;
                } else if (eventType === 'cancelled') {
                    finished = true;
                    state.isCancellingChat = false;
                    syncChatControlLocks();
                    setAssistantStatus(assistantMessage, 'Stopped', 'done');
                }
            }
        }

        finalizeAssistantMessage(assistantMessage, {
            sessionId: state.sessionId || 'unknown',
            messageCount: Math.max(messageCount, assistantMessage.fullText ? 1 : 0),
            toolCount: assistantMessage.toolStatusMap.size,
            status: finished ? 'done' : 'incomplete'
        });
        if (vault) {
            await fetchSessions(vault, state.sessionId || '');
            if (state.sessionId) {
                await loadSession(state.sessionId);
            }
        }

    } catch (error) {
        console.error('Error sending message:', error);
        removeLoadingMessage(loadingMessage);
        if (state.isCancellingChat || error.name === 'AbortError') {
            addMessage('assistant', 'Response stopped.');
        } else {
            addChatErrorMessage(error.message);
        }
    } finally {
        state.isLoading = false;
        state.isCancellingChat = false;
        state.activeChatSessionId = null;
        state.activeChatAbortController = null;
        chatElements.sendBtn.disabled = false;
        syncChatControlLocks();
        chatElements.chatInput.focus();
        refreshCompactionProgress();
    }
}

async function stopChatResponse() {
    if (!state.isLoading || state.isCancellingChat) return;
    const sessionId = state.activeChatSessionId || state.sessionId;
    if (!sessionId) return;

    state.isCancellingChat = true;
    syncChatControlLocks();
    try {
        const response = await fetch(
            `api/chat/sessions/${encodeURIComponent(sessionId)}/cancel`,
            { method: 'POST' }
        );
        if (response.status === 404) {
            if (state.activeChatAbortController) {
                state.activeChatAbortController.abort();
            }
            return;
        }
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
    } catch (error) {
        console.error('Error stopping chat response:', error);
        state.isCancellingChat = false;
        syncChatControlLocks();
        addChatErrorMessage(`Failed to stop response: ${error.message}`);
    }
}

// Loading indicator helpers
function addLoadingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex justify-start';
    messageDiv.id = 'loading-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'max-w-[80%] px-4 py-2 rounded-lg message-bubble message-assistant';
    contentDiv.innerHTML = `<div class="flex items-center space-x-2 text-sm">
        <span class="typing-indicator inline-flex">${TYPING_DOTS_HTML}</span>
        <span class="ml-1">Contacting assistant…</span>
    </div>`;

    messageDiv.appendChild(contentDiv);

    appendChatMessageNode(messageDiv, { forceScroll: true });

    return messageDiv;
}

function removeLoadingMessage(messageDiv) {
    if (messageDiv && messageDiv.parentNode) {
        messageDiv.parentNode.removeChild(messageDiv);
    }
}

function enforceExternalLinkBehavior(container) {
    if (!container) return;
    const links = container.querySelectorAll('a[href]');
    links.forEach(link => {
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
    });
}

function renderAssistantHtml(bodyDiv, markdownContent = '') {
    if (!bodyDiv) return;
    const content = (markdownContent || '').trim();
    const protectedContent = protectLatexForMarkdown(content);
    const renderedHtml = content ? marked.parse(protectedContent.markdown) : '';
    const restoredHtml = restoreLatexPlaceholders(renderedHtml, protectedContent.segments);
    bodyDiv.innerHTML = sanitizeAssistantHtml(restoredHtml);
}

function protectLatexForMarkdown(markdown) {
    if (!markdown) {
        return { markdown: '', segments: [] };
    }

    const segments = [];
    const codePattern = /(```[\s\S]*?```|`[^`\n]*`)/g;
    let cursor = 0;
    let output = '';
    let match = codePattern.exec(markdown);

    while (match) {
        output += replaceLatexSegments(markdown.slice(cursor, match.index), segments);
        output += match[0];
        cursor = match.index + match[0].length;
        match = codePattern.exec(markdown);
    }

    output += replaceLatexSegments(markdown.slice(cursor), segments);
    return { markdown: output, segments };
}

function replaceLatexSegments(text, segments) {
    if (!text) return '';

    const pattern =
        /(\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$\$[\s\S]+?\$\$)/g;

    return text.replace(pattern, (rawMath) => {
        const placeholder = `@@MATH_SEGMENT_${segments.length}@@`;
        segments.push(rawMath);
        return placeholder;
    });
}

function restoreLatexPlaceholders(html, segments) {
    if (!html || !segments.length) return html;

    return segments.reduce((acc, rawMath, index) => {
        const placeholder = `@@MATH_SEGMENT_${index}@@`;
        return acc.split(placeholder).join(escapeHtml(rawMath));
    }, html);
}

function escapeHtml(value) {
    if (!value) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function truncateText(value, maxLength) {
    const text = String(value || '').trim();
    if (!text || text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
}

function getMathJax() {
    if (typeof window === 'undefined') return null;
    const mathJax = window.MathJax;
    if (!mathJax || typeof mathJax.typesetPromise !== 'function') return null;
    return mathJax;
}

function sanitizeAssistantHtml(html) {
    if (!html) return '';

    if (!window.DOMPurify || typeof window.DOMPurify.sanitize !== 'function') {
        return html;
    }

    return window.DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true }
    });
}

function postProcessAssistantBody(bodyDiv) {
    if (!bodyDiv) return;
    enforceExternalLinkBehavior(bodyDiv);
    renderAssistantMath(bodyDiv);
    attachCodeCopyButtons(bodyDiv);
}

function renderAssistantMath(bodyDiv) {
    if (!bodyDiv) return;
    const mathJax = getMathJax();
    if (!mathJax) return;

    mathTypesetQueue = mathTypesetQueue
        .then(() => mathJax.startup?.promise)
        .then(() => {
            if (typeof mathJax.typesetClear === 'function') {
                mathJax.typesetClear([bodyDiv]);
            }
            return mathJax.typesetPromise([bodyDiv]);
        })
        .catch((error) => {
            console.warn('MathJax render failed:', error);
        });
}

function scheduleAssistantPostProcess(context, delayMs = 120) {
    if (!context || !context.bodyDiv) return;

    if (context.postProcessTimer) {
        clearTimeout(context.postProcessTimer);
    }

    context.postProcessTimer = window.setTimeout(() => {
        postProcessAssistantBody(context.bodyDiv);
        context.postProcessTimer = null;
        scrollChatToBottom();
    }, delayMs);
}

function flushAssistantPostProcess(context) {
    if (!context || !context.bodyDiv) return;

    if (context.postProcessTimer) {
        clearTimeout(context.postProcessTimer);
        context.postProcessTimer = null;
    }

    postProcessAssistantBody(context.bodyDiv);
}

// Add message to chat with copy controls
function addMessage(role, content, options = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex ${role === 'user' ? 'justify-end' : 'justify-start'}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = `max-w-[80%] px-4 py-2 rounded-lg message-bubble ${
        role === 'user'
            ? 'message-user'
            : role === 'error'
            ? 'state-surface-error border'
            : 'message-assistant prose prose-sm max-w-none'
    }`;

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'message-body';

    if (role === 'assistant') {
        renderAssistantHtml(bodyDiv, content);
        postProcessAssistantBody(bodyDiv);
    } else {
        const escapedContent = content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
        bodyDiv.innerHTML = escapedContent;
    }

    contentDiv.appendChild(bodyDiv);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'message-footer';

    const footerContent = document.createElement('div');
    footerContent.className = 'message-footer-content';

    if (role === 'assistant' && options.footerHtml) {
        footerContent.innerHTML = options.footerHtml;
    }

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-footer-actions';

    if (role === 'user' || role === 'error') {
        footerDiv.classList.add('message-footer-right');
    }

    const copyButton = createCopyButton(() => getCopyableText(bodyDiv), 'message-copy-button');
    actionsDiv.appendChild(copyButton);
    const forkButton = role === 'assistant' ? createForkButton(options.sequenceIndex) : null;
    if (forkButton) {
        actionsDiv.appendChild(forkButton);
    }

    if (footerContent.innerHTML.trim()) {
        footerDiv.appendChild(footerContent);
    } else {
        footerDiv.classList.add('message-footer-right');
    }

    footerDiv.appendChild(actionsDiv);
    contentDiv.appendChild(footerDiv);

    messageDiv.appendChild(contentDiv);

    appendChatMessageNode(messageDiv, { forceScroll: true });
}

function createAssistantStreamingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex justify-start';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'max-w-[80%] px-4 py-3 rounded-lg message-bubble message-assistant prose prose-sm max-w-none shadow-sm';

    const progressDiv = document.createElement('div');
    progressDiv.className = 'stream-progress';

    const indicator = document.createElement('div');
    indicator.className = 'stream-status-indicator typing';
    indicator.innerHTML = TYPING_DOTS_HTML;

    const statusText = document.createElement('span');
    statusText.className = 'stream-status-text';
    statusText.textContent = 'Assistant is responding 💬';

    progressDiv.appendChild(indicator);
    progressDiv.appendChild(statusText);

    const toolList = document.createElement('div');
    toolList.className = 'tool-status-list hidden';

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'message-body prose prose-sm max-w-none';
    bodyDiv.innerHTML = '';

    contentDiv.appendChild(progressDiv);
    contentDiv.appendChild(bodyDiv);
    messageDiv.appendChild(contentDiv);

    appendChatMessageNode(messageDiv, { forceScroll: true });

    return {
        messageDiv,
        contentDiv,
        progressDiv,
        indicator,
        statusText,
        bodyDiv,
        toolList,
        toolCallsSection: null,
        toolCallsSummaryTitle: null,
        toolStatusMap: new Map(),
        fullText: '',
        errorMessages: [],
        hasTools: false,
        toolSummary: null,
        postProcessTimer: null
    };
}

function ensureToolCallsSection(context) {
    if (context.toolCallsSection) {
        return context.toolCallsSection;
    }

    const section = document.createElement('details');
    section.className = 'tool-calls-section';

    const summary = document.createElement('summary');
    summary.className = 'tool-status-summary';

    const chevron = document.createElement('span');
    chevron.className = 'tool-status-chevron';
    chevron.textContent = '▸';

    const title = document.createElement('span');
    title.className = 'tool-status-title';
    title.textContent = 'Tool calls (0)';

    summary.appendChild(chevron);
    summary.appendChild(title);

    section.appendChild(summary);
    section.appendChild(context.toolList);
    context.contentDiv.appendChild(section);
    section.addEventListener('toggle', () => {
        chevron.textContent = section.open ? '▾' : '▸';
    });

    context.toolCallsSection = section;
    context.toolCallsSummaryTitle = title;
    return section;
}

function updateToolCallsSummary(context) {
    if (!context || !context.toolCallsSummaryTitle) {
        return;
    }

    const total = context.toolStatusMap.size;
    context.toolCallsSummaryTitle.textContent = `Tool calls (${total})`;
}

function renderAssistantMarkdown(context, options = {}) {
    const { finalize = false } = options;
    renderAssistantHtml(context.bodyDiv, context.fullText);
    if (finalize) {
        flushAssistantPostProcess(context);
    } else {
        scheduleAssistantPostProcess(context);
    }
    scrollChatToBottom();
}

function setAssistantStatus(context, label, state = 'thinking') {
    const emoji = STATUS_EMOJIS[state] || STATUS_EMOJIS.thinking;
    context.statusText.textContent = `${label} ${emoji}`;
    context.indicator.className = 'stream-status-indicator';
    if (state === 'thinking') {
        context.indicator.classList.add('typing');
        context.indicator.innerHTML = TYPING_DOTS_HTML;
        return;
    }

    const stateClass = state === 'tools'
        ? 'tool'
        : state === 'done'
        ? 'success'
        : state === 'error'
        ? 'error'
        : '';
    if (stateClass) {
        context.indicator.classList.add(stateClass);
    }
    context.indicator.textContent = emoji;
}

function handleToolEvent(context, payload) {
    const toolId = payload.tool_call_id || `tool-${context.toolStatusMap.size + 1}`;
    if (!toolId) return;

    let entry = context.toolStatusMap.get(toolId);

    if (payload.event === 'tool_call_started' || !entry) {
        ensureToolCallsSection(context);
        entry = createToolStatusEntry(context, toolId, payload);
        context.hasTools = true;
        if (payload.event === 'tool_call_started') {
            setAssistantStatus(context, 'Running tools', 'tools');
        }
    }

    if (payload.event === 'tool_call_finished') {
        entry.container.classList.remove('tool-status-running');
        entry.container.classList.add('tool-status-complete');
        if (payload.result !== undefined && payload.result !== null) {
            entry.result = payload.result;
        }
        updateToolDetail(entry);
        entry.chevron.textContent = entry.container.open ? '▾' : '▸';

        const hasRunning = Array.from(context.toolStatusMap.values())
            .some(item => item.container.classList.contains('tool-status-running'));
        if (!hasRunning) {
            setAssistantStatus(context, 'Continuing response', 'thinking');
        }
    } else if (payload.event === 'tool_call_started' && payload.arguments) {
        entry.args = payload.arguments;
        updateToolDetail(entry);
    }
    updateToolCallsSummary(context);
}

function createToolStatusEntry(context, toolId, payload) {
    const container = document.createElement('details');
    container.className = 'tool-status tool-status-running';

    const summary = document.createElement('summary');
    summary.className = 'tool-status-summary';

    const chevron = document.createElement('span');
    chevron.className = 'tool-status-chevron';
    chevron.textContent = '▸';

    const title = document.createElement('span');
    title.className = 'tool-status-title';
    title.textContent = payload.tool_name || 'Tool call';

    const body = document.createElement('div');
    body.className = 'tool-status-body';

    const detailContainer = document.createElement('div');
    detailContainer.className = 'tool-status-detail-container';
    body.appendChild(detailContainer);

    summary.appendChild(chevron);
    summary.appendChild(title);

    container.appendChild(summary);
    container.appendChild(body);

    container.addEventListener('toggle', () => {
        chevron.textContent = container.open ? '▾' : '▸';
    });

    context.toolList.classList.remove('hidden');
    context.toolList.appendChild(container);
    const entry = {
        container,
        summary,
        chevron,
        title,
        detailContainer,
        args: payload.arguments || null,
        result: null
    };
    updateToolDetail(entry);
    context.toolStatusMap.set(toolId, entry);

    return entry;
}

function finalizeAssistantMessage(context, metadata) {
    renderAssistantMarkdown(context, { finalize: true });

    const hasError = context.errorMessages.length > 0;
    const endedEarly = metadata.status && metadata.status !== 'done' && !hasError;

    if (hasError || endedEarly) {
        const finalLabel = hasError ? 'Completed with issues' : 'Response ended early';
        setAssistantStatus(context, finalLabel, 'error');
    } else if (context.progressDiv && context.progressDiv.parentNode) {
        context.progressDiv.parentNode.removeChild(context.progressDiv);
    }

    const footerDiv = document.createElement('div');
    footerDiv.className = 'message-footer';

    const footerContent = document.createElement('div');
    footerContent.className = 'message-footer-content';
    const hasToolSection = Boolean(context.toolCallsSection && context.toolStatusMap.size > 0);

    if (hasToolSection && context.toolCallsSection) {
        footerDiv.classList.add('message-footer-has-tools');
        footerContent.appendChild(context.toolCallsSection);
    }

    if (endedEarly && !hasError) {
        const span = document.createElement('span');
        span.textContent = 'Status: Partial output';
        footerContent.appendChild(span);
    } else if (hasError) {
        const span = document.createElement('span');
        span.textContent = 'Status: Needs review';
        footerContent.appendChild(span);
    }

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-footer-actions';

    const copyButton = createCopyButton(() => getCopyableText(context.bodyDiv), 'message-copy-button');
    actionsDiv.appendChild(copyButton);
    const forkButton = createForkButton(context.sequenceIndex);
    if (forkButton) {
        actionsDiv.appendChild(forkButton);
    }

    if (footerContent.childElementCount > 0) {
        footerDiv.appendChild(footerContent);
    } else {
        footerDiv.classList.add('message-footer-right');
    }
    footerDiv.appendChild(actionsDiv);
    context.contentDiv.appendChild(footerDiv);

    scrollChatToBottom();
}

function parseSseEvent(rawEvent) {
    if (!rawEvent) return null;

    const lines = rawEvent.split('\n');
    const dataLines = [];

    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('data:')) {
            dataLines.push(trimmed.slice(5).trim());
        }
    }

    if (!dataLines.length) {
        // Attempt to parse raw JSON as fallback
        try {
            return JSON.parse(rawEvent);
        } catch {
            return null;
        }
    }

    // Preserve SSE semantics: each `data:` line is joined with a newline.
    const dataPayload = dataLines.join('\n');
    if (!dataPayload) return null;

    try {
        return JSON.parse(dataPayload);
    } catch (error) {
        console.warn('Failed to parse SSE chunk:', dataPayload, error);
        return null;
    }
}

function formatToolDetail(value) {
    if (value === undefined || value === null) return '';
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function updateToolDetail(entry) {
    if (!entry || !entry.detailContainer) return;

    entry.detailContainer.innerHTML = '';

    const sections = [];
    if (entry.args) {
        sections.push({ label: 'Args', value: formatToolDetail(entry.args) });
    }
    if (entry.result) {
        sections.push({ label: 'Result', value: formatToolDetail(entry.result) });
    }

    if (sections.length) {
        sections.forEach(({ label, value }) => {
            entry.detailContainer.appendChild(createToolDetailSection(label, value));
        });
        return;
    }

    const placeholder = document.createElement('div');
    placeholder.className = 'tool-status-placeholder';
    placeholder.textContent = entry.container.classList.contains('tool-status-complete')
        ? 'No tool details available.'
        : 'Awaiting tool details…';
    entry.detailContainer.appendChild(placeholder);
}

function createToolDetailSection(label, value) {
    const section = document.createElement('div');
    section.className = 'tool-status-section';

    const heading = document.createElement('div');
    heading.className = 'tool-status-label';
    heading.textContent = label;

    const block = document.createElement('pre');
    block.className = 'tool-status-block';
    block.textContent = value;

    section.appendChild(heading);
    section.appendChild(block);
    return section;
}

function attachCodeCopyButtons(container) {
    const codeBlocks = container.querySelectorAll('pre');
    codeBlocks.forEach(pre => {
        if (pre.querySelector('.code-copy-button')) return;
        const copyButton = createCopyButton(() => getCopyableText(pre), 'code-copy-button');
        pre.appendChild(copyButton);
    });
}

function createCopyButton(getText, extraClass = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `copy-button ${extraClass}`.trim();
    button.setAttribute('aria-label', 'Copy to clipboard');
    button.title = 'Copy to clipboard';
    button.innerHTML = COPY_ICON_SVG;

    button.addEventListener('click', async (event) => {
        event.stopPropagation();
        const text = getText();
        if (!text) {
            flashCopyFeedback(button, false);
            return;
        }
        const didCopy = await handleCopy(text);
        flashCopyFeedback(button, didCopy);
    });

    return button;
}

function createForkButton(sequenceIndex) {
    if (!Number.isInteger(sequenceIndex) || sequenceIndex < 0) {
        return null;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy-button message-fork-button';
    button.setAttribute('aria-label', 'Fork session from this message');
    button.title = 'Fork session from this message';
    button.innerHTML = FORK_ICON_SVG;

    button.addEventListener('click', async (event) => {
        event.stopPropagation();
        await forkCurrentSession(sequenceIndex, button);
    });

    return button;
}

async function forkCurrentSession(sequenceIndex, button) {
    const vault = chatElements.vaultSelector.value;
    const sessionId = state.sessionId;
    if (state.isLoading || !vault || !sessionId || !Number.isInteger(sequenceIndex)) {
        return;
    }

    const previousDisabled = button.disabled;
    button.disabled = true;
    try {
        const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/fork`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vault_name: vault,
                through_sequence_index: sequenceIndex
            })
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
        const payload = await response.json();
        const forkSessionId = payload?.session?.session_id;
        if (!forkSessionId) {
            throw new Error('Fork response did not include a new session id.');
        }
        state.sessionId = forkSessionId;
        state.isWorkspaceUnlocked = false;
        await fetchSessions(vault, forkSessionId);
        await loadSession(forkSessionId);
    } catch (error) {
        console.error('Failed to fork chat session:', error);
        addChatErrorMessage(`Fork failed: ${error.message}`);
        button.disabled = previousDisabled;
    }
}

function getCopyableText(element) {
    const clone = element.cloneNode(true);
    clone.querySelectorAll('.copy-button').forEach(btn => btn.remove());
    return clone.innerText.trim();
}

async function handleCopy(text) {
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (err) {
        console.warn('navigator.clipboard.writeText failed', err);
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.left = '-1000px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    let didCopy = false;
    try {
        didCopy = document.execCommand('copy');
    } catch (err) {
        console.warn('document.execCommand copy failed', err);
    }

    document.body.removeChild(textarea);
    return didCopy;
}

function flashCopyFeedback(button, didCopy) {
    const originalLabel = button.innerHTML;
    const originalTitle = button.title;
    button.innerHTML = didCopy ? '✅' : '⚠️';
    button.title = didCopy ? 'Copied!' : 'Copy failed';
    button.disabled = true;

    setTimeout(() => {
        button.innerHTML = originalLabel;
        button.title = originalTitle;
        button.disabled = false;
    }, 1200);
}

// Clear session
function updateSessionTitleRow() {
    const row = chatElements.sessionTitleRow;
    const input = chatElements.sessionTitleInput;
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

async function saveSessionTitle() {
    const sessionId = state.sessionId;
    const vault = chatElements.vaultSelector?.value || '';
    const input = chatElements.sessionTitleInput;
    const btn = chatElements.sessionTitleSave;
    if (!sessionId || !vault || !input || !btn) return;

    const title = input.value.trim() || null;
    btn.disabled = true;
    try {
        const response = await fetch(`api/chat/sessions/${encodeURIComponent(sessionId)}/title`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vault_name: vault, title }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        // Update local state so the picker label refreshes immediately
        const session = state.sessions.find((s) => s.session_id === sessionId);
        if (session) session.title = title;
        renderSessionSelector();
    } catch (error) {
        console.error('Failed to save session title:', error);
    } finally {
        btn.disabled = false;
    }
}

async function exportCurrentSession() {
    const sessionId = state.sessionId;
    const vault = chatElements.vaultSelector?.value || '';
    const btn = chatElements.sessionExportBtn;
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
        syncChatControlLocks();
    }
}

async function deleteCurrentSession() {
    const sessionId = state.sessionId;
    const vault = chatElements.vaultSelector?.value || '';
    const btn = chatElements.sessionDeleteBtn;
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
        clearPendingAttachments();
        renderChatEmptyState();
        renderSessionSelector();
        updateSessionTitleRow();
        syncChatControlLocks();
        updateStatus();
    } catch (error) {
        console.error('Failed to delete session:', error);
    } finally {
        btn.disabled = false;
    }
}

async function clearSession(confirmReset = true) {
    const confirmed = confirmReset
        ? window.confirm('Do you want to start a new chat session? The current session remains available in chat history unless you delete it.')
        : true;
    if (!confirmed) return;

    state.sessionId = null;
    state.isWorkspaceUnlocked = false;
    if (chatElements.workspacePathInput) {
        chatElements.workspacePathInput.value = '';
    }
    clearCompactionProgress();
    clearPendingAttachments();
    renderChatEmptyState();
    renderSessionSelector();
    updateSessionTitleRow();
    syncChatControlLocks();
    updateStatus();
}

// Rescan vaults
async function rescanVaults() {
    if (!dashElements.rescanResult) return;

    dashElements.rescanResult.innerHTML = '<p class="text-txt-secondary">Rescanning...</p>';
    dashElements.rescanBtn.disabled = true;

    try {
        const response = await fetch('api/vaults/rescan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        if (data.metadata) {
            state.metadata = data.metadata;
            window.App = window.App || {};
            window.App.metadata = data.metadata;
            populateSelectors();
        } else {
            await fetchMetadata();
        }

        await fetchSystemStatus();
        renderRescanResult(data);

    } catch (error) {
        console.error('Error rescanning:', error);
        dashElements.rescanResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
    } finally {
        dashElements.rescanBtn.disabled = false;
    }
}

function renderRescanResult(data) {
    if (!dashElements.rescanResult) return;

    const configurationErrors = state.systemStatus?.configuration_errors || [];
    const workflowErrors = configurationErrors.filter((error) => {
        const filePath = String(error.file_path || '');
        return filePath.includes('/AssistantMD/Workflows/');
    });

    dashElements.rescanResult.innerHTML = `
        <div class="state-surface-success p-3 rounded border">
            <p class="font-medium">✅ Rescan Completed</p>
            <p>Vaults discovered: ${data.vaults_discovered || 0}</p>
            <p>Workflows loaded: ${data.workflows_loaded || 0}</p>
            <p>Enabled workflows: ${data.enabled_workflows || 0}</p>
            <p>Scheduler jobs synced: ${data.scheduler_jobs_synced || 0}</p>
            <p class="mt-2 text-sm">${data.message || ''}</p>
        </div>
        ${workflowErrors.length ? `
            <div class="state-surface-error p-3 rounded border mt-3">
                <p class="font-medium">⚠️ Workflows Failed To Load</p>
                <ul class="list-disc list-inside mt-2 space-y-1">
                    ${workflowErrors.map((error) => `
                        <li>
                            <span class="font-medium">${escapeHtml(error.workflow_name || error.file_path || 'workflow')}</span>:
                            ${escapeHtml(error.error_message || 'Unknown load error')}
                        </li>
                    `).join('')}
                </ul>
            </div>
        ` : ''}
    `;
}

// Execute workflow manually
async function toggleWorkflowEnabled(globalId, enabled, triggerButton = null) {
    if (!globalId) {
        return;
    }

    if (triggerButton) {
        triggerButton.disabled = true;
    }

    try {
        const response = await fetch('api/workflows/enabled', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ global_id: globalId, enabled })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        const data = await response.json();
        dashElements.executeWorkflowResult.innerHTML = `
            <div class="state-surface-success p-3 rounded border">
                <p class="font-medium">${escapeHtml(data.message || 'Workflow updated.')}</p>
            </div>
        `;
        await fetchSystemStatus();
    } catch (error) {
        console.error('Error updating workflow enabled state:', error);
        dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
    } finally {
        if (triggerButton) {
            triggerButton.disabled = false;
        }
    }
}

async function openWorkflowFileEditor(globalId) {
    if (!globalId) {
        return;
    }

    closeWorkflowFileEditor();
    const overlay = document.createElement('div');
    overlay.id = 'workflow-file-modal';
    overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
    overlay.innerHTML = `
        <div class="absolute inset-0" data-workflow-file-close="true"></div>
        <section class="app-modal-panel relative flex flex-col" role="dialog" aria-modal="true" aria-labelledby="workflow-file-modal-title">
            <div class="app-modal-header flex-none">
                <div class="app-modal-title-block">
                    <h2 id="workflow-file-modal-title" class="text-lg font-semibold text-txt-primary">Workflow: ${escapeHtml(globalId)}</h2>
                    <p id="workflow-file-modal-path" class="mt-1 text-xs text-txt-secondary cell-mono">Loading...</p>
                </div>
                <div class="app-modal-actions">
                    <button type="button" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-70 disabled:cursor-not-allowed" data-workflow-file-save="true" disabled>
                        Save
                    </button>
                    <button type="button" class="px-3 py-1.5 text-sm bg-app-elevated border border-border-primary text-txt-primary rounded-md hover:bg-app-card focus:outline-none focus:ring-2 focus:ring-accent" data-workflow-file-close="true">
                        Close
                    </button>
                </div>
            </div>
            <div class="p-4 space-y-3 flex-1 min-h-0 flex flex-col">
                <div id="workflow-file-modal-status" class="text-sm text-txt-secondary">Loading workflow file...</div>
                <textarea
                    id="workflow-file-modal-editor"
                    class="w-full flex-1 min-h-0 px-3 py-2 border border-border-secondary rounded-md bg-app-bg text-txt-primary font-mono text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                    spellcheck="false"
                    disabled
                ></textarea>
            </div>
        </section>
    `;
    document.body.appendChild(overlay);

    const editor = overlay.querySelector('#workflow-file-modal-editor');
    const pathLabel = overlay.querySelector('#workflow-file-modal-path');
    const statusLabel = overlay.querySelector('#workflow-file-modal-status');
    const saveButton = overlay.querySelector('[data-workflow-file-save]');
    let sha256 = '';

    overlay.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        if (target.dataset.workflowFileClose === 'true') {
            closeWorkflowFileEditor();
            return;
        }
        if (target.dataset.workflowFileSave === 'true' && editor instanceof HTMLTextAreaElement) {
            saveButton.disabled = true;
            statusLabel.textContent = 'Saving...';
            try {
                const response = await fetch(`api/workflows/file?global_id=${encodeURIComponent(globalId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        content: editor.value,
                        expected_sha256: sha256
                    })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                const data = await response.json();
                sha256 = data.sha256 || '';
                statusLabel.textContent = data.message || 'Saved.';
                await fetchSystemStatus();
                saveButton.disabled = false;
            } catch (error) {
                console.error('Error saving workflow file:', error);
                statusLabel.innerHTML = `<span class="state-error">Error: ${escapeHtml(error.message)}</span>`;
                saveButton.disabled = false;
            }
        }
    });

    try {
        const response = await fetch(`api/workflows/file?global_id=${encodeURIComponent(globalId)}`);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
        const data = await response.json();
        sha256 = data.sha256 || '';
        if (pathLabel) {
            pathLabel.textContent = data.path || '';
        }
        if (editor instanceof HTMLTextAreaElement) {
            editor.value = data.content || '';
            editor.disabled = false;
        }
        if (statusLabel) {
            statusLabel.textContent = `Editing ${data.source || 'workflow'} workflow file.`;
        }
        if (saveButton instanceof HTMLButtonElement) {
            saveButton.disabled = false;
        }
    } catch (error) {
        console.error('Error loading workflow file:', error);
        if (statusLabel) {
            statusLabel.innerHTML = `<span class="state-error">Error: ${escapeHtml(error.message)}</span>`;
        }
    }
}

function closeWorkflowFileEditor() {
    document.getElementById('workflow-file-modal')?.remove();
}

async function executeWorkflow(globalId, triggerButton = null, isSystemTemplate = false) {
    if (!globalId) {
        return;
    }

    const selectedVault = chatElements.vaultSelector?.value || '';
    const scopeLabel = isSystemTemplate
        ? ` for vault "${selectedVault || '(none selected)'}"`
        : '';
    const confirmed = window.confirm(`Run workflow "${globalId}"${scopeLabel}?`);
    if (!confirmed) {
        return;
    }
    if (isSystemTemplate && !selectedVault) {
        dashElements.executeWorkflowResult.innerHTML = '<p class="state-error">Select a vault before running a system workflow.</p>';
        return;
    }

    dashElements.executeWorkflowResult.innerHTML = '<p class="text-txt-secondary">Starting workflow...</p>';
    if (triggerButton) {
        triggerButton.disabled = true;
    }

    try {
        const payload = { global_id: globalId };
        if (isSystemTemplate) {
            payload.vault_name = selectedVault;
        }

        const response = await fetch('api/workflows/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const task = data.task || {};
        if (!task.task_id) {
            throw new Error('Workflow did not return an execution task.');
        }
        await fetchWorkflowTasks({ render: true });
        dashElements.executeWorkflowResult.innerHTML = `
            <div class="state-surface-info p-3 rounded border">
                <p class="font-medium">Workflow started</p>
                <p>Workflow: ${escapeHtml(globalId)}</p>
                <p class="text-sm">Task: ${escapeHtml(task.task_id)}</p>
                <p class="text-sm">Use the Running Workflows list to monitor or stop this task.</p>
            </div>
        `;
        monitorWorkflowTask(task.task_id);
    } catch (error) {
        console.error('Error executing workflow:', error);
        dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
        displaySystemStatus();
    } finally {
        if (triggerButton) {
            triggerButton.disabled = false;
        }
    }
}

async function monitorWorkflowTask(taskId) {
    if (!taskId) return;
    try {
        while (true) {
            await new Promise(resolve => window.setTimeout(resolve, 1000));
            const response = await fetch(`api/tasks/${encodeURIComponent(taskId)}`);
            if (!response.ok) {
                return;
            }
            const task = await response.json();
            if (!isTerminalTaskStatus(task.status)) {
                continue;
            }
            await fetchWorkflowTasks({ render: true });
            renderWorkflowTaskResult(task);
            return;
        }
    } catch (error) {
        console.error('Error monitoring workflow task:', error);
    }
}

async function stopWorkflow(taskId, triggerButton = null) {
    if (!taskId) return;
    if (triggerButton) {
        triggerButton.disabled = true;
        triggerButton.textContent = 'Stopping...';
    }
    try {
        const response = await fetch(`api/tasks/${encodeURIComponent(taskId)}/cancel`, {
            method: 'POST'
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }
        dashElements.executeWorkflowResult.innerHTML = `
            <div class="state-surface-info p-3 rounded border">
                <p class="font-medium">Stop requested</p>
                <p class="text-sm">Task: ${escapeHtml(taskId)}</p>
                <p class="text-sm">Files mutated by this workflow will be rolled back when cancellation completes.</p>
            </div>
        `;
        await fetchWorkflowTasks({ render: true });
    } catch (error) {
        console.error('Error stopping workflow:', error);
        dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
        if (triggerButton) {
            triggerButton.disabled = false;
            triggerButton.textContent = 'Stop';
        }
    }
}

async function stopAllWorkflows(triggerButton = null) {
    const tasks = activeWorkflowTasks();
    if (!tasks.length) {
        dashElements.executeWorkflowResult.innerHTML = '<p class="text-sm text-txt-secondary">No running workflows to stop.</p>';
        return;
    }
    const confirmed = window.confirm(`Stop ${tasks.length} running workflow task${tasks.length === 1 ? '' : 's'}?`);
    if (!confirmed) {
        return;
    }
    if (triggerButton) {
        triggerButton.disabled = true;
        triggerButton.textContent = 'Stopping...';
    }
    try {
        const results = await Promise.allSettled(
            tasks.map(task => fetch(`api/tasks/${encodeURIComponent(task.task_id)}/cancel`, { method: 'POST' }))
        );
        const failures = [];
        for (const result of results) {
            if (result.status === 'rejected') {
                failures.push(result.reason?.message || 'request failed');
                continue;
            }
            if (!result.value.ok) {
                failures.push(`HTTP ${result.value.status}`);
            }
        }
        await fetchWorkflowTasks({ render: true });
        if (failures.length) {
            dashElements.executeWorkflowResult.innerHTML = `
                <p class="state-error">Stop requested for ${tasks.length - failures.length} workflow task${tasks.length - failures.length === 1 ? '' : 's'}, but ${failures.length} failed.</p>
            `;
            return;
        }
        dashElements.executeWorkflowResult.innerHTML = `
            <div class="state-surface-info p-3 rounded border">
                <p class="font-medium">Stop requested for all running workflows</p>
                <p class="text-sm">${tasks.length} workflow task${tasks.length === 1 ? '' : 's'} will stop and roll back mutated files where applicable.</p>
            </div>
        `;
    } catch (error) {
        console.error('Error stopping all workflows:', error);
        dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
    } finally {
        if (triggerButton) {
            triggerButton.disabled = false;
            triggerButton.textContent = 'Stop All';
        }
    }
}

function renderWorkflowTaskResult(task) {
    const result = task?.metadata?.workflow_result || null;
    const status = String(task?.status || '').toLowerCase();
    const success = status === 'completed' && (!result || result.success !== false);
    const surfaceClass = success ? 'state-surface-success' : 'state-surface-error';
    const heading = success ? '✅ Execution Completed' : `Workflow ${status || 'finished'}`;
    const outputFiles = result?.output_files || [];
    dashElements.executeWorkflowResult.innerHTML = `
        <div class="${surfaceClass} p-3 rounded border">
            <p class="font-medium">${escapeHtml(heading)}</p>
            <p>Workflow: ${escapeHtml(result?.global_id || task?.metadata?.workflow_id || task?.label || '')}</p>
            ${typeof result?.execution_time_seconds === 'number'
                ? `<p>Execution time: ${result.execution_time_seconds.toFixed(2)}s</p>`
                : ''}
            ${outputFiles.length ? `
                <p class="mt-2">Output files created:</p>
                <ul class="list-disc list-inside ml-4">
                    ${outputFiles.map(f => `<li class="text-sm">${escapeHtml(f)}</li>`).join('')}
                </ul>
            ` : ''}
            <p class="mt-2 text-sm">${escapeHtml(result?.message || task?.terminal_reason || '')}</p>
        </div>
    `;
}

function isTerminalTaskStatus(status) {
    return ['completed', 'failed', 'cancelled', 'timed_out', 'skipped'].includes(
        String(status || '').toLowerCase()
    );
}

function updateStatus(message) {
    if (!configElements.statusBanner || !configElements.statusMessages || !configElements.configTab) return;

    const warnings = getConfigurationWarnings();
    const noticeLines = [];
    let repairNeeded = false;

    if (state.restartRequired) {
        noticeLines.push(RESTART_NOTICE_TEXT);
    }

    warnings.forEach((issue) => {
        noticeLines.push(issue.message);
        if (issue.name && /^(settings|models|providers|tools):(missing|extra)$/.test(issue.name)) {
            repairNeeded = true;
        }
    });

    // Check for no vaults
    if (state.metadata && state.metadata.vaults && state.metadata.vaults.length === 0) {
        noticeLines.push('No vaults found. Review installation instructions.');
    }

    // Update System tab and banner
    if (noticeLines.length === 0) {
        // No warnings - hide banner and remove tab highlight
        configElements.statusBanner.classList.add('hidden');
        configElements.statusMessages.innerHTML = '';
        configElements.configTab.classList.remove('font-semibold', 'bg-app-elevated', 'px-3', 'rounded-t-md', 'text-accent');
        configElements.configTab.classList.add('text-txt-secondary');
        configElements.configTab.style.borderColor = '';
        configElements.configTab.textContent = 'System';
    } else {
        // Show warnings in banner and highlight tab with background
        configElements.statusBanner.classList.remove('hidden');
        let messageHtml = noticeLines.map(line => `<div>• ${line}</div>`).join('');
        if (repairNeeded) {
            messageHtml += `
                <div class="mt-2">
                    <button id="repair-settings-btn" type="button" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60">
                        Repair settings from template
                    </button>
                </div>
            `;
        }
        configElements.statusMessages.innerHTML = messageHtml;
        configElements.configTab.classList.remove('text-txt-secondary', 'text-txt-primary');
        configElements.configTab.classList.add('text-accent', 'font-semibold', 'bg-app-elevated', 'px-3', 'rounded-t-md');
        configElements.configTab.style.borderColor = 'rgb(var(--border-primary))';
        configElements.configTab.textContent = 'System ⚠️';
        const repairBtn = document.getElementById('repair-settings-btn');
        if (repairBtn) {
            repairBtn.addEventListener('click', async () => {
                const confirmed = window.confirm(
                    'Repair settings from template?\n\nThis will add missing keys from settings.template.yaml, prune unknown settings, and remove unknown non-user-editable tools/models/providers. Existing values for matching keys will be preserved.\nA backup will be written to system/settings.bak. Reload the page after repair to see changes.'
                );
                if (!confirmed) return;

                repairBtn.disabled = true;
                repairBtn.textContent = 'Repairing…';
                let alertEl = document.getElementById('config-repair-alert');
                if (!alertEl && configElements.statusMessages) {
                    alertEl = document.createElement('div');
                    alertEl.id = 'config-repair-alert';
                    alertEl.className = 'mt-2 text-sm';
                    configElements.statusMessages.appendChild(alertEl);
                }
                const showAlert = (text, tone = 'info') => {
                    if (!alertEl) return;
                    alertEl.textContent = text;
                    alertEl.className = `mt-2 text-sm ${tone === 'error' ? 'state-error' : 'text-txt-secondary'}`;
                };
                try {
                    const resp = await fetch('api/system/settings/repair', { method: 'POST' });
                    if (!resp.ok) throw new Error(await resp.text() || 'Repair failed');
                    await fetchSystemStatus();
                    showAlert('Settings repaired. Backup saved to system/settings.bak. Reload the page to see new defaults.', 'info');
                } catch (err) {
                    console.error('Settings repair failed', err);
                    showAlert('Settings repair failed: ' + err.message, 'error');
                } finally {
                    repairBtn.disabled = false;
                    repairBtn.textContent = 'Repair settings from template';
                }
            });
        }
    }
}

function setRestartRequired(required = true) {
    const currentStartup = state.systemStatus?.system?.startup_time || null;

    if (!required) {
        state.restartRequired = false;
        localStorage.removeItem(RESTART_STORAGE_KEY);
        if (window.ConfigurationPanel && typeof window.ConfigurationPanel.setRestartRequired === 'function') {
            window.ConfigurationPanel.setRestartRequired(false);
        }
        updateStatus();
        return;
    }

    const payload = { required: true, startupTime: currentStartup };
    try {
        localStorage.setItem(RESTART_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
        console.warn('Failed to persist restart-required flag:', error);
    }

    state.restartRequired = true;
    if (window.ConfigurationPanel && typeof window.ConfigurationPanel.setRestartRequired === 'function') {
        window.ConfigurationPanel.setRestartRequired(true);
    }
    updateStatus();
}

function syncRestartFlagWithStorage() {
    let stored = null;
    try {
        const raw = localStorage.getItem(RESTART_STORAGE_KEY);
        stored = raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.warn('Failed to read restart-required flag:', error);
        localStorage.removeItem(RESTART_STORAGE_KEY);
    }

    const currentStartup = state.systemStatus?.system?.startup_time || null;

    const isValid = stored && stored.required && (!stored.startupTime || stored.startupTime === currentStartup);

    if (isValid) {
        if (currentStartup && stored.startupTime !== currentStartup) {
            try {
                localStorage.setItem(RESTART_STORAGE_KEY, JSON.stringify({ required: true, startupTime: currentStartup }));
            } catch (error) {
                console.warn('Failed to update restart-required flag:', error);
            }
        }
        if (!state.restartRequired) {
            state.restartRequired = true;
            if (window.ConfigurationPanel && typeof window.ConfigurationPanel.setRestartRequired === 'function') {
                window.ConfigurationPanel.setRestartRequired(true);
            }
            updateStatus();
        }
        return;
    }

    if (state.restartRequired) {
        state.restartRequired = false;
        if (window.ConfigurationPanel && typeof window.ConfigurationPanel.setRestartRequired === 'function') {
            window.ConfigurationPanel.setRestartRequired(false);
        }
        updateStatus();
    }

    localStorage.removeItem(RESTART_STORAGE_KEY);
}

// Start app
window.App = window.App || {};
window.App.setRestartRequired = setRestartRequired;

init();
