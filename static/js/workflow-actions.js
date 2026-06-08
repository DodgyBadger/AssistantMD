(function workflowActionsModule(window, document) {
    function createWorkflowActionsController({ state, elements, utils, callbacks }) {
        const icons = window.AssistantMDIcons;
        // Rescan vaults
        async function rescanVaults() {
            if (!elements.rescanResult) return;

            elements.rescanResult.innerHTML = '<p class="text-txt-secondary">Rescanning...</p>';
            elements.rescanBtn.disabled = true;

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
                    callbacks.populateSelectors();
                } else {
                    await callbacks.fetchMetadata();
                }

                await callbacks.fetchSystemStatus();
                renderRescanResult(data);

            } catch (error) {
                console.error('Error rescanning:', error);
                elements.rescanResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
            } finally {
                elements.rescanBtn.disabled = false;
            }
        }

        function renderRescanResult(data) {
            if (!elements.rescanResult) return;

            const configurationErrors = state.systemStatus?.configuration_errors || [];
            const workflowErrors = configurationErrors.filter((error) => {
                const filePath = String(error.file_path || '');
                return filePath.includes('/AssistantMD/Workflows/');
            });

            elements.rescanResult.innerHTML = `
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
                                    <span class="font-medium">${utils.escapeHtml(error.workflow_name || error.file_path || 'workflow')}</span>:
                                    ${utils.escapeHtml(error.error_message || 'Unknown load error')}
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
                elements.executeWorkflowResult.innerHTML = `
                    <div class="state-surface-success p-3 rounded border">
                        <p class="font-medium">${utils.escapeHtml(data.message || 'Workflow updated.')}</p>
                    </div>
                `;
                await callbacks.fetchSystemStatus();
            } catch (error) {
                console.error('Error updating workflow enabled state:', error);
                elements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
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
                            <h2 id="workflow-file-modal-title" class="text-lg font-semibold text-txt-primary">Workflow: ${utils.escapeHtml(globalId)}</h2>
                            <p id="workflow-file-modal-path" class="mt-1 text-xs text-txt-secondary cell-mono">Loading...</p>
                        </div>
                        <div class="app-modal-actions">
                            <button type="button" class="ui-icon-button is-primary is-compact" data-workflow-file-save="true" aria-label="Save workflow file" title="Save workflow file" disabled>
                                ${icons.SAVE_ICON_SVG}
                            </button>
                            <button type="button" class="ui-icon-button is-compact" data-workflow-file-close="true" aria-label="Close" title="Close">
                                ${icons.X_ICON_SVG}
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
                if (!(target instanceof Element)) {
                    return;
                }
                if (target.closest('[data-workflow-file-close="true"]')) {
                    closeWorkflowFileEditor();
                    return;
                }
                if (target.closest('[data-workflow-file-save="true"]') && editor instanceof HTMLTextAreaElement) {
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
                        await callbacks.fetchSystemStatus();
                        saveButton.disabled = false;
                    } catch (error) {
                        console.error('Error saving workflow file:', error);
                        statusLabel.innerHTML = `<span class="state-error">Error: ${utils.escapeHtml(error.message)}</span>`;
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
                    statusLabel.innerHTML = `<span class="state-error">Error: ${utils.escapeHtml(error.message)}</span>`;
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

            const selectedVault = callbacks.selectedVault();
            const scopeLabel = isSystemTemplate
                ? ` for vault "${selectedVault || '(none selected)'}"`
                : '';
            const confirmed = window.confirm(`Run workflow "${globalId}"${scopeLabel}?`);
            if (!confirmed) {
                return;
            }
            if (isSystemTemplate && !selectedVault) {
                elements.executeWorkflowResult.innerHTML = '<p class="state-error">Select a vault before running a system workflow.</p>';
                return;
            }

            elements.executeWorkflowResult.innerHTML = '<p class="text-txt-secondary">Starting workflow...</p>';
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
                await callbacks.fetchWorkflowTasks({ render: true });
                elements.executeWorkflowResult.innerHTML = `
                    <div class="state-surface-info p-3 rounded border">
                        <p class="font-medium">Workflow started</p>
                        <p>Workflow: ${utils.escapeHtml(globalId)}</p>
                        <p class="text-sm">Task: ${utils.escapeHtml(task.task_id)}</p>
                        <p class="text-sm">Use the Running Workflows list to monitor or stop this task.</p>
                    </div>
                `;
                monitorWorkflowTask(task.task_id);
            } catch (error) {
                console.error('Error executing workflow:', error);
                elements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
                callbacks.displaySystemStatus();
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
                    if (!callbacks.isTerminalTaskStatus(task.status)) {
                        continue;
                    }
                    await callbacks.fetchWorkflowTasks({ render: true });
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
                icons.setIconButtonLabel(triggerButton, 'Stopping workflow...');
            }
            try {
                const response = await fetch(`api/tasks/${encodeURIComponent(taskId)}/cancel`, {
                    method: 'POST'
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                elements.executeWorkflowResult.innerHTML = `
                    <div class="state-surface-info p-3 rounded border">
                        <p class="font-medium">Stop requested</p>
                        <p class="text-sm">Task: ${utils.escapeHtml(taskId)}</p>
                        <p class="text-sm">Files mutated by this workflow will be rolled back when cancellation completes.</p>
                    </div>
                `;
                await callbacks.fetchWorkflowTasks({ render: true });
            } catch (error) {
                console.error('Error stopping workflow:', error);
                elements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
                if (triggerButton) {
                    triggerButton.disabled = false;
                    icons.setIconButtonLabel(triggerButton, 'Stop workflow');
                }
            }
        }

        async function stopAllWorkflows(triggerButton = null) {
            const tasks = callbacks.activeWorkflowTasks();
            if (!tasks.length) {
                elements.executeWorkflowResult.innerHTML = '<p class="text-sm text-txt-secondary">No running workflows to stop.</p>';
                return;
            }
            const confirmed = window.confirm(`Stop ${tasks.length} running workflow task${tasks.length === 1 ? '' : 's'}?`);
            if (!confirmed) {
                return;
            }
            if (triggerButton) {
                triggerButton.disabled = true;
                icons.setIconButtonLabel(triggerButton, 'Stopping all workflows...');
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
                await callbacks.fetchWorkflowTasks({ render: true });
                if (failures.length) {
                    elements.executeWorkflowResult.innerHTML = `
                        <p class="state-error">Stop requested for ${tasks.length - failures.length} workflow task${tasks.length - failures.length === 1 ? '' : 's'}, but ${failures.length} failed.</p>
                    `;
                    return;
                }
                elements.executeWorkflowResult.innerHTML = `
                    <div class="state-surface-info p-3 rounded border">
                        <p class="font-medium">Stop requested for all running workflows</p>
                        <p class="text-sm">${tasks.length} workflow task${tasks.length === 1 ? '' : 's'} will stop and roll back mutated files where applicable.</p>
                    </div>
                `;
            } catch (error) {
                console.error('Error stopping all workflows:', error);
                elements.executeWorkflowResult.innerHTML = `<p class="state-error">❌ Error: ${error.message}</p>`;
            } finally {
                if (triggerButton) {
                    triggerButton.disabled = false;
                    icons.setIconButtonLabel(triggerButton, 'Stop all workflows');
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
            elements.executeWorkflowResult.innerHTML = `
                <div class="${surfaceClass} p-3 rounded border">
                    <p class="font-medium">${utils.escapeHtml(heading)}</p>
                    <p>Workflow: ${utils.escapeHtml(result?.global_id || task?.metadata?.workflow_id || task?.label || '')}</p>
                    ${typeof result?.execution_time_seconds === 'number'
                        ? `<p>Execution time: ${result.execution_time_seconds.toFixed(2)}s</p>`
                        : ''}
                    ${outputFiles.length ? `
                        <p class="mt-2">Output files created:</p>
                        <ul class="list-disc list-inside ml-4">
                            ${outputFiles.map(f => `<li class="text-sm">${utils.escapeHtml(f)}</li>`).join('')}
                        </ul>
                    ` : ''}
                    <p class="mt-2 text-sm">${utils.escapeHtml(result?.message || task?.terminal_reason || '')}</p>
                </div>
            `;
        }

        return Object.freeze({
            rescanVaults,
            toggleWorkflowEnabled,
            openFileEditor: openWorkflowFileEditor,
            executeWorkflow,
            stopWorkflow,
            stopAllWorkflows,
        });
    }

    window.WorkflowActions = Object.freeze({
        create: createWorkflowActionsController,
    });
})(window, document);
