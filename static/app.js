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

const STATUS_ICONS = {
    success: '✓',
    error: '⚠️',
    tool: '🛠️',
    running: '…'
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
    statusIcon: document.getElementById('status-icon'),
    statusText: document.getElementById('status-text'),
    vaultSelector: document.getElementById('vault-selector'),
    modelSelector: document.getElementById('model-selector'),
    modeSelector: document.getElementById('mode-selector'),
    toolsCheckboxes: document.getElementById('tools-checkboxes'),
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    sendBtn: document.getElementById('send-btn'),
    clearBtn: document.getElementById('clear-btn')
};

// DOM elements - Dashboard
const dashElements = {
    systemStatus: document.getElementById('system-status'),
    rescanBtn: document.getElementById('rescan-btn'),
    rescanResult: document.getElementById('rescan-result'),
    assistantSelector: document.getElementById('assistant-selector'),
    stepNameInput: document.getElementById('step-name-input'),
    executeAssistantBtn: document.getElementById('execute-assistant-btn'),
    executeAssistantResult: document.getElementById('execute-assistant-result')
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

// Initialize app
async function init() {
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
        tabControls.button.classList.toggle('border-blue-500', isActive);
        tabControls.button.classList.toggle('text-blue-600', isActive);
        tabControls.button.classList.toggle('border-transparent', !isActive);
        tabControls.button.classList.toggle('text-gray-500', !isActive);
        tabControls.content.classList.toggle('hidden', !isActive);
    });

    if (tabName === 'dashboard') {
        fetchSystemStatus();
    } else if (tabName === 'configuration' && window.ConfigurationPanel) {
        window.ConfigurationPanel.onTabActivated();
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
        const response = await fetch('api/chat/metadata');
        if (!response.ok) throw new Error('Failed to fetch metadata');

        state.metadata = await response.json();
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

    const preferredWebTool = (['web_search_tavily', 'web_search_duckduckgo']
        .map(name => state.metadata.tools.find(tool => tool.name === name && tool.available !== false))
        .find(Boolean)?.name) || null;

    const toolMap = new Map(state.metadata.tools.map(tool => [tool.name, tool]));
    const handledTools = new Set();

    const createToolElement = (tool) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex items-center';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `tool-${tool.name}`;
        checkbox.value = tool.name;
        checkbox.className = 'mr-2';
        checkbox.disabled = tool.available === false;

        if (
            !checkbox.disabled &&
            (
                tool.name === 'file_ops_safe' ||
                (preferredWebTool && tool.name === preferredWebTool)
            )
        ) {
            checkbox.checked = true;
        }

        const label = document.createElement('label');
        label.htmlFor = `tool-${tool.name}`;
        label.className = `text-sm ${checkbox.disabled ? 'text-gray-400' : 'text-gray-700'}`;
        label.innerHTML = `<strong>${tool.name}</strong>: ${tool.description}${checkbox.disabled ? ' (unavailable)' : ''}`;

        wrapper.appendChild(checkbox);
        wrapper.appendChild(label);
        return wrapper;
    };

    const leftColumnOrder = [
        'web_search_duckduckgo',
        'web_search_tavily',
        'file_ops_safe',
        'file_ops_unsafe'
    ];
    const rightColumnOrder = [
        'documentation_access',
        'tavily_extract',
        'tavily_crawl',
        'code_execution'
    ];

    const leftColumn = document.createElement('div');
    leftColumn.className = 'flex flex-col gap-2';
    const rightColumn = document.createElement('div');
    rightColumn.className = 'flex flex-col gap-2';

    const appendTools = (order, column) => {
        order.forEach(name => {
            const tool = toolMap.get(name);
            if (!tool) return;
            column.appendChild(createToolElement(tool));
            handledTools.add(name);
        });
    };

    appendTools(leftColumnOrder, leftColumn);
    appendTools(rightColumnOrder, rightColumn);

    state.metadata.tools.forEach(tool => {
        if (handledTools.has(tool.name)) {
            return;
        }
        const targetColumn = leftColumn.childElementCount <= rightColumn.childElementCount
            ? leftColumn
            : rightColumn;
        targetColumn.appendChild(createToolElement(tool));
    });

    chatElements.toolsCheckboxes.appendChild(leftColumn);
    chatElements.toolsCheckboxes.appendChild(rightColumn);

    applyModeToolPreferences();
}

