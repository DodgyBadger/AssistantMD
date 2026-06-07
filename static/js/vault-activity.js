(function vaultActivityModule(window, document) {
    function createVaultActivityController({ state, elements, utils, callbacks }) {
        const { escapeHtml, formatShortDate } = utils;

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
            return callbacks.formatChatSessionLabel(session);
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

        function attachEventListeners() {
            if (!elements.vaultActivityStatus) return;
            elements.vaultActivityStatus.addEventListener('change', (event) => {
                if (event.target?.id !== 'vault-activity-selector') return;
                state.selectedActivityVault = event.target.value || '';
                loadVaultActivity(state.selectedActivityVault);
            });
            elements.vaultActivityStatus.addEventListener('click', (event) => {
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

        return Object.freeze({
            renderResult: renderVaultActivityResult,
            loadActivity: loadVaultActivity,
            updateContainer: updateVaultActivityContainer,
            closeDetails: closeVaultActivityDetails,
            attachEventListeners,
        });
    }

    window.VaultActivity = Object.freeze({
        create: createVaultActivityController,
    });
})(window, document);
