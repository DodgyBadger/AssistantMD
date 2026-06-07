const {
    SESSION_SUMMARY_ICON_SVG,
} = window.AssistantMDIcons;

const {
    escapeHtml,
    truncateText,
    formatShortDate,
} = window.AssistantMDUtils;

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

const chatRendering = window.ChatRendering.create({
    state,
    elements: chatElements,
    icons: window.AssistantMDIcons,
    utils: window.AssistantMDUtils,
    callbacks: {
        scrollChatToBottom,
        fetchSessions,
        loadSession,
    },
});

const vaultActivity = window.VaultActivity.create({
    state,
    elements: dashElements,
    utils: window.AssistantMDUtils,
    callbacks: {
        formatChatSessionLabel: (session) => sessionControls.formatOptionLabel(session),
    },
});

let dashboardView;

const workflowActions = window.WorkflowActions.create({
    state,
    elements: dashElements,
    utils: window.AssistantMDUtils,
    callbacks: {
        fetchMetadata,
        populateSelectors,
        fetchSystemStatus,
        fetchWorkflowTasks,
        displaySystemStatus,
        isTerminalTaskStatus,
        activeWorkflowTasks: () => dashboardView.activeWorkflowTasks(),
        selectedVault: () => chatElements.vaultSelector?.value || '',
    },
});

dashboardView = window.DashboardView.create({
    state,
    elements: dashElements,
    utils: window.AssistantMDUtils,
    callbacks: {
        renderVaultActivityResult: vaultActivity.renderResult,
        loadVaultActivity: vaultActivity.loadActivity,
        fetchWorkflowTasks,
        isTerminalTaskStatus,
        openWorkflowFileEditor: workflowActions.openFileEditor,
        toggleWorkflowEnabled: workflowActions.toggleWorkflowEnabled,
        executeWorkflow: workflowActions.executeWorkflow,
        stopWorkflow: workflowActions.stopWorkflow,
        stopAllWorkflows: workflowActions.stopAllWorkflows,
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

function renderChatEmptyState(message) {
    chatRendering.renderEmptyState(message);
}

function addChatErrorMessage(errorText) {
    chatRendering.addErrorMessage(errorText);
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
    chatRendering.renderPersistedSession(payload);
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

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        if (state.isChatFocusMode) {
            setChatFocusMode(false);
            return;
        }
        workspacePicker.closeModal();
        vaultActivity.closeDetails();
    }
});

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
        dashElements.rescanBtn.addEventListener('click', workflowActions.rescanVaults);
    }

    dashboardView.attachEventListeners();
    vaultActivity.attachEventListeners();

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

function addLoadingMessage() {
    return chatRendering.addLoadingMessage();
}

function removeLoadingMessage(messageDiv) {
    chatRendering.removeLoadingMessage(messageDiv);
}

function addMessage(role, content, options = {}) {
    chatRendering.addMessage(role, content, options);
}

function createAssistantStreamingMessage() {
    return chatRendering.createAssistantStreamingMessage();
}

function renderAssistantMarkdown(context, options = {}) {
    chatRendering.renderAssistantMarkdown(context, options);
}

function setAssistantStatus(context, label, state = 'thinking') {
    chatRendering.setAssistantStatus(context, label, state);
}

function handleToolEvent(context, payload) {
    chatRendering.handleToolEvent(context, payload);
}

function finalizeAssistantMessage(context, metadata) {
    chatRendering.finalizeAssistantMessage(context, metadata);
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