// Fetch system status
async function fetchSystemStatus() {
    try {
        const response = await fetch('api/status');
        if (!response.ok) throw new Error('Failed to fetch status');

        state.systemStatus = await response.json();
        syncRestartFlagWithStorage();
        displaySystemStatus();
        populateAssistantSelector();
        updateStatus();
    } catch (error) {
        console.error('Error fetching status:', error);
        dashElements.systemStatus.innerHTML = '<p class="text-red-600">Failed to fetch system status</p>';
    }
}

// Display system status information
function displaySystemStatus() {
    const status = state.systemStatus;
    const enabledAssistants = status.enabled_assistants || [];
    const disabledAssistants = status.disabled_assistants || [];
    const combinedAssistants = [...enabledAssistants, ...disabledAssistants];
    const workflowTypes = [...new Set(combinedAssistants.map(a => a.workflow))];

    const badgeColors = [
        { bg: '#e8f5e9', color: '#388e3c' },
        { bg: '#e3f2fd', color: '#1976d2' },
        { bg: '#fff3e0', color: '#e65100' },
        { bg: '#f3e5f5', color: '#7b1fa2' },
        { bg: '#e0f2f1', color: '#00695c' },
        { bg: '#fce4ec', color: '#c2185b' }
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
            .dashboard-table { width: 100%; border-collapse: collapse; background: white; font-size: 13px; margin-top: 8px; }
            .dashboard-table th { background: #f8f9fa; padding: 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #dee2e6; }
            .dashboard-table td { padding: 8px; border-bottom: 1px solid #f0f0f0; }
            .dashboard-table tr:hover { background: #f8f9fa; }
            .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
            ${badgeStyles}
            .badge-running { background: #4caf50; color: white; }
        </style>

        <h3 class="text-lg font-semibold mb-2">🗂️ Vaults</h3>
        <table class="dashboard-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Path</th>
                    <th style="text-align: center;">Assistants</th>
                </tr>
            </thead>
            <tbody>
                ${status.vaults.map(v => `
                    <tr>
                        <td><strong>${v.name}</strong></td>
                        <td style="font-family: monospace; font-size: 11px; color: #666;">${v.path}</td>
                        <td style="text-align: center;">${v.assistant_count}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;

    if (status.scheduler.job_details && status.scheduler.job_details.length > 0) {
        const schedulerBadge = status.scheduler.running
            ? '<span class="badge badge-running">RUNNING</span>'
            : '<span class="badge" style="background: #ffebee; color: #c62828;">STOPPED</span>';

        html += `
            <h3 class="text-lg font-semibold mb-2 mt-6">⏰ Scheduled Jobs ${schedulerBadge}</h3>
            <table class="dashboard-table">
                <thead>
                    <tr>
                        <th>Assistant</th>
                        <th>Next Run</th>
                        <th>Interval</th>
                    </tr>
                </thead>
                <tbody>
                    ${status.scheduler.job_details.map(job => {
                        const assistantName = job.id.replace('__', '/');
                        const nextRun = job.next_run_time ? new Date(job.next_run_time).toLocaleString('en-US', {
                            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
                        }) : '—';
                        return `
                            <tr>
                                <td><strong>${assistantName}</strong></td>
                                <td>${nextRun}</td>
                                <td style="font-size: 11px;">${job.trigger_description}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    }

    if (combinedAssistants.length > 0) {
        html += `
            <h3 class="text-lg font-semibold mb-2 mt-6">🤖 Assistants</h3>
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
                    ${combinedAssistants.map(a => {
                        const badgeClass = `badge-${a.workflow}`;
                        const schedule = a.schedule_cron || '—';
                        const description = a.description || '—';
                        return `
                            <tr>
                                <td><strong>${a.global_id}</strong></td>
                                <td style="text-align: center;"><span class="badge ${badgeClass}">${a.workflow}</span></td>
                                <td style="font-size: 11px;">${schedule}</td>
                                <td style="font-size: 11px; color: #666;">${description}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    }

    dashElements.systemStatus.innerHTML = html;
}

// Populate assistant selector
function populateAssistantSelector() {
    if (!dashElements.assistantSelector) return;

    dashElements.assistantSelector.innerHTML = '<option value="">Select assistant...</option>';

    const allAssistants = [
        ...(state.systemStatus?.enabled_assistants || []),
        ...(state.systemStatus?.disabled_assistants || [])
    ];

    allAssistants.forEach(assistant => {
        const option = document.createElement('option');
        option.value = assistant.global_id;
        option.textContent = `${assistant.global_id} (${assistant.workflow})`;
        dashElements.assistantSelector.appendChild(option);
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

    if (chatElements.clearBtn) {
        chatElements.clearBtn.addEventListener('click', clearSession);
    }

    if (dashElements.rescanBtn) {
        dashElements.rescanBtn.addEventListener('click', rescanVaults);
    }

    if (dashElements.executeAssistantBtn) {
        dashElements.executeAssistantBtn.addEventListener('click', executeAssistant);
    }

    if (chatElements.chatMessages) {
        chatElements.chatMessages.addEventListener('scroll', handleChatScroll, { passive: true });
    }

    if (chatElements.modeSelector) {
        chatElements.modeSelector.addEventListener('change', handleModeChange);
    }
}

function handleModeChange() {
    applyModeToolPreferences();
}

function applyModeToolPreferences() {
    const mode = chatElements.modeSelector ? chatElements.modeSelector.value : 'regular';
    const docCheckbox = document.getElementById('tool-documentation_access');
    if (!docCheckbox || docCheckbox.disabled) {
        return;
    }
    docCheckbox.checked = mode === 'assistant_creation';
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
        use_conversation_history: true,
        session_type: chatElements.modeSelector.value,
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
                    setAssistantStatus(assistantMessage, 'Something went wrong.', 'error');
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
    contentDiv.className = 'max-w-[80%] px-4 py-2 rounded-lg bg-gray-100 text-gray-800';
    contentDiv.innerHTML = `<div class="flex items-center space-x-2 text-sm text-gray-600">
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

// Add message to chat with copy controls
function addMessage(role, content, options = {}) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex ${role === 'user' ? 'justify-end' : 'justify-start'}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = `max-w-[80%] px-4 py-2 rounded-lg ${
        role === 'user'
            ? 'bg-gray-100 text-gray-800'
            : role === 'error'
            ? 'bg-red-100 text-red-800 border border-red-300'
            : 'bg-blue-100 text-gray-800 prose prose-sm max-w-none'
    }`;
    contentDiv.classList.add('message-bubble');

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'message-body';

    if (role === 'assistant') {
        bodyDiv.innerHTML = marked.parse(content);
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
    contentDiv.className = 'max-w-[80%] px-4 py-3 rounded-lg bg-blue-100 text-gray-800 prose prose-sm max-w-none message-bubble shadow-sm';

    const progressDiv = document.createElement('div');
    progressDiv.className = 'stream-progress';

    const indicator = document.createElement('div');
    indicator.className = 'stream-status-indicator typing';
    indicator.innerHTML = TYPING_DOTS_HTML;

    const statusText = document.createElement('span');
    statusText.className = 'stream-status-text';
    statusText.textContent = 'Assistant is responding…';

    progressDiv.appendChild(indicator);
    progressDiv.appendChild(statusText);

    const toolList = document.createElement('div');
    toolList.className = 'tool-status-list hidden';

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'message-body prose prose-sm max-w-none';
    bodyDiv.innerHTML = '<p class="text-sm text-gray-600">Preparing response…</p>';

    contentDiv.appendChild(progressDiv);
    contentDiv.appendChild(toolList);
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
        toolStatusMap: new Map(),
        fullText: '',
        errorMessages: [],
        hasTools: false,
        toolSummary: null
    };
}

function renderAssistantMarkdown(context) {
    if (!context.fullText.trim()) {
        context.bodyDiv.innerHTML = '<p class="text-sm text-gray-600">Thinking…</p>';
    } else {
        context.bodyDiv.innerHTML = marked.parse(context.fullText);
        attachCodeCopyButtons(context.bodyDiv);
    }

    scrollChatToBottom();
}

function setAssistantStatus(context, label, state = 'thinking') {
    context.statusText.textContent = label;

    if (state === 'done') {
        context.indicator.className = 'stream-status-indicator success';
        context.indicator.textContent = STATUS_ICONS.success;
    } else if (state === 'error') {
        context.indicator.className = 'stream-status-indicator error';
        context.indicator.textContent = STATUS_ICONS.error;
    } else if (state === 'tools') {
        context.indicator.className = 'stream-status-indicator tool';
        context.indicator.textContent = STATUS_ICONS.tool;
    } else {
        context.indicator.className = 'stream-status-indicator typing';
        context.indicator.innerHTML = TYPING_DOTS_HTML;
    }
}

function handleToolEvent(context, payload) {
    const toolId = payload.tool_call_id || `tool-${context.toolStatusMap.size + 1}`;
    if (!toolId) return;

    let entry = context.toolStatusMap.get(toolId);

    if (payload.event === 'tool_call_started' || !entry) {
        entry = createToolStatusEntry(context, toolId, payload);
        context.hasTools = true;
        if (payload.event === 'tool_call_started') {
            setAssistantStatus(context, 'Running tools…', 'tools');
        }
    }

    if (payload.event === 'tool_call_finished') {
        entry.container.classList.remove('tool-status-running');
        entry.container.classList.add('tool-status-complete');
        if (payload.result) {
            entry.result = payload.result;
        }
        updateToolDetail(entry);
        entry.chevron.textContent = entry.container.open ? '▾' : '▸';

        const hasRunning = Array.from(context.toolStatusMap.values())
            .some(item => item.container.classList.contains('tool-status-running'));
        if (!hasRunning) {
            setAssistantStatus(context, 'Continuing response…', 'thinking');
        }
    } else if (payload.event === 'tool_call_started' && payload.arguments) {
        entry.args = payload.arguments;
        updateToolDetail(entry);
    }
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
        const finalLabel = hasError ? 'Completed with issues.' : 'Response ended early.';
        setAssistantStatus(context, finalLabel, 'error');
    } else if (context.progressDiv && context.progressDiv.parentNode) {
        context.progressDiv.parentNode.removeChild(context.progressDiv);
    }

    const footerDiv = document.createElement('div');
    footerDiv.className = 'message-footer';

    const footerContent = document.createElement('div');
    footerContent.className = 'message-footer-content';

    const metaEntries = [];
    if (metadata.sessionId) {
        metaEntries.push({ label: 'Session', value: metadata.sessionId });
    }
    if (metadata.messageCount) {
        metaEntries.push({ label: 'Messages', value: metadata.messageCount });
    }
    if (metadata.toolCount) {
        metaEntries.push({ label: 'Tools', value: metadata.toolCount });
    }
    if (endedEarly && !hasError) {
        metaEntries.push({ label: 'Status', value: 'Partial output' });
    }

    if (metaEntries.length === 0) {
        metaEntries.push({ label: 'Status', value: hasError ? 'Needs review' : 'Ready' });
    }

    metaEntries.forEach(({ label, value }) => {
        const span = document.createElement('span');
        span.textContent = `${label}: ${value}`;
        footerContent.appendChild(span);
    });

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-footer-actions';

    const copyButton = createCopyButton(() => getCopyableText(context.bodyDiv), 'message-copy-button');
    actionsDiv.appendChild(copyButton);

    footerDiv.appendChild(footerContent);
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
    state.sessionId = null;
    chatElements.chatMessages.innerHTML = '<div class="text-center text-gray-500 text-sm">Start a conversation...</div>';
    updateStatus();
}

// Rescan vaults
async function rescanVaults() {
    if (!dashElements.rescanResult) return;

    dashElements.rescanResult.innerHTML = '<p class="text-gray-600">Rescanning...</p>';
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
            <div class="text-green-700 bg-green-50 p-3 rounded border border-green-200">
                <p class="font-medium">✅ Rescan Completed</p>
                <p>Vaults discovered: ${data.vaults_discovered || 0}</p>
                <p>Assistants loaded: ${data.assistants_loaded || 0}</p>
                <p>Enabled assistants: ${data.enabled_assistants || 0}</p>
                <p>Scheduler jobs synced: ${data.scheduler_jobs_synced || 0}</p>
                <p class="mt-2 text-sm">${data.message || ''}</p>
            </div>
        `;

        await fetchSystemStatus();
        await fetchMetadata();

    } catch (error) {
        console.error('Error rescanning:', error);
        dashElements.rescanResult.innerHTML = `<p class="text-red-600">❌ Error: ${error.message}</p>`;
    } finally {
        dashElements.rescanBtn.disabled = false;
    }
}

// Execute assistant manually
async function executeAssistant() {
    const globalId = dashElements.assistantSelector.value;
    const stepName = dashElements.stepNameInput.value.trim() || null;

    if (!globalId) {
        alert('Please select an assistant');
        return;
    }

    dashElements.executeAssistantResult.innerHTML = '<p class="text-gray-600">Executing...</p>';
    dashElements.executeAssistantBtn.disabled = true;

    try {
        const payload = { global_id: globalId };
        if (stepName) payload.step_name = stepName;

        const response = await fetch('api/assistants/execute', {
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

        dashElements.executeAssistantResult.innerHTML = `
            <div class="text-green-700 bg-green-50 p-3 rounded border border-green-200">
                <p class="font-medium">✅ Execution Completed</p>
                <p>Assistant: ${data.global_id || ''}</p>
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
        console.error('Error executing assistant:', error);
        dashElements.executeAssistantResult.innerHTML = `<p class="text-red-600">❌ Error: ${error.message}</p>`;
    } finally {
        dashElements.executeAssistantBtn.disabled = false;
    }
}

function updateStatus(message) {
    if (!chatElements.statusIcon || !chatElements.statusText) return;

    const warnings = getConfigurationWarnings();
    const noticeLines = [];

    if (state.restartRequired) {
        noticeLines.push(RESTART_NOTICE_TEXT);
    }

    warnings.forEach((issue) => {
        noticeLines.push(issue.message);
    });

    // Check for no vaults
    if (state.metadata && state.metadata.vaults && state.metadata.vaults.length === 0) {
        noticeLines.push('No vaults found. Review installation instructions.');
    }

    // Show only icon when everything is good, or icon + text when there are issues
    if (!noticeLines.length) {
        chatElements.statusIcon.textContent = '✅';
        chatElements.statusText.classList.add('hidden');
        chatElements.statusText.innerHTML = '';
    } else {
        chatElements.statusIcon.textContent = '⚠️';
        chatElements.statusText.classList.remove('hidden');
        chatElements.statusText.innerHTML = `<span class="text-amber-600">${noticeLines.join(' • ')}</span>`;
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
