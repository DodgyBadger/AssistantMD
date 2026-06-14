(function chatRenderingModule(window, document) {
    const CHAT_EMPTY_STATE_MESSAGE = 'Start a conversation...';

    function createChatRenderingController({ state, elements, icons, utils, callbacks }) {
        let mathTypesetQueue = Promise.resolve();
        let currentEmptyStateMessage = CHAT_EMPTY_STATE_MESSAGE;
        let workspaceEditorOpen = false;

        function isChatPlaceholderNode(node) {
            if (!node || !(node instanceof HTMLElement)) return false;
            return node.classList.contains('chat-start-panel') ||
                (
                    node.classList.contains('text-center') &&
                    node.classList.contains('text-txt-secondary') &&
                    node.classList.contains('text-sm')
                );
        }

        function clearChatPlaceholderIfPresent() {
            const container = elements.chatMessages;
            if (!container) return;
            if (container.children.length !== 1) return;
            if (!isChatPlaceholderNode(container.children[0])) return;
            container.innerHTML = '';
        }

        function appendChatMessageNode(node, { forceScroll = true } = {}) {
            const container = elements.chatMessages;
            if (!container || !node) return;
            clearChatPlaceholderIfPresent();
            container.appendChild(node);
            callbacks.scrollChatToBottom(forceScroll);
        }

        function renderChatEmptyState(message = CHAT_EMPTY_STATE_MESSAGE) {
            const container = elements.chatMessages;
            if (!container) return;
            currentEmptyStateMessage = message;
            container.innerHTML = '';
            if (message === CHAT_EMPTY_STATE_MESSAGE) {
                renderChatStartPanel(container);
                state.shouldAutoScroll = true;
                return;
            }
            const placeholder = document.createElement('div');
            placeholder.className = 'text-center text-txt-secondary text-sm';
            placeholder.textContent = message;
            container.appendChild(placeholder);
            state.shouldAutoScroll = true;
        }

        function refreshEmptyState() {
            const container = elements.chatMessages;
            if (!container || container.children.length !== 1 || !isChatPlaceholderNode(container.children[0])) {
                return;
            }
            renderChatEmptyState(currentEmptyStateMessage);
        }

        function renderChatStartPanel(container) {
            const modelText = selectedOptionText(elements.modelSelector) || 'No model selected';
            const thinkingText = selectedOptionText(elements.thinkingSelector).replace(/^Thinking:\s*/i, '') || 'Default';
            const workspacePath = (elements.workspacePathInput?.value || '').trim();

            const panel = document.createElement('div');
            panel.className = 'chat-start-panel';
            panel.innerHTML = `
                <div class="chat-start-panel-title">Ready for a new chat</div>
                <div class="chat-start-panel-grid">
                    <div class="chat-start-panel-item">
                        <span class="chat-start-panel-label">Model</span>
                        <span class="chat-start-panel-value">${utils.escapeHtml(modelText)}</span>
                    </div>
                    <div class="chat-start-panel-item">
                        <span class="chat-start-panel-label">Thinking</span>
                        <span class="chat-start-panel-value">${utils.escapeHtml(thinkingText)}</span>
                    </div>
                    <button type="button" class="chat-start-settings-button" data-chat-start-settings="true" aria-label="Change chat settings" title="Change chat settings">
                        <span>Change settings</span>
                        ${icons.SETTINGS_ICON_SVG}
                    </button>
                </div>
                ${renderWorkspaceRow(workspacePath)}
            `;
            attachChatStartPanelEvents(panel);
            container.appendChild(panel);
        }

        function selectedOptionText(select) {
            if (!(select instanceof HTMLSelectElement)) return '';
            const option = select.selectedOptions && select.selectedOptions.length
                ? select.selectedOptions[0]
                : null;
            return (option?.textContent || select.value || '').trim();
        }

        function renderWorkspaceRow(workspacePath) {
            return `
                <div class="chat-start-workspace-block">
                    <div class="chat-start-workspace-editor">
                        <span class="chat-start-workspace-label">Workspace</span>
                        ${workspacePath
                            ? `<span class="chat-start-workspace-path">${utils.escapeHtml(workspacePath)}</span>`
                            : renderWorkspaceEntryControls()}
                    </div>
                    <p class="chat-start-workspace-help">A workspace is a folder in your vault. Setting this helps orient the chat agent. See <a href="https://github.com/DodgyBadger/AssistantMD/blob/main/docs/use/build-guide.md" target="_blank" rel="noopener noreferrer">build-guide</a> for more info.</p>
                </div>
            `;
        }

        function renderWorkspaceEntryControls() {
            if (!workspaceEditorOpen) {
                return '<button type="button" class="chat-start-link-button" data-chat-start-workspace-open="true">Add workspace</button>';
            }
            return `
                <input
                    type="text"
                    class="chat-start-workspace-input"
                    placeholder="Workspace path..."
                    aria-label="Workspace path"
                    data-chat-start-workspace-input
                />
                <button type="button" class="chat-start-icon-button" data-chat-start-workspace-browse="true" aria-label="Choose workspace folder" title="Choose workspace folder">
                    ${icons.FOLDER_ICON_SVG}
                </button>
                <button type="button" class="chat-start-link-button" data-chat-start-workspace-apply="true">Apply</button>
                <button type="button" class="chat-start-link-button is-muted" data-chat-start-workspace-cancel="true">Cancel</button>
            `;
        }

        function attachChatStartPanelEvents(panel) {
            panel.addEventListener('click', (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (target.closest('[data-chat-start-settings]')) {
                    callbacks.openChatSettings?.();
                    return;
                }
                if (target.closest('[data-chat-start-workspace-open]')) {
                    workspaceEditorOpen = true;
                    renderChatEmptyState();
                    return;
                }
                if (target.closest('[data-chat-start-workspace-cancel]')) {
                    workspaceEditorOpen = false;
                    renderChatEmptyState();
                    return;
                }
                if (target.closest('[data-chat-start-workspace-browse]')) {
                    callbacks.openWorkspacePicker?.();
                    return;
                }
                if (target.closest('[data-chat-start-workspace-apply]')) {
                    applyWorkspaceFromStartPanel(panel);
                }
            });
            panel.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                const target = event.target;
                if (!(target instanceof HTMLInputElement) || !target.matches('[data-chat-start-workspace-input]')) {
                    return;
                }
                event.preventDefault();
                applyWorkspaceFromStartPanel(panel);
            });
        }

        function applyWorkspaceFromStartPanel(panel) {
            const input = panel.querySelector('[data-chat-start-workspace-input]');
            if (!(input instanceof HTMLInputElement)) return;
            const path = input.value.trim();
            if (!path || !elements.workspacePathInput) return;
            elements.workspacePathInput.value = path;
            elements.workspacePathInput.dispatchEvent(new Event('input', { bubbles: true }));
            workspaceEditorOpen = false;
            renderChatEmptyState();
        }

        function addChatErrorMessage(errorText) {
            addMessage('error', `Error: ${errorText || 'Streaming failed'}`);
        }


        function renderPersistedSession(payload) {
            elements.chatMessages.innerHTML = '';

            const messages = Array.isArray(payload?.messages) ? payload.messages : [];
            const toolEventsById = groupToolEventsById(payload?.tool_events);
            const pendingToolCallIds = new Set();
            const effectiveToolCallIds = toolCallIdsForMessages(messages);
            let archivedToolEvents = toolEventsExceptIds(toolEventsById, effectiveToolCallIds);

            if (messages.length === 0) {
                renderChatEmptyState('Selected session has no persisted messages.');
                return;
            }

            messages.forEach((message) => {
                if (message.is_tool_message) {
                    collectToolIds(message.tool_call_ids, pendingToolCallIds);
                    collectToolIds(message.tool_return_ids, pendingToolCallIds);
                    return;
                }

                if (message.role === 'assistant') {
                    const assistantToolEvents = toolEventsForIds(toolEventsById, pendingToolCallIds);
                    pendingToolCallIds.clear();
                    renderPersistedAssistantMessage(message.content || '', assistantToolEvents, {
                        sequenceIndex: message.sequence_index
                    });
                    return;
                }

                pendingToolCallIds.clear();
                if (isCompactionSummaryMessage(message) && archivedToolEvents.length > 0) {
                    renderPersistedAssistantMessage(message.content || '', archivedToolEvents, {
                        sequenceIndex: message.sequence_index,
                        archivedToolEvents: true
                    });
                    archivedToolEvents = [];
                    return;
                }

                addMessage('user', message.content || '', {
                    sequenceIndex: message.sequence_index
                });
            });

            if (archivedToolEvents.length > 0) {
                renderPersistedAssistantMessage('Tool activity archived by compaction.', archivedToolEvents, {
                    archivedToolEvents: true
                });
            }
        }

        function groupToolEventsById(toolEvents) {
            const grouped = new Map();
            if (!Array.isArray(toolEvents)) {
                return grouped;
            }
            toolEvents.forEach((event) => {
                if (!event || !event.tool_call_id) {
                    return;
                }
                const existing = grouped.get(event.tool_call_id) || [];
                existing.push(event);
                grouped.set(event.tool_call_id, existing);
            });
            return grouped;
        }

        function toolCallIdsForMessages(messages) {
            const ids = new Set();
            if (!Array.isArray(messages)) {
                return ids;
            }
            messages.forEach((message) => {
                if (!message || !message.is_tool_message) {
                    return;
                }
                collectToolIds(message.tool_call_ids, ids);
                collectToolIds(message.tool_return_ids, ids);
            });
            return ids;
        }

        function isCompactionSummaryMessage(message) {
            return String(message?.content || '').includes('AssistantMD compacted chat history');
        }

        function collectToolIds(toolIds, target) {
            if (!Array.isArray(toolIds) && !(toolIds instanceof Set)) {
                return;
            }
            toolIds.forEach((toolId) => {
                if (toolId) {
                    target.add(toolId);
                }
            });
        }

        function toolEventsForIds(toolEventsById, toolCallIds) {
            const selected = [];
            toolCallIds.forEach((toolId) => {
                const events = toolEventsById.get(toolId);
                if (Array.isArray(events)) {
                    selected.push(...events);
                }
            });
            return selected;
        }

        function toolEventsExceptIds(toolEventsById, excludedToolCallIds) {
            const selected = [];
            toolEventsById.forEach((events, toolId) => {
                if (excludedToolCallIds.has(toolId)) {
                    return;
                }
                if (Array.isArray(events)) {
                    selected.push(...events);
                }
            });
            return selected;
        }

        function renderPersistedAssistantMessage(content, toolEvents, options = {}) {
            const context = createAssistantStreamingMessage();
            context.fullText = content || '';
            context.sequenceIndex = Number.isInteger(options.sequenceIndex) ? options.sequenceIndex : null;
            context.archivedToolEvents = Boolean(options.archivedToolEvents);
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
                entry.events.push(event);

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
            });

            updateToolCallsSummary(context);
        }


        // Loading indicator helpers
        function addLoadingMessage() {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'flex justify-start';
            messageDiv.id = 'loading-message';

            const contentDiv = document.createElement('div');
            contentDiv.className = 'max-w-[80%] px-4 py-2 rounded-lg message-bubble message-assistant';
            contentDiv.innerHTML = `<div class="flex items-center space-x-2 text-sm">
                <span class="typing-indicator inline-flex">${icons.TYPING_DOTS_HTML}</span>
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
                return acc.split(placeholder).join(utils.escapeHtml(rawMath));
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
                callbacks.scrollChatToBottom();
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

            const copyButton = createCopyButton(() => utils.getCopyableText(bodyDiv), 'message-copy-button');
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
            indicator.innerHTML = icons.TYPING_DOTS_HTML;

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
                postProcessTimer: null,
                archivedToolEvents: false
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
            title.textContent = context.archivedToolEvents ? 'Archived tool calls (0)' : 'Tool calls (0)';

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
            const label = context.archivedToolEvents ? 'Archived tool calls' : 'Tool calls';
            context.toolCallsSummaryTitle.textContent = `${label} (${total})`;
        }

        function renderAssistantMarkdown(context, options = {}) {
            const { finalize = false } = options;
            renderAssistantHtml(context.bodyDiv, context.fullText);
            if (finalize) {
                flushAssistantPostProcess(context);
            } else {
                scheduleAssistantPostProcess(context);
            }
            callbacks.scrollChatToBottom();
        }

        function setAssistantStatus(context, label, state = 'thinking') {
            context.statusText.textContent = label;
            context.indicator.className = 'stream-status-indicator';
            if (state === 'thinking') {
                context.indicator.classList.add('typing');
                context.indicator.innerHTML = icons.TYPING_DOTS_HTML;
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
                entry.events.push(payload);
                updateToolDetail(entry);

                const hasRunning = Array.from(context.toolStatusMap.values())
                    .some(item => item.container.classList.contains('tool-status-running'));
                if (!hasRunning) {
                    setAssistantStatus(context, 'Continuing response', 'thinking');
                }
            } else if (payload.event === 'tool_call_started') {
                if (payload.arguments) {
                    entry.args = payload.arguments;
                }
                entry.events.push(payload);
                updateToolDetail(entry);
            }
            updateToolCallsSummary(context);
        }

        function createToolStatusEntry(context, toolId, payload) {
            const container = document.createElement('button');
            container.type = 'button';
            container.className = 'tool-status tool-status-running';

            const summary = document.createElement('div');
            summary.className = 'tool-status-summary';

            const line = document.createElement('span');
            line.className = 'tool-status-line';

            summary.appendChild(line);

            container.appendChild(summary);
            container.addEventListener('click', () => {
                openToolCallDetails(entry);
            });

            context.toolList.classList.remove('hidden');
            context.toolList.appendChild(container);
            const entry = {
                container,
                summary,
                line,
                toolId,
                toolName: payload.tool_name || 'Tool call',
                args: payload.arguments || null,
                result: null,
                archived: Boolean(context.archivedToolEvents),
                events: []
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

            const copyButton = createCopyButton(() => utils.getCopyableText(context.bodyDiv), 'message-copy-button');
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

            callbacks.scrollChatToBottom();
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
            value = normalizeToolDisplayValue(value);
            if (value === undefined || value === null) return '';
            return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
        }

        function normalizeToolDisplayValue(value) {
            if (typeof value !== 'string') return value;
            const trimmed = value.trim();
            if (!trimmed) return '';
            if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return value;
            try {
                return JSON.parse(trimmed);
            } catch {
                return value;
            }
        }

        function isEmptyToolValue(value) {
            value = normalizeToolDisplayValue(value);
            if (value === undefined || value === null) return true;
            if (typeof value === 'string') return value.trim() === '';
            if (Array.isArray(value)) return value.every(isEmptyToolValue);
            if (typeof value === 'object') {
                const entries = Object.entries(value);
                return entries.length === 0 || entries.every(([, item]) => isEmptyToolValue(item));
            }
            return false;
        }

        function pruneEmptyToolValue(value) {
            value = normalizeToolDisplayValue(value);
            if (isEmptyToolValue(value)) return null;
            if (Array.isArray(value)) {
                const items = value
                    .map(pruneEmptyToolValue)
                    .filter(item => item !== null);
                return items.length ? items : null;
            }
            if (value && typeof value === 'object') {
                const entries = Object.entries(value)
                    .map(([key, item]) => [key, pruneEmptyToolValue(item)])
                    .filter(([, item]) => item !== null);
                if (entries.length === 0) return null;
                return Object.fromEntries(entries);
            }
            return value;
        }

        function formatInlineToolValue(value) {
            value = pruneEmptyToolValue(value);
            if (value === null) return '';
            if (typeof value === 'string') return value.trim();
            if (Array.isArray(value)) {
                return value.map(formatInlineToolValue).filter(Boolean).join(', ');
            }
            if (typeof value === 'object') {
                return Object.entries(value)
                    .map(([key, item]) => {
                        const formatted = formatInlineToolValue(item);
                        return formatted ? `${key}: ${formatted}` : '';
                    })
                    .filter(Boolean)
                    .join(', ');
            }
            return String(value);
        }

        function formatToolPreview(value, fallback = '') {
            const detail = formatInlineToolValue(value).replace(/\s+/g, ' ').trim();
            if (!detail) return fallback;
            return detail.length > 80 ? `${detail.slice(0, 77)}...` : detail;
        }

        function truncateToolTooltip(value) {
            const detail = formatInlineToolValue(value).replace(/\s+/g, ' ').trim();
            if (!detail) return '';
            return detail.length > 400 ? `${detail.slice(0, 397)}...` : detail;
        }

        function appendToolCallLine(entry, argsValue) {
            entry.line.innerHTML = '';

            const name = document.createElement('span');
            name.className = 'tool-status-name';
            name.textContent = entry.toolName;
            entry.line.appendChild(name);

            if (argsValue === null) {
                return;
            }

            entry.line.appendChild(document.createTextNode(' ('));
            if (argsValue && typeof argsValue === 'object' && !Array.isArray(argsValue)) {
                Object.entries(argsValue).forEach(([key, value], index) => {
                    if (index > 0) {
                        entry.line.appendChild(document.createTextNode(', '));
                    }
                    const keySpan = document.createElement('span');
                    keySpan.className = 'tool-status-arg-key';
                    keySpan.textContent = key;
                    const valueSpan = document.createElement('span');
                    valueSpan.className = 'tool-status-arg-value';
                    valueSpan.textContent = formatInlineToolValue(value);
                    entry.line.appendChild(keySpan);
                    entry.line.appendChild(document.createTextNode(': '));
                    entry.line.appendChild(valueSpan);
                });
            } else {
                const valueSpan = document.createElement('span');
                valueSpan.className = 'tool-status-arg-value';
                valueSpan.textContent = formatInlineToolValue(argsValue);
                entry.line.appendChild(valueSpan);
            }
            entry.line.appendChild(document.createTextNode(')'));
        }

        function updateToolDetail(entry) {
            if (!entry) return;

            const hasArgs = !isEmptyToolValue(entry.args);
            const prunedArgs = hasArgs ? pruneEmptyToolValue(entry.args) : null;
            appendToolCallLine(entry, prunedArgs);
            entry.container.title = [
                entry.archived ? 'Archived by compaction.' : '',
                hasArgs ? truncateToolTooltip(prunedArgs) : 'No args',
            ].filter(Boolean).join(' ');
        }

        function openToolCallDetails(entry) {
            if (!entry) return;
            closeToolCallDetails();

            const sections = [];
            sections.push({ label: 'Tool', value: entry.toolName || 'Tool call' });
            sections.push({ label: 'Tool call ID', value: entry.toolId || '' });
            sections.push({
                label: 'Context',
                value: entry.archived
                    ? 'Archived by compaction; the tool event is persisted but no longer part of active chat context.'
                    : 'Retained in active chat context.'
            });
            if (!isEmptyToolValue(entry.args)) {
                sections.push({ label: 'Args', value: entry.args });
            }
            if (!isEmptyToolValue(entry.result)) {
                sections.push({ label: 'Result', value: entry.result, kind: 'result' });
            }
            if (entry.events.length > 0) {
                sections.push({ label: 'Events', value: entry.events });
            }

            const overlay = document.createElement('div');
            overlay.id = 'chat-tool-call-modal';
            overlay.className = 'app-modal-overlay fixed inset-0 z-50 flex bg-black/40';
            overlay.innerHTML = `
                <div class="absolute inset-0" data-tool-call-close="true"></div>
                <section class="app-modal-panel relative overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="chat-tool-call-modal-title">
                    <div class="app-modal-header sticky top-0">
                        <div class="app-modal-title-block">
                            <h2 id="chat-tool-call-modal-title" class="text-lg font-semibold text-txt-primary">${utils.escapeHtml(entry.toolName || 'Tool call')}</h2>
                            <p class="mt-1 text-xs text-txt-secondary cell-mono">${utils.escapeHtml(entry.toolId || '')}</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-compact" data-tool-call-close="true" aria-label="Close" title="Close">
                                ${icons.X_ICON_SVG}
                            </button>
                        </div>
                    </div>
                    <div class="p-4" data-tool-call-modal-body></div>
                </section>
            `;
            const body = overlay.querySelector('[data-tool-call-modal-body]');
            if (body) {
                sections.forEach(({ label, value, kind }) => {
                    body.appendChild(createToolDetailSection(label, value, { kind }));
                });
            }
            overlay.addEventListener('click', (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                if (target.closest('[data-tool-call-close="true"]')) {
                    closeToolCallDetails();
                }
            });
            document.addEventListener('keydown', handleToolCallModalKeydown);
            document.body.appendChild(overlay);
        }

        function closeToolCallDetails() {
            const modal = document.getElementById('chat-tool-call-modal');
            if (modal) {
                modal.remove();
            }
            document.removeEventListener('keydown', handleToolCallModalKeydown);
        }

        function handleToolCallModalKeydown(event) {
            if (event.key === 'Escape') {
                closeToolCallDetails();
            }
        }

        function createToolDetailSection(label, value, options = {}) {
            const section = document.createElement('div');
            section.className = 'tool-status-section';

            const heading = document.createElement('div');
            heading.className = 'tool-status-label';
            heading.textContent = label;
            section.appendChild(heading);

            if (options.kind === 'result') {
                renderToolResultValue(section, value);
            } else {
                section.appendChild(createToolDetailBlock(formatToolDetail(value)));
            }

            return section;
        }

        function renderToolResultValue(section, value) {
            const normalized = normalizeToolDisplayValue(value);
            if (!normalized || typeof normalized !== 'object' || Array.isArray(normalized)) {
                section.appendChild(createToolDetailBlock(formatToolDetail(normalized)));
                return;
            }

            const handled = new Set();
            ['text', 'return_value', 'content', 'message'].forEach((key) => {
                if (!isEmptyToolValue(normalized[key])) {
                    section.appendChild(createToolDetailSubsection(key, normalized[key]));
                    handled.add(key);
                }
            });
            ['metadata', 'items', 'artifact_ref'].forEach((key) => {
                if (!isEmptyToolValue(normalized[key])) {
                    section.appendChild(createToolDetailSubsection(key, normalized[key]));
                    handled.add(key);
                }
            });

            const remaining = Object.fromEntries(
                Object.entries(normalized).filter(([key, item]) => !handled.has(key) && !isEmptyToolValue(item))
            );
            if (Object.keys(remaining).length > 0) {
                section.appendChild(createToolDetailSubsection('other', remaining));
            }
        }

        function createToolDetailSubsection(label, value) {
            const wrapper = document.createElement('div');
            wrapper.className = 'tool-status-subsection';

            const subheading = document.createElement('div');
            subheading.className = 'tool-status-sublabel';
            subheading.textContent = label;

            wrapper.appendChild(subheading);
            wrapper.appendChild(createToolDetailBlock(formatToolDetail(value)));
            return wrapper;
        }

        function createToolDetailBlock(value) {
            const block = document.createElement('pre');
            block.className = 'tool-status-block';
            block.textContent = value;
            return block;
        }

        function attachCodeCopyButtons(container) {
            const codeBlocks = container.querySelectorAll('pre');
            codeBlocks.forEach(pre => {
                if (pre.querySelector('.code-copy-button')) return;
                const copyButton = createCopyButton(() => utils.getCopyableText(pre), 'code-copy-button');
                pre.appendChild(copyButton);
            });
        }

        function createCopyButton(getText, extraClass = '') {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `copy-button ${extraClass}`.trim();
            button.setAttribute('aria-label', 'Copy to clipboard');
            button.title = 'Copy to clipboard';
            button.innerHTML = icons.COPY_ICON_SVG;

            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                const text = getText();
                if (!text) {
                    utils.flashCopyFeedback(button, false);
                    return;
                }
                const didCopy = await utils.handleCopy(text);
                utils.flashCopyFeedback(button, didCopy);
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
            button.innerHTML = icons.FORK_ICON_SVG;

            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                await forkCurrentSession(sequenceIndex, button);
            });

            return button;
        }

        async function forkCurrentSession(sequenceIndex, button) {
            const vault = elements.vaultSelector.value;
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
                await callbacks.fetchSessions(vault, forkSessionId);
                await callbacks.loadSession(forkSessionId);
            } catch (error) {
                console.error('Failed to fork chat session:', error);
                addChatErrorMessage(`Fork failed: ${error.message}`);
                button.disabled = previousDisabled;
            }
        }

        return Object.freeze({
            renderEmptyState: renderChatEmptyState,
            refreshEmptyState,
            addErrorMessage: addChatErrorMessage,
            renderPersistedSession,
            addMessage,
            addLoadingMessage,
            removeLoadingMessage,
            createAssistantStreamingMessage,
            renderAssistantMarkdown,
            setAssistantStatus,
            handleToolEvent,
            finalizeAssistantMessage,
        });
    }

    window.ChatRendering = Object.freeze({
        create: createChatRenderingController,
    });
})(window, document);
