(function chatRenderingModule(window, document) {
    const CHAT_EMPTY_STATE_MESSAGE = 'Start a conversation...';

    function createChatRenderingController({ state, elements, icons, utils, callbacks }) {
        let mathTypesetQueue = Promise.resolve();

        function isChatPlaceholderNode(node) {
            if (!node || !(node instanceof HTMLElement)) return false;
            return node.classList.contains('text-center') &&
                node.classList.contains('text-txt-secondary') &&
                node.classList.contains('text-sm');
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


        function renderPersistedSession(payload) {
            elements.chatMessages.innerHTML = '';

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
