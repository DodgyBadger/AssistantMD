const {
    COPY_ICON_SVG,
    FORK_ICON_SVG,
    SESSION_SUMMARY_ICON_SVG,
    TYPING_DOTS_HTML,
} = window.AssistantMDIcons;

const {
    escapeHtml,
    truncateText,
    formatShortDate,
    getCopyableText,
    handleCopy,
    flashCopyFeedback,
} = window.AssistantMDUtils;

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

let sessionControls;

const sessionSummary = window.SessionSummary.create({
    state,
    elements: chatElements,
    icons: window.AssistantMDIcons,
    utils: window.AssistantMDUtils,
    callbacks: {
        renderSessionSelector: () => sessionControls.renderSelector(),
        fetchSessions,
    },
});

const workspacePicker = window.WorkspacePicker.create({
    state,
    elements: chatElements,
    utils: window.AssistantMDUtils,
    callbacks: {
        fetchSessions,
        addChatErrorMessage,
    },
});

sessionControls = window.SessionControls.create({
    state,
    elements: chatElements,
    composeState: chatComposeState,
    utils: window.AssistantMDUtils,
    sessionSummary,
    callbacks: {
        loadSession,
        clearSession,
        clearPendingAttachments,
        renderChatEmptyState,
        syncChatControlLocks,
        updateStatus,
    },
});

const dashboardView = window.DashboardView.create({
    state,
    elements: dashElements,
    utils: window.AssistantMDUtils,
    callbacks: {
        renderVaultActivityResult,
        loadVaultActivity,
        fetchWorkflowTasks,
        isTerminalTaskStatus,
        openWorkflowFileEditor,
        toggleWorkflowEnabled,
        executeWorkflow,
        stopWorkflow,
        stopAllWorkflows,
    },
});

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
    workspacePicker.syncControls();
    syncSendButtonState();
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

async function fetchSessions(vault, preferredSessionId = '') {
    state.sessions = [];
    sessionControls.renderSelector();
    if (!vault) {
        sessionControls.clearCompactionProgress();
        return;
    }
    try {
        const response = await fetch(`api/chat/sessions?vault_name=${encodeURIComponent(vault)}`);
        if (!response.ok) {
            throw new Error('Failed to fetch chat sessions');
        }
        state.sessions = await response.json();
        sessionControls.renderSelector();
        if (preferredSessionId && state.sessions.some((session) => session.session_id === preferredSessionId)) {
            state.sessionId = preferredSessionId;
            sessionControls.renderSelector();
        }
        await sessionControls.refreshCompactionProgress();
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
        sessionControls.renderSelector();
        sessionControls.refreshCompactionProgress();
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
        sessionControls.renderSelector();
        sessionControls.updateTitleRow();
        updateStatus();
        await sessionControls.refreshCompactionProgress();
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
    sessionControls.renderSelector();
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
        dashboardView.syncWorkflowTaskPolling();
        if (render) {
            displaySystemStatus();
        }
    } catch (error) {
        console.error('Error fetching workflow tasks:', error);
        state.workflowTasks = [];
        dashboardView.syncWorkflowTaskPolling();
        if (render && dashElements.executeWorkflowResult) {
            dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
        }
    }
}

function displaySystemStatus() {
    dashboardView.displaySystemStatus();
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
    return sessionControls.formatOptionLabel(session);
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
        workspacePicker.closeModal();
        closeVaultActivityDetails();
    }
});

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

    sessionControls.attachEventListeners();

    if (chatElements.workspacePathInput) {
        chatElements.workspacePathInput.addEventListener('input', () => {
            workspacePicker.syncControls();
        });
        chatElements.workspacePathInput.addEventListener('blur', workspacePicker.savePath);
        chatElements.workspacePathInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                workspacePicker.savePath();
            }
        });
    }

    if (chatElements.workspacePickerBtn) {
        chatElements.workspacePickerBtn.addEventListener('click', workspacePicker.openModal);
    }

    if (chatElements.workspaceUnlockBtn) {
        chatElements.workspaceUnlockBtn.addEventListener('click', workspacePicker.unlockPath);
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
                sessionControls.setMenuOpen(false);
                sessionSummary.closePreview();
            }
        }
    });

    if (dashElements.rescanBtn) {
        dashElements.rescanBtn.addEventListener('click', rescanVaults);
    }

    dashboardView.attachEventListeners();

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
    sessionControls.clearCompactionProgress();
    sessionControls.renderSelector();
    sessionControls.updateTitleRow();
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
    const workspacePathValue = workspacePicker.currentPath() || null;
    const requestSessionId = state.sessionId || createClientSessionId(vault);
    state.sessionId = requestSessionId;
    state.isWorkspaceUnlocked = false;
    sessionControls.renderSelector();
    sessionControls.updateTitleRow();
    sessionControls.refreshCompactionProgress();
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
            sessionControls.renderSelector();
            sessionControls.updateTitleRow();
            sessionControls.refreshCompactionProgress();
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
        sessionControls.refreshCompactionProgress();
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
    statusText.textContent = 'Assistant is responding';

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
    context.statusText.textContent = label;
    context.indicator.className = 'stream-status-indicator';
    if (state === 'thinking') {
        context.indicator.classList.add('typing');
        context.indicator.innerHTML = TYPING_DOTS_HTML;
        return;
    }
    context.indicator.classList.add('hidden');
    context.indicator.innerHTML = '';
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

// Clear session

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
    sessionControls.clearCompactionProgress();
    clearPendingAttachments();
    renderChatEmptyState();
    sessionControls.renderSelector();
    sessionControls.updateTitleRow();
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
    const tasks = dashboardView.activeWorkflowTasks();
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
