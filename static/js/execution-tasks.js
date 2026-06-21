(function executionTaskActionsModule(window) {
    function createExecutionTaskActionsController({ elements, utils, callbacks }) {
        const icons = window.AssistantMDIcons;

        function renderResult(html) {
            const target = elements.executionTaskResult || elements.rescanResult;
            if (target) {
                target.innerHTML = html;
            }
        }

        async function stopExecutionTask(taskId, triggerButton = null) {
            if (!taskId) return;
            if (triggerButton) {
                triggerButton.disabled = true;
                icons.setIconButtonLabel(triggerButton, 'Stopping task...');
            }
            try {
                const response = await fetch(`api/tasks/${encodeURIComponent(taskId)}/cancel`, {
                    method: 'POST',
                    cache: 'no-store'
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || `HTTP ${response.status}`);
                }
                renderResult(`
                    <div class="state-surface-info p-3 rounded border">
                        <p class="font-medium">Stop requested</p>
                        <p class="text-sm">Task: ${utils.escapeHtml(taskId)}</p>
                        <p class="text-sm">Files mutated by this task will be rolled back when cancellation completes, where applicable.</p>
                    </div>
                `);
                await callbacks.fetchExecutionTasks({ render: true });
            } catch (error) {
                console.error('Error stopping task:', error);
                renderResult(`<p class="state-error">❌ Error: ${error.message}</p>`);
                if (triggerButton) {
                    triggerButton.disabled = false;
                    icons.setIconButtonLabel(triggerButton, 'Stop task');
                }
            }
        }

        async function stopAllExecutionTasks(triggerButton = null) {
            const tasks = callbacks.activeExecutionTasks();
            if (!tasks.length) {
                renderResult('<p class="text-sm text-txt-secondary">No running tasks to stop.</p>');
                return;
            }
            const confirmed = window.confirm(`Stop ${tasks.length} running task${tasks.length === 1 ? '' : 's'}?`);
            if (!confirmed) {
                return;
            }
            if (triggerButton) {
                triggerButton.disabled = true;
                icons.setIconButtonLabel(triggerButton, 'Stopping all tasks...');
            }
            try {
                const results = await Promise.allSettled(
                    tasks.map(task => fetch(`api/tasks/${encodeURIComponent(task.task_id)}/cancel`, {
                        method: 'POST',
                        cache: 'no-store'
                    }))
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
                await callbacks.fetchExecutionTasks({ render: true });
                if (failures.length) {
                    const stopped = tasks.length - failures.length;
                    renderResult(`
                        <p class="state-error">Stop requested for ${stopped} task${stopped === 1 ? '' : 's'}, but ${failures.length} failed.</p>
                    `);
                    return;
                }
                renderResult(`
                    <div class="state-surface-info p-3 rounded border">
                        <p class="font-medium">Stop requested for all running tasks</p>
                        <p class="text-sm">${tasks.length} task${tasks.length === 1 ? '' : 's'} will stop and roll back mutated files where applicable.</p>
                    </div>
                `);
            } catch (error) {
                console.error('Error stopping all tasks:', error);
                renderResult(`<p class="state-error">❌ Error: ${error.message}</p>`);
            } finally {
                if (triggerButton) {
                    triggerButton.disabled = false;
                    icons.setIconButtonLabel(triggerButton, 'Stop all tasks');
                }
            }
        }

        return Object.freeze({
            stopExecutionTask,
            stopAllExecutionTasks,
        });
    }

    window.ExecutionTaskActions = Object.freeze({
        create: createExecutionTaskActionsController,
    });
})(window);
