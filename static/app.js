// Shared SVG icon for copy buttons
const COPY_ICON_SVG = `
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <rect x="6.5" y="6.5" width="9" height="9" rx="2" stroke="currentColor" stroke-width="1.4"></rect>
        <rect x="4.5" y="4.5" width="9" height="9" rx="2" stroke="currentColor" stroke-width="1.4" opacity="0.85"></rect>
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

// State management
const RESTART_NOTICE_TEXT = 'Restart the container to apply changes.';
const RESTART_STORAGE_KEY = 'assistantmd_restart_required';

const state = {
    sessionId: null,
    metadata: null,
    isLoading: false,
    systemStatus: null,
    restartRequired: false,
    shouldAutoScroll: true
};

// DOM elements - Chat
const chatElements = {
    vaultSelector: document.getElementById('vault-selector'),
    modelSelector: document.getElementById('model-selector'),
    templateSelector: document.getElementById('template-selector'),
    toolsCheckboxes: document.getElementById('tools-checkboxes'),
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    sendBtn: document.getElementById('send-btn'),
    newSessionBtn: document.getElementById('new-session-btn')
};

// DOM elements - Dashboard
const dashElements = {
    systemStatus: document.getElementById('system-status'),
    rescanBtn: document.getElementById('rescan-btn'),
    rescanResult: document.getElementById('rescan-result'),
    workflowSelector: document.getElementById('workflow-selector'),
    stepNameInput: document.getElementById('step-name-input'),
    executeWorkflowBtn: document.getElementById('execute-workflow-btn'),
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

function handleChatScroll() {
    const container = chatElements.chatMessages;
    if (!container) return;
    state.shouldAutoScroll = isChatNearBottom(container);
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
    if (window.ConfigurationPanel) {
        window.ConfigurationPanel.init({
            refreshMetadata: () => fetchMetadata(),
            refreshStatus: () => fetchSystemStatus()
        });
    }
    await fetchMetadata();
    await fetchSystemStatus();
    setupEventListeners();
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
    chatElements.vaultSelector.innerHTML = '<option value="">Select vault...</option>';
    chatElements.modelSelector.innerHTML = '<option value="">Select model...</option>';
    chatElements.toolsCheckboxes.innerHTML = '';
    if (chatElements.templateSelector) {
        chatElements.templateSelector.innerHTML = '<option value="">Select template...</option>';
        chatElements.templateSelector.disabled = true;
    }

    state.metadata.vaults.forEach(vault => {
        const option = document.createElement('option');
        option.value = vault;
        option.textContent = vault;
        chatElements.vaultSelector.appendChild(option);
    });

    let firstAvailableModel = null;
    const envDefaultModel = state.systemStatus && state.systemStatus.configuration_status
        ? state.systemStatus.configuration_status.default_model
        : null;

    state.metadata.models.forEach(model => {
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

    if (envDefaultModel && state.metadata.models.some(m => m.name === envDefaultModel && m.available)) {
        chatElements.modelSelector.value = envDefaultModel;
    } else if (firstAvailableModel) {
        chatElements.modelSelector.value = firstAvailableModel;
    }

    // Trigger template fetch if a vault is already selected (e.g., persisted UI state in future)
    if (chatElements.vaultSelector && chatElements.vaultSelector.value) {
        fetchTemplates(chatElements.vaultSelector.value);
    }

    const preferredWebTool = (['web_search_tavily', 'web_search_duckduckgo']
        .map(name => state.metadata.tools.find(tool => tool.name === name && tool.available !== false))
        .find(Boolean)?.name) || null;

    const toolMap = new Map(state.metadata.tools.map(tool => [tool.name, tool]));
    const handledTools = new Set();

    const createToolElement = (tool) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'tool-checkbox-wrapper';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `tool-${tool.name}`;
        checkbox.value = tool.name;
        checkbox.disabled = tool.available === false;

        if (
            !checkbox.disabled &&
            (
                tool.name === 'file_ops_safe' ||
                tool.name === 'buffer_ops' ||
                (preferredWebTool && tool.name === preferredWebTool)
            )
        ) {
            checkbox.checked = true;
        }

        const label = document.createElement('label');
        label.htmlFor = `tool-${tool.name}`;
        label.textContent = `${tool.name}${checkbox.disabled ? ' (unavailable)' : ''}`;

        const description = tool.description ? String(tool.description).trim() : '';
        if (description) {
            label.title = description;
        }

        if (tool.name === 'buffer_ops' && state.metadata.settings?.auto_buffer_max_tokens > 0) {
            checkbox.checked = true;
            checkbox.disabled = true;
            label.title = description
                ? `${description} Auto-enabled because auto_buffer_max_tokens is set.`
                : 'Auto-enabled because auto_buffer_max_tokens is set.';
        }

        wrapper.appendChild(checkbox);
        wrapper.appendChild(label);
        return wrapper;
    };

    const toolOrder = [
        'web_search_duckduckgo',
        'web_search_tavily',
        'file_ops_safe',
        'file_ops_unsafe',
        'buffer_ops',
        'documentation_access',
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
            const availableModels = state.metadata.models.filter(m => m.available !== false);
            const firstAvailableModel = availableModels.length ? availableModels[0].name : null;
            const currentValue = chatElements.modelSelector.value;
            const hasEnvDefault = availableModels.some(m => m.name === envDefaultModel);
            if (hasEnvDefault && (!currentValue || currentValue === firstAvailableModel)) {
                chatElements.modelSelector.value = envDefaultModel;
            }
        }
        syncRestartFlagWithStorage();
        displaySystemStatus();
        populateWorkflowSelector();
        updateStatus();
    } catch (error) {
        console.error('Error fetching status:', error);
        dashElements.systemStatus.innerHTML = '<p class="state-error text-sm">Failed to fetch system status</p>';
    }
}

// Display system status information
function displaySystemStatus() {
    const status = state.systemStatus;
    const enabledWorkflows = status.enabled_workflows || [];
    const disabledWorkflows = status.disabled_workflows || [];
    const combinedWorkflows = [...enabledWorkflows, ...disabledWorkflows];
    const workflowTypes = [...new Set(combinedWorkflows.map(a => a.workflow_engine))];

    const badgeColors = [
        { bg: 'rgb(var(--accent-primary) / 0.14)', color: 'rgb(var(--accent-primary))' },
        { bg: 'rgb(var(--accent-hover) / 0.14)', color: 'rgb(var(--accent-hover))' },
        { bg: 'rgb(var(--border-primary) / 0.65)', color: 'rgb(var(--text-primary))' },
        { bg: 'rgb(var(--text-secondary) / 0.14)', color: 'rgb(var(--text-secondary))' },
        { bg: 'rgb(var(--bg-elevated))', color: 'rgb(var(--text-primary))' },
        { bg: 'rgb(var(--accent-primary) / 0.22)', color: 'rgb(var(--text-on-accent))' }
    ];

    const workflowColorMap = {};
    workflowTypes.forEach((type, index) => {
        const colors = badgeColors[index % badgeColors.length];
        workflowColorMap[type] = colors;
    });

    const badgeStyles = workflowTypes.map(type => {
        const colors = workflowColorMap[type];
        return `.badge-${type} { background: ${colors.bg}; color: ${colors.color}; }`;
    }).join('\n            ');

    let html = `
        <style>
            .dashboard-table { width: 100%; border-collapse: collapse; background: rgb(var(--bg-card)); font-size: 13px; margin-top: 8px; color: rgb(var(--text-primary)); }
            .dashboard-table th { background: rgb(var(--bg-elevated)); padding: 8px; text-align: left; font-weight: 600; border-bottom: 2px solid rgb(var(--border-primary)); color: rgb(var(--text-primary)); }
            .dashboard-table td { padding: 8px; border-bottom: 1px solid rgb(var(--border-primary)); color: rgb(var(--text-primary)); }
            .dashboard-table tr:hover { background: rgb(var(--bg-elevated)); }
            .dashboard-table .subtle { color: rgb(var(--text-secondary)); }
            .dashboard-table .cell-center { text-align: center; }
            .dashboard-table .cell-xs { font-size: 11px; }
            .dashboard-table .cell-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
            .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
            ${badgeStyles}
            .badge-running { background: rgb(var(--accent-primary)); color: rgb(var(--text-on-accent)); }
            .badge-stopped { background: rgb(var(--state-warning) / 0.2); color: rgb(var(--state-warning)); }
        </style>

        <h3 class="text-lg font-semibold mb-2">🗂️ Vaults</h3>
        <table class="dashboard-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Path</th>
                    <th class="cell-center">Workflows</th>
                </tr>
            </thead>
            <tbody>
                ${status.vaults.map(v => `
                    <tr>
                        <td><strong>${v.name}</strong></td>
                        <td class="cell-mono cell-xs subtle">${v.path}</td>
                        <td class="cell-center">${v.workflow_count}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;

    if (status.scheduler.job_details && status.scheduler.job_details.length > 0) {
        const schedulerBadge = status.scheduler.running
            ? '<span class="badge badge-running">RUNNING</span>'
            : '<span class="badge badge-stopped">STOPPED</span>';

        html += `
            <h3 class="text-lg font-semibold mb-2 mt-6">⏰ Scheduled Jobs ${schedulerBadge}</h3>
            <table class="dashboard-table">
                <thead>
                    <tr>
                        <th>Workflow</th>
                        <th>Next Run</th>
                        <th>Interval</th>
                    </tr>
                </thead>
                <tbody>
                    ${status.scheduler.job_details.map(job => {
                        const workflowName = job.id.replace('__', '/');
                        const nextRun = job.next_run_time ? new Date(job.next_run_time).toLocaleString('en-US', {
                            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
                        }) : '—';
                        return `
                            <tr>
                                <td><strong>${workflowName}</strong></td>
                                <td>${nextRun}</td>
                                <td class="cell-xs subtle">${job.trigger_description}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    }

    if (combinedWorkflows.length > 0) {
        html += `
            <h3 class="text-lg font-semibold mb-2 mt-6">🤖 Workflows</h3>
            <table class="dashboard-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th style="text-align: center;">Type</th>
                        <th>Schedule</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody>
                    ${combinedWorkflows.map(workflow => {
                        const badgeClass = `badge-${workflow.workflow_engine}`;
                        const schedule = workflow.schedule_cron || '—';
                        const description = workflow.description || '—';
                        return `
                            <tr>
                                <td><strong>${workflow.global_id}</strong></td>
                        <td class="cell-center"><span class="badge ${badgeClass}">${workflow.workflow_engine}</span></td>
                        <td class="cell-xs">${schedule}</td>
                        <td class="cell-xs subtle">${description}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    }

    dashElements.systemStatus.innerHTML = html;
}

// Populate workflow selector
function populateWorkflowSelector() {
    if (!dashElements.workflowSelector) return;

    dashElements.workflowSelector.innerHTML = '<option value="">Select workflow...</option>';

    const allWorkflows = [
        ...(state.systemStatus?.enabled_workflows || []),
        ...(state.systemStatus?.disabled_workflows || [])
    ];

    allWorkflows.forEach(workflow => {
        const option = document.createElement('option');
        option.value = workflow.global_id;
        option.textContent = `${workflow.global_id} (${workflow.workflow_engine})`;
        dashElements.workflowSelector.appendChild(option);
    });
}

// Setup event listeners
function setupEventListeners() {
    if (chatElements.sendBtn) {
        chatElements.sendBtn.addEventListener('click', sendMessage);
    }

    if (chatElements.chatInput) {
        chatElements.chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    if (chatElements.newSessionBtn) {
        chatElements.newSessionBtn.addEventListener('click', clearSession);
    }

    if (dashElements.rescanBtn) {
        dashElements.rescanBtn.addEventListener('click', rescanVaults);
    }

    if (dashElements.executeWorkflowBtn) {
        dashElements.executeWorkflowBtn.addEventListener('click', executeWorkflow);
    }

    if (chatElements.chatMessages) {
        chatElements.chatMessages.addEventListener('scroll', handleChatScroll, { passive: true });
    }

    if (chatElements.vaultSelector) {
        chatElements.vaultSelector.addEventListener('change', handleVaultChange);
    }
}

function handleVaultChange() {
    const vault = chatElements.vaultSelector ? chatElements.vaultSelector.value : '';
    populateTemplates([]); // reset while loading
    if (vault) {
        fetchTemplates(vault);
    }
}

function populateTemplates(templates) {
    if (!chatElements.templateSelector) return;
    chatElements.templateSelector.innerHTML = '<option value="">Select template...</option>';
    if (!templates || templates.length === 0) {
        chatElements.templateSelector.disabled = true;
        return;
    }
    templates.forEach((tmpl) => {
        const option = document.createElement('option');
        option.value = tmpl.name;
        option.textContent = `${tmpl.name} (${tmpl.source})`;
        chatElements.templateSelector.appendChild(option);
    });
    const preferredTemplate = state.metadata?.default_context_template || 'default.md';
    const defaultTemplate = Array.from(chatElements.templateSelector.options)
        .find((option) => option.value === preferredTemplate);
    if (defaultTemplate) {
        chatElements.templateSelector.value = defaultTemplate.value;
    } else {
        const fallbackTemplate = Array.from(chatElements.templateSelector.options)
            .find((option) => option.value === 'default.md');
        if (fallbackTemplate) {
            chatElements.templateSelector.value = fallbackTemplate.value;
        }
    }
    chatElements.templateSelector.disabled = false;
}

async function fetchTemplates(vault) {
    if (!vault) {
        populateTemplates([]);
        return;
    }
    try {
        const response = await fetch(`api/context/templates?vault_name=${encodeURIComponent(vault)}`);
        if (!response.ok) {
            throw new Error('Failed to fetch templates');
        }
        const templates = await response.json();
        populateTemplates(templates);
    } catch (error) {
        console.error('Error fetching templates:', error);
        populateTemplates([]);
    }
}

// Send message handler with streaming response support
async function sendMessage() {
    const message = chatElements.chatInput.value.trim();
    if (!message || state.isLoading) return;

    const vault = chatElements.vaultSelector.value;
    const model = chatElements.modelSelector.value;

    if (!vault) {
        alert('Please select a vault');
        return;
    }

    if (!model) {
        alert('Please select a model');
        return;
    }

    addMessage('user', message);
    chatElements.chatInput.value = '';
    state.isLoading = true;
    chatElements.sendBtn.disabled = true;

    const selectedTools = Array.from(chatElements.toolsCheckboxes.querySelectorAll('input:checked'))
        .map(cb => cb.value);

    const requestData = {
        vault_name: vault,
        prompt: message,
        tools: selectedTools,
        model: model,
        context_template: chatElements.templateSelector ? chatElements.templateSelector.value || null : null,
        instructions: null,
        stream: true
    };

    if (state.sessionId) {
        requestData.session_id = state.sessionId;
    }

    const loadingMessage = addLoadingMessage();

    try {
        const response = await fetch('api/chat/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        removeLoadingMessage(loadingMessage);

        const sessionId = response.headers.get('X-Session-ID');
        if (sessionId) {
            state.sessionId = sessionId;
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
                }
            }
        }

        finalizeAssistantMessage(assistantMessage, {
            sessionId: state.sessionId || 'unknown',
            messageCount: Math.max(messageCount, assistantMessage.fullText ? 1 : 0),
            toolCount: assistantMessage.toolStatusMap.size,
            status: finished ? 'done' : 'incomplete'
        });

    } catch (error) {
        console.error('Error sending message:', error);
        removeLoadingMessage(loadingMessage);
        addMessage('error', `❌ Error: ${error.message || 'Streaming failed'}`);
    } finally {
        state.isLoading = false;
        chatElements.sendBtn.disabled = false;
        chatElements.chatInput.focus();
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

    if (chatElements.chatMessages.children.length === 1 &&
        chatElements.chatMessages.children[0].classList.contains('text-center')) {
        chatElements.chatMessages.innerHTML = '';
    }

    chatElements.chatMessages.appendChild(messageDiv);
    scrollChatToBottom(true);

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
        bodyDiv.innerHTML = marked.parse(content);
        enforceExternalLinkBehavior(bodyDiv);
    } else {
        const escapedContent = content
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');
        bodyDiv.innerHTML = escapedContent;
    }

    contentDiv.appendChild(bodyDiv);

    if (role === 'assistant') {
        attachCodeCopyButtons(bodyDiv);
    }

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

    if (footerContent.innerHTML.trim()) {
        footerDiv.appendChild(footerContent);
    } else {
        footerDiv.classList.add('message-footer-right');
    }

    footerDiv.appendChild(actionsDiv);
    contentDiv.appendChild(footerDiv);

    messageDiv.appendChild(contentDiv);

    if (chatElements.chatMessages.children.length === 1 &&
        chatElements.chatMessages.children[0].classList.contains('text-center')) {
        chatElements.chatMessages.innerHTML = '';
    }

    chatElements.chatMessages.appendChild(messageDiv);
    scrollChatToBottom(true);
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

    if (chatElements.chatMessages.children.length === 1 &&
        chatElements.chatMessages.children[0].classList.contains('text-center')) {
        chatElements.chatMessages.innerHTML = '';
    }

    chatElements.chatMessages.appendChild(messageDiv);
    scrollChatToBottom(true);

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
        toolSummary: null
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

function renderAssistantMarkdown(context) {
    if (!context.fullText.trim()) {
        context.bodyDiv.innerHTML = '';
    } else {
        context.bodyDiv.innerHTML = marked.parse(context.fullText);
        enforceExternalLinkBehavior(context.bodyDiv);
        attachCodeCopyButtons(context.bodyDiv);
    }

    scrollChatToBottom();
}

function setAssistantStatus(context, label, state = 'thinking') {
    const emoji = STATUS_EMOJIS[state] || STATUS_EMOJIS.thinking;
    context.statusText.textContent = `${label} ${emoji}`;
    context.indicator.className = 'stream-status-indicator typing';
    context.indicator.innerHTML = TYPING_DOTS_HTML;
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

    const dataPayload = dataLines.join('');
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
async function clearSession() {
    const confirmed = window.confirm('Do you want to start a new chat session? The current session is saved as a markdown file in your vault.');
    if (!confirmed) return;

    state.sessionId = null;
    chatElements.chatMessages.innerHTML = '<div class="text-center text-txt-secondary text-sm">Start a conversation...</div>';
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
        dashElements.rescanResult.innerHTML = `
            <div class="state-surface-success p-3 rounded border">
                <p class="font-medium">✅ Rescan Completed</p>
                <p>Vaults discovered: ${data.vaults_discovered || 0}</p>
                <p>Workflows loaded: ${data.workflows_loaded || 0}</p>
                <p>Enabled workflows: ${data.enabled_workflows || 0}</p>
                <p>Scheduler jobs synced: ${data.scheduler_jobs_synced || 0}</p>
                <p class="mt-2 text-sm">${data.message || ''}</p>
            </div>
        `;

        if (data.metadata) {
            state.metadata = data.metadata;
            window.App = window.App || {};
            window.App.metadata = data.metadata;
            populateSelectors();
        } else {
            await fetchMetadata();
        }

        await fetchSystemStatus();

    } catch (error) {
        console.error('Error rescanning:', error);
        dashElements.rescanResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
    } finally {
        dashElements.rescanBtn.disabled = false;
    }
}

// Execute workflow manually
async function executeWorkflow() {
    const globalId = dashElements.workflowSelector.value;
    const stepName = dashElements.stepNameInput.value.trim() || null;

    if (!globalId) {
        alert('Please select a workflow');
        return;
    }

    dashElements.executeWorkflowResult.innerHTML = '<p class="text-txt-secondary">Executing...</p>';
    dashElements.executeWorkflowBtn.disabled = true;

    try {
        const payload = { global_id: globalId };
        if (stepName) payload.step_name = stepName;

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
        const outputFiles = data.output_files || [];

        dashElements.executeWorkflowResult.innerHTML = `
            <div class="state-surface-success p-3 rounded border">
                <p class="font-medium">✅ Execution Completed</p>
                <p>Workflow: ${data.global_id || ''}</p>
                <p>Execution time: ${data.execution_time_seconds?.toFixed(2) || 0}s</p>
                ${outputFiles.length ? `
                    <p class="mt-2">Output files created:</p>
                    <ul class="list-disc list-inside ml-4">
                        ${outputFiles.map(f => `<li class="text-sm">${f}</li>`).join('')}
                    </ul>
                ` : ''}
                <p class="mt-2 text-sm">${data.message || ''}</p>
            </div>
        `;

    } catch (error) {
        console.error('Error executing workflow:', error);
        dashElements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
    } finally {
        dashElements.executeWorkflowBtn.disabled = false;
    }
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

    // Update Configuration tab and banner
    if (noticeLines.length === 0) {
        // No warnings - hide banner and remove tab highlight
        configElements.statusBanner.classList.add('hidden');
        configElements.statusMessages.innerHTML = '';
        configElements.configTab.classList.remove('font-semibold', 'bg-app-elevated', 'px-3', 'rounded-t-md', 'text-accent');
        configElements.configTab.classList.add('text-txt-secondary');
        configElements.configTab.style.borderColor = '';
        configElements.configTab.textContent = 'Configuration';
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
        configElements.configTab.textContent = 'Configuration ⚠️';
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
