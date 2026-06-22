/**
 * System and dashboard maintenance panel logic.
 *
 * Provides a structured interface for activity logs, model mappings,
 * provider settings, and secrets management without polluting app.js.
 */

(function configurationModule(window, document) {
    const state = {
        initialized: false,
        hasLoadedOnce: false,
        isLoadingLog: false,
        isLoadingSettings: false,
        isLoadingModels: false,
        isSavingModel: false,
        isSavingSetting: false,
        isLoadingProviders: false,
        isSavingProvider: false,
        isLoadingSecrets: false,
        isSavingSecret: false,
        isPurgingCache: false,
        isCleaningGoals: false,
        isCleaningVaultState: false,
        isRefreshingSystemAuthoring: false,
        isLoadingSystemJobs: false,
        isLoadingSystemMigrations: false,
        isRunningSystemMigrations: false,
        isScanningImport: false,
        isLoadingImportVaults: false,
        isImportingUrl: false,
        settings: [],
        models: [],
        providers: [],
        secrets: [],
        importVaults: [],
        importResults: null,
        importUrlResult: null,
        activityLogEntries: [],
        activityLogFilters: {
            query: '',
            levels: ['error', 'warning', 'info', 'debug'],
            tags: [],
            latestFirst: true
        },
        activityLogFilterMenus: {
            level: false,
            tag: false
        },
        systemJobs: [],
        systemMigrations: null,
        settingEditKey: null,
        settingDraftValue: '',
        modelEdit: null,
        modelDraft: null,
        providerEdit: null,
        providerDraft: null,
        openAiOauthPaste: '',
        openAiOauthAuthUrl: '',
        openAiOauthDeviceVerificationUrl: '',
        openAiOauthDeviceUserCode: '',
        openAiOauthDeviceExpiresAt: '',
        openAiOauthDevicePollIntervalSeconds: null,
        isOpenAiOauthBusy: false,
        secretEdit: null,
        secretDraft: null,
        settingsFilter: ''
    };

    const BUILT_IN_PROVIDER_NAMES = new Set(['anthropic', 'google', 'grok', 'mistral', 'openai', 'openrouter']);

    const SECRET_METADATA = {
        OPENAI_API_KEY: { label: 'OpenAI API Key', description: 'Required for OpenAI model aliases' },
        ANTHROPIC_API_KEY: { label: 'Anthropic API Key', description: 'Required for Claude model aliases' },
        GOOGLE_API_KEY: { label: 'Google API Key', description: 'Required for Google Gemini model aliases' },
        GROK_API_KEY: { label: 'Grok API Key', description: 'Required for Grok model aliases' },
        MISTRAL_API_KEY: { label: 'Mistral API Key', description: 'Required for Mistral model aliases' },
        OPENROUTER_API_KEY: { label: 'OpenRouter API Key', description: 'Required for OpenRouter model aliases' },
        TAVILY_API_KEY: { label: 'Tavily API Key', description: 'Required for Tavily search/crawl tools' },
        LOGFIRE_TOKEN: { label: 'Logfire Token', description: 'Enables cloud telemetry when set' },
        LM_STUDIO_API_KEY: { label: 'LM Studio API Key', description: 'Optional key for LM Studio endpoints' },
        LM_STUDIO_BASE_URL: { label: 'LM Studio Base URL', description: 'Custom endpoint for LM Studio (http://host:port)' },
        OLLAMA_API_KEY: { label: 'Ollama API Key', description: 'Optional key for secured Ollama endpoints' },
        OLLAMA_BASE_URL: { label: 'Ollama Base URL', description: 'Custom endpoint for Ollama (http://host:port)' },
    };

    const callbacks = {
        refreshMetadata: null,
        refreshStatus: null
    };

    const elements = {
        activityLogViewer: null,
        refreshActivityLogBtn: null,
        activityLogSearch: null,
        activityLogLevelDropdown: null,
        activityLogLevelTrigger: null,
        activityLogLevelMenu: null,
        activityLogLevelSummary: null,
        activityLogLevelOptions: null,
        activityLogTagDropdown: null,
        activityLogTagTrigger: null,
        activityLogTagMenu: null,
        activityLogTagSummary: null,
        activityLogTagOptions: null,
        activityLogLatestFirst: null,
        activityLogCount: null,

        settingsFeedback: null,
        settingsFilter: null,
        settingsList: null,

        modelFeedback: null,
        modelList: null,
        modelAddBtn: null,

        providerFeedback: null,
        providerList: null,
        providerAddBtn: null,

        secretsList: null,
        secretFeedback: null,
        secretAddBtn: null,

        miscFeedback: null,
        refreshSystemAuthoringBtn: null,
        refreshSystemAuthoringFeedback: null,
        purgeExpiredCacheBtn: null,
        cleanupVaultStateBtn: null,
        cleanupVaultStateFeedback: null,
        systemJobsList: null,
        refreshSystemJobsBtn: null,
        systemMigrationsStatus: null,
        systemMigrationsFeedback: null,
        refreshSystemMigrationsBtn: null,
        runSystemMigrationsBtn: null,
        purgeSessionsVault: null,
        purgeSessionsAge: null,
        purgeSessionsBtn: null,
        purgeSessionsFeedback: null,
        cleanupGoalsVault: null,
        cleanupGoalsStatus: null,
        cleanupGoalsAge: null,
        cleanupGoalsBtn: null,
        cleanupGoalsFeedback: null,

        importVaultSelect: null,
        importPdfModeSelect: null,
        importQueueCheckbox: null,
        importUseOcrCheckbox: null,
        importCaptureOcrImagesCheckbox: null,
        importStatus: null,
        importScanBtn: null,
        importRefreshVaultsBtn: null,
        importResults: null,
        importUrlInput: null,
        importUrlSubmit: null
    };

    const toneClasses = {
        info: 'text-txt-secondary',
        success: 'state-success',
        warning: 'state-warning',
        error: 'state-error'
    };

    function iconButton(iconName, label, extraClass = '', attrs = '') {
        return `class="ui-icon-button is-compact ${extraClass}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" ${attrs}`;
    }

    function iconSvg(iconName) {
        const icon = window.AssistantMDIcons;
        const svgByName = {
            clean: icon.CLEAN_ICON_SVG,
            database: icon.DATABASE_ICON_SVG,
            edit: icon.EDIT_ICON_SVG,
            refresh: icon.REFRESH_ICON_SVG,
            save: icon.SAVE_ICON_SVG,
            trash: icon.TRASH_ICON_SVG,
            x: icon.X_ICON_SVG,
            circleX: icon.CIRCLE_X_ICON_SVG,
        };
        return svgByName[iconName] || icon.SETTINGS_ICON_SVG;
    }

    function setIconButtonLabel(button, label) {
        window.AssistantMDIcons.setIconButtonLabel(button, label);
    }

    function cacheElements() {
        elements.activityLogViewer = document.getElementById('activity-log-viewer');
        elements.refreshActivityLogBtn = document.getElementById('refresh-activity-log');
        elements.activityLogSearch = document.getElementById('activity-log-search');
        elements.activityLogLevelDropdown = document.getElementById('activity-log-level-dropdown');
        elements.activityLogLevelTrigger = document.getElementById('activity-log-level-trigger');
        elements.activityLogLevelMenu = document.getElementById('activity-log-level-menu');
        elements.activityLogLevelSummary = document.getElementById('activity-log-level-summary');
        elements.activityLogLevelOptions = document.getElementById('activity-log-level-options');
        elements.activityLogTagDropdown = document.getElementById('activity-log-tag-dropdown');
        elements.activityLogTagTrigger = document.getElementById('activity-log-tag-trigger');
        elements.activityLogTagMenu = document.getElementById('activity-log-tag-menu');
        elements.activityLogTagSummary = document.getElementById('activity-log-tag-summary');
        elements.activityLogTagOptions = document.getElementById('activity-log-tag-options');
        elements.activityLogLatestFirst = document.getElementById('activity-log-latest-first');
        elements.activityLogCount = document.getElementById('activity-log-count');

        elements.settingsFeedback = document.getElementById('settings-feedback');
        elements.settingsFilter = document.getElementById('settings-filter');
        elements.settingsList = document.getElementById('settings-list');

        elements.modelFeedback = document.getElementById('model-feedback');
        elements.modelList = document.getElementById('model-list');
        elements.modelAddBtn = document.getElementById('model-add-row');

        elements.providerFeedback = document.getElementById('provider-feedback');
        elements.providerList = document.getElementById('provider-list');
        elements.providerAddBtn = document.getElementById('provider-add-row');

        elements.secretsList = document.getElementById('secrets-list');
        elements.secretFeedback = document.getElementById('secret-feedback');
        elements.secretAddBtn = document.getElementById('secret-add-row');

        elements.miscFeedback = document.getElementById('misc-feedback');
        elements.refreshSystemAuthoringBtn = document.getElementById('refresh-system-authoring');
        elements.refreshSystemAuthoringFeedback = document.getElementById('refresh-system-authoring-feedback');
        elements.purgeExpiredCacheBtn = document.getElementById('purge-expired-cache');
        elements.cleanupVaultStateBtn = document.getElementById('cleanup-vault-state');
        elements.cleanupVaultStateFeedback = document.getElementById('cleanup-vault-state-feedback');
        elements.systemJobsList = document.getElementById('system-jobs-list');
        elements.refreshSystemJobsBtn = document.getElementById('refresh-system-jobs');
        elements.systemMigrationsStatus = document.getElementById('system-migrations-status');
        elements.systemMigrationsFeedback = document.getElementById('system-migrations-feedback');
        elements.refreshSystemMigrationsBtn = document.getElementById('refresh-system-migrations');
        elements.runSystemMigrationsBtn = document.getElementById('run-system-migrations');
        elements.purgeSessionsVault = document.getElementById('purge-sessions-vault');
        elements.purgeSessionsAge = document.getElementById('purge-sessions-age');
        elements.purgeSessionsBtn = document.getElementById('purge-sessions-btn');
        elements.purgeSessionsFeedback = document.getElementById('purge-sessions-feedback');
        elements.cleanupGoalsVault = document.getElementById('cleanup-goals-vault');
        elements.cleanupGoalsStatus = document.getElementById('cleanup-goals-status');
        elements.cleanupGoalsAge = document.getElementById('cleanup-goals-age');
        elements.cleanupGoalsBtn = document.getElementById('cleanup-goals-btn');
        elements.cleanupGoalsFeedback = document.getElementById('cleanup-goals-feedback');

        elements.importVaultSelect = document.getElementById('import-vault-select');
        elements.importPdfModeSelect = document.getElementById('import-pdf-mode');
        elements.importQueueCheckbox = document.getElementById('import-queue');
        elements.importUseOcrCheckbox = document.getElementById('import-use-ocr');
        elements.importCaptureOcrImagesCheckbox = document.getElementById('import-capture-ocr-images');
        elements.importStatus = document.getElementById('import-status');
        elements.importScanBtn = document.getElementById('import-scan');
        elements.importRefreshVaultsBtn = document.getElementById('import-refresh-vaults');
        elements.importResults = document.getElementById('import-results');
        elements.importUrlInput = document.getElementById('import-url-input');
        elements.importUrlSubmit = document.getElementById('import-url-submit');
    }

    function bindEvents() {
        elements.refreshActivityLogBtn?.addEventListener('click', () => refreshActivityLog());
        elements.activityLogSearch?.addEventListener('input', handleActivityLogFilterChange);
        elements.activityLogLevelTrigger?.addEventListener('click', () => setActivityLogFilterMenuOpen('level', !state.activityLogFilterMenus.level));
        elements.activityLogLevelOptions?.addEventListener('change', handleActivityLogFilterChange);
        elements.activityLogTagTrigger?.addEventListener('click', () => setActivityLogFilterMenuOpen('tag', !state.activityLogFilterMenus.tag));
        elements.activityLogTagOptions?.addEventListener('change', handleActivityLogFilterChange);
        elements.activityLogLatestFirst?.addEventListener('change', handleActivityLogFilterChange);
        document.addEventListener('click', handleActivityLogDocumentClick);

        elements.settingsList?.addEventListener('click', handleSettingsTableClick);
        elements.settingsList?.addEventListener('input', handleSettingsInputChange);
        elements.settingsFilter?.addEventListener('input', handleSettingsFilterInput);

        elements.modelAddBtn?.addEventListener('click', startNewModel);
        elements.modelList?.addEventListener('click', handleModelTableClick);
        elements.modelList?.addEventListener('input', handleModelInputChange);
        elements.modelList?.addEventListener('change', handleModelInputChange);

        elements.providerAddBtn?.addEventListener('click', startNewProvider);
        elements.providerList?.addEventListener('click', handleProviderTableClick);
        elements.providerList?.addEventListener('input', handleProviderInputChange);
        elements.providerList?.addEventListener('change', handleProviderInputChange);

        elements.secretAddBtn?.addEventListener('click', startNewSecret);
        elements.secretsList?.addEventListener('click', handleSecretsTableClick);
        elements.secretsList?.addEventListener('input', handleSecretInputChange);
        elements.refreshSystemAuthoringBtn?.addEventListener('click', handleRefreshSystemAuthoring);
        elements.purgeExpiredCacheBtn?.addEventListener('click', handlePurgeExpiredCache);
        elements.cleanupVaultStateBtn?.addEventListener('click', handleCleanupVaultState);
        elements.refreshSystemJobsBtn?.addEventListener('click', loadSystemJobs);
        elements.refreshSystemMigrationsBtn?.addEventListener('click', loadSystemMigrations);
        elements.runSystemMigrationsBtn?.addEventListener('click', handleRunSystemMigrations);
        elements.purgeSessionsBtn?.addEventListener('click', handlePurgeSessions);
        elements.cleanupGoalsBtn?.addEventListener('click', handleCleanupGoals);

        elements.importScanBtn?.addEventListener('click', handleImportScan);
        elements.importRefreshVaultsBtn?.addEventListener('click', handleImportVaultRescan);
        elements.importUrlSubmit?.addEventListener('click', handleImportUrl);
        elements.importPdfModeSelect?.addEventListener('change', updateImportOcrAvailability);
    }

    const restartNoticeText = 'Restart recommended: restart the container to apply pending changes.';

    function setStatus(element, message, tone = 'info') {
        if (!element) return;

        element.classList.remove(...Object.values(toneClasses));
        const className = toneClasses[tone] || toneClasses.info;
        element.classList.add(className);
        element.textContent = message;
    }

    function withRestartNotice(message, result) {
        const restart = Boolean(result && result.restart_required);
        if (restart && window.App && typeof window.App.setRestartRequired === 'function') {
            window.App.setRestartRequired(true);
        }
        return {
            text: restart ? `${message} ${restartNoticeText}` : message,
            restart,
        };
    }

    async function refreshActivityLog(limitBytes = 65_536) {
        if (!elements.activityLogViewer || state.isLoadingLog) return;

        state.isLoadingLog = true;
        const refreshBtn = elements.refreshActivityLogBtn;
        const prevLabel = refreshBtn ? (refreshBtn.dataset.iconLabel || refreshBtn.title || 'Refresh Activity Log') : '';

        if (refreshBtn) {
            refreshBtn.disabled = true;
            setIconButtonLabel(refreshBtn, 'Refreshing activity log...');
        }

        elements.activityLogViewer.textContent = 'Loading system log…';

        try {
            const response = await fetch(`api/system/activity-log?limit_bytes=${limitBytes}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            state.activityLog = data;

            state.activityLogEntries = parseActivityLogEntries(data.content || '');
            populateActivityLogFilters();
            renderActivityLog();
        } catch (error) {
            elements.activityLogViewer.textContent = `Failed to load activity log: ${error.message}`;
        } finally {
            if (refreshBtn) {
                refreshBtn.disabled = false;
                setIconButtonLabel(refreshBtn, prevLabel);
            }
            state.isLoadingLog = false;
        }
    }

    async function loadGeneralSettings() {
        if (!elements.settingsList || state.isLoadingSettings) return;

        state.isLoadingSettings = true;
        setStatus(elements.settingsFeedback, 'Loading settings…', 'info');

        try {
            const response = await fetch('api/system/settings/general');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            state.settings = Array.isArray(data) ? data : [];
            state.settingEditKey = null;
            state.settingDraftValue = '';
            renderSettings();
            setStatus(elements.settingsFeedback, '', 'info');
        } catch (error) {
            renderSettings(true);
            setStatus(elements.settingsFeedback, `Failed to load settings: ${error.message}`, 'error');
        } finally {
            state.isLoadingSettings = false;
        }
    }

    function renderSettings(emptyOnError = false) {
        if (!elements.settingsList) return;

        const query = normalizeSearchText(state.settingsFilter);
        const filteredSettings = state.settings.filter((setting) => settingMatchesFilter(setting, query));

        if (!state.settings.length || !filteredSettings.length) {
            const message = emptyOnError
                ? 'Unable to load settings.'
                : state.settings.length
                    ? 'No settings match the current filter.'
                    : 'No configurable settings found.';
            elements.settingsList.innerHTML = `
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    ${escapeHtml(message)}
                </div>
            `;
            return;
        }

        const sortedSettings = [...filteredSettings].sort((a, b) =>
            String(a?.key ?? '').localeCompare(String(b?.key ?? ''), undefined, { sensitivity: 'base' })
        );

        const grouped = groupSettingsByCategory(sortedSettings);
        const cards = grouped.map(([category, settings]) => `
            <section class="space-y-2">
                <div class="text-xs font-semibold uppercase text-txt-secondary">${escapeHtml(category)}</div>
                <div class="flex flex-col gap-3">
                    ${settings.map((setting) => {
                        if (state.settingEditKey === setting.key) {
                            return renderSettingEditCard(setting);
                        }
                        return renderSettingViewCard(setting);
                    }).join('')}
                </div>
            </section>
        `).join('');

        elements.settingsList.innerHTML = cards;
    }

    function normalizeSearchText(value) {
        return String(value || '').trim().toLowerCase();
    }

    function settingMatchesFilter(setting, query) {
        if (!query) return true;
        const haystack = [
            setting.key,
            setting.value,
            setting.description,
            setting.category
        ].map((value) => String(value || '').toLowerCase()).join(' ');
        return haystack.includes(query);
    }

    function groupSettingsByCategory(settings) {
        const groups = new Map();
        settings.forEach((setting) => {
            const category = setting.category || 'Other';
            if (!groups.has(category)) {
                groups.set(category, []);
            }
            groups.get(category).push(setting);
        });
        return Array.from(groups.entries()).sort((a, b) => {
            if (a[0] === 'Other') return 1;
            if (b[0] === 'Other') return -1;
            return a[0].localeCompare(b[0], undefined, { sensitivity: 'base' });
        });
    }

    function renderSettingViewCard(setting) {
        const description = setting.description
            ? `<div class="text-xs text-txt-secondary mt-1">${escapeHtml(setting.description)}</div>`
            : '';

        return `
            <div class="setting-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-setting="${escapeHtml(setting.key)}" data-mode="view" style="max-width: 1400px;">
                <div class="flex flex-col md:flex-row gap-4 md:items-center md:justify-between">
                    <div class="flex-1">
                        <div class="font-semibold text-txt-primary text-sm">${escapeHtml(setting.key)}</div>
                        ${description}
                    </div>
                    <div class="flex items-center gap-4">
                        <div class="text-sm text-txt-primary font-mono bg-app-elevated px-3 py-2 rounded border border-border-primary break-words inline-block max-w-xs">${escapeHtml(setting.value ?? '')}</div>
                        <button data-action="edit-setting" ${iconButton('edit', 'Edit setting', 'is-primary shrink-0')}>${iconSvg('edit')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    function renderSettingEditCard(setting) {
        const description = setting.description
            ? `<div class="text-xs text-txt-secondary mt-1">${escapeHtml(setting.description)}</div>`
            : '';

        const draftValue = state.settingDraftValue ?? setting.value ?? '';

        return `
            <div class="setting-card rounded-lg border border-border-primary bg-app-card editing-highlight px-5 py-4 shadow-sm" data-setting="${escapeHtml(setting.key)}" data-mode="edit" style="max-width: 1400px;">
                <div class="space-y-4">
                    <div>
                        <div class="font-semibold text-txt-primary text-sm">${escapeHtml(setting.key)}</div>
                        ${description}
                    </div>
                    <div class="space-y-2">
                        <input data-field="setting-value" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent font-mono text-sm bg-app-card text-txt-primary transition-colors" value="${escapeHtml(draftValue)}" />
                        <p class="text-xs text-txt-secondary">Values are stored as plain text; lists/objects use JSON.</p>
                    </div>
                    <div class="flex justify-end gap-2">
                        <button data-action="cancel-setting" ${iconButton('circleX', 'Cancel setting edit')}>${iconSvg('circleX')}</button>
                        <button data-action="save-setting" ${iconButton('save', 'Save setting', 'is-primary')}>${iconSvg('save')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    function handleSettingsTableClick(event) {
        const actionButton = event.target.closest('[data-action]');
        if (!actionButton) return;

        const card = actionButton.closest('[data-setting]');
        const settingKey = card?.dataset.setting;
        if (!settingKey) return;

        const action = actionButton.dataset.action;

        if (action === 'edit-setting') {
            startSettingEdit(settingKey);
        } else if (action === 'cancel-setting') {
            cancelSettingEdit();
        } else if (action === 'save-setting') {
            saveSettingValue(settingKey);
        }
    }

    function handleSettingsInputChange(event) {
        if (!state.settingEditKey) return;
        if (event.target.dataset.field === 'setting-value') {
            state.settingDraftValue = event.target.value;
        }
    }

    function handleSettingsFilterInput(event) {
        state.settingsFilter = event.target.value || '';
        renderSettings();
    }

    function startSettingEdit(settingKey) {
        if (state.isSavingSetting) return;

        const setting = state.settings.find((s) => s.key === settingKey);
        if (!setting) return;

        state.settingEditKey = setting.key;
        state.settingDraftValue = setting.value ?? '';
        renderSettings();
        setStatus(elements.settingsFeedback, `Editing '${setting.key}'.`, 'info');
        focusSettingInput();
    }

    function focusSettingInput() {
        requestAnimationFrame(() => {
            const input = elements.settingsList?.querySelector('[data-setting][data-mode="edit"] [data-field="setting-value"]');
            if (input) input.focus();
        });
    }

    function cancelSettingEdit(message = true) {
        state.settingEditKey = null;
        state.settingDraftValue = '';
        renderSettings();
        if (message) {
            setStatus(elements.settingsFeedback, 'Editing cancelled.', 'info');
        }
    }

    async function saveSettingValue(settingKey) {
        if (state.isSavingSetting || !state.settingEditKey) return;

        const value = state.settingDraftValue ?? '';
        state.isSavingSetting = true;
        setStatus(elements.settingsFeedback, 'Saving setting…', 'info');

        try {
            const response = await fetch(`api/system/settings/general/${encodeURIComponent(settingKey)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value })
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            state.settings = state.settings.map((setting) => (setting.key === result.key ? result : setting));
            cancelSettingEdit(false);
            renderSettings();
            await notifyConfigChanged();
            const resultMessage = withRestartNotice(`Saved setting '${result.key}'.`, result);
            setStatus(elements.settingsFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.settingsFeedback, `Failed to save setting: ${error.message}`, 'error');
        } finally {
            state.isSavingSetting = false;
        }
    }

    async function loadProviders() {
        if (!elements.providerList || state.isLoadingProviders) return;

        state.isLoadingProviders = true;
        setStatus(elements.providerFeedback, 'Loading providers…', 'info');

        try {
            const response = await fetch('api/system/providers');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            state.providers = Array.isArray(data) ? data : [];
            if (state.providerEdit && state.providerEdit.mode === 'existing') {
                const stillExists = state.providers.some(provider => provider.name === state.providerEdit.key);
                if (!stillExists) {
                    state.providerEdit = null;
                    state.providerDraft = null;
                }
            }

            renderProviders();
            populateProviderOptions();
            renderModels();
            setStatus(elements.providerFeedback, '', 'info');
        } catch (error) {
            renderProviders(true);
            setStatus(elements.providerFeedback, `Failed to load providers: ${error.message}`, 'error');
        } finally {
            state.isLoadingProviders = false;
        }
    }

    function renderProviders(emptyOnError = false) {
        if (!elements.providerList) return;

        const cards = [];
        const editing = state.providerEdit;
        const draft = state.providerDraft || {};

        if (editing && editing.mode === 'new') {
            cards.push(renderProviderEditCard(draft, { isNew: true }));
        }

        if (!state.providers.length) {
            const message = emptyOnError
                ? 'Unable to load providers.'
                : 'No custom providers configured.';
            cards.push(`
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    ${escapeHtml(message)}
                </div>
            `);
            elements.providerList.innerHTML = cards.join('');
            focusProviderInput();
            return;
        }

        state.providers.forEach((provider) => {
            if (editing && editing.mode === 'existing' && editing.key === provider.name) {
                cards.push(renderProviderEditCard(draft, { isNew: false }));
                return;
            }
            const editable = provider.user_editable === true;
            const isBuiltIn = isBuiltInProviderName(provider.name);
            const isOpenAi = provider.name === 'openai';

            const apiKeyDisplay = provider.api_key
                ? provider.api_key_has_value
                    ? `<div class="flex items-center gap-2">
                        <div class="w-fit"><span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-success border">${'Set'}</span></div>
                        <div class="text-xs text-txt-secondary font-mono">${escapeHtml(provider.api_key)}</div>
                    </div>`
                    : `<div class="flex items-center gap-2">
                        <div class="w-fit"><span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-error border">Not set</span></div>
                        <div class="text-xs state-error">Configure ${escapeHtml(provider.api_key)}</div>
                    </div>`
                : `<div class="flex items-center gap-2"><span class="text-sm text-txt-secondary">No key required</span></div>`;

            const baseUrlDisplay = provider.base_url
                ? provider.base_url_has_value
                    ? `<div class="flex items-center gap-2">
                        <div class="w-fit"><span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-success border">Set</span></div>
                        <div class="text-xs text-txt-secondary font-mono">${escapeHtml(provider.base_url)}</div>
                    </div>`
                    : `<div class="flex items-center gap-2">
                        <div class="w-fit"><span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-error border">Not set</span></div>
                        <div class="text-xs state-error">Configure ${escapeHtml(provider.base_url)}</div>
                    </div>`
                : `<div class="flex items-center gap-2"><span class="text-sm text-txt-secondary">No base URL configured</span></div>`;

            const actions = [
                editable
                    ? `<button data-action="edit" data-provider="${escapeHtml(provider.name)}" ${iconButton('edit', 'Edit provider', 'is-primary')}>${iconSvg('edit')}</button>`
                    : '',
                editable && !isBuiltIn
                    ? `<button data-action="delete" data-provider="${escapeHtml(provider.name)}" ${iconButton('trash', 'Delete provider', 'is-danger')}>${iconSvg('trash')}</button>`
                    : '',
            ].join('');

            const providerMeta = isBuiltIn
                ? '<div class="text-xs text-txt-secondary mt-0.5">Built-in provider</div>'
                : '';
            const openAiOAuthPanel = isOpenAi ? renderOpenAiOAuthPanel(provider) : '';

            cards.push(`
                <div class="provider-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-provider-row="${escapeHtml(provider.name)}" style="max-width: 1400px;">
                    <div class="space-y-4">
                        <div class="flex items-center justify-between gap-4">
                            <div>
                                <div class="font-semibold text-txt-primary text-sm">${escapeHtml(provider.name)}</div>
                                ${providerMeta}
                            </div>
                            <div class="flex gap-2 shrink-0">
                                ${actions}
                            </div>
                        </div>
                        <div class="grid gap-6 md:grid-cols-2">
                            <div>
                                <div class="text-xs font-medium text-txt-secondary mb-2">API Key</div>
                                <div>${apiKeyDisplay}</div>
                            </div>
                            <div>
                                <div class="text-xs font-medium text-txt-secondary mb-2">Base URL</div>
                                <div>${baseUrlDisplay}</div>
                            </div>
                        </div>
                        ${openAiOAuthPanel}
                    </div>
                </div>
            `);
        });

        elements.providerList.innerHTML = cards.join('');
        focusProviderInput();
    }

    function populateProviderOptions() {
        // provider options are built per-row during render; nothing to do here.
    }

    function isBuiltInProviderName(name) {
        return BUILT_IN_PROVIDER_NAMES.has(String(name || '').toLowerCase());
    }

    function renderOpenAiOAuthUnsupportedWarning(extraClass = '') {
        const classSuffix = extraClass ? ` ${extraClass}` : '';
        return `
            <div class="rounded-md border border-border-secondary bg-app-card px-3 py-2 text-xs state-warning${classSuffix}">
                OpenAI OAuth is experimental and is not officially supported by OpenAI for AssistantMD. Use it at your own risk: it could break if OpenAI changes the flow, and your account could be disabled if OpenAI decides to restrict this access.
            </div>
        `;
    }

    function renderOpenAiOAuthPanel(provider) {
        const oauthEnabled = provider.oauth_enabled === true;
        const oauthStatus = provider.oauth_status || 'disabled';
        const connected = oauthStatus === 'connected';
        const pending = oauthStatus === 'pending';
        const canClearOAuth = connected || pending;
        const pendingFlow = provider.oauth_pending_flow || '';
        const disabledReason = provider.oauth_disabled_reason || '';
        const accountText = provider.oauth_account_id ? `Account ${provider.oauth_account_id}` : 'No account connected';
        const expiresText = provider.oauth_expires_at ? `Expires ${formatDateTime(provider.oauth_expires_at)}` : 'No token expiry recorded';
        const refreshText = provider.oauth_last_refresh_at ? `Last refresh ${formatDateTime(provider.oauth_last_refresh_at)}` : 'No refresh recorded';
        const fallbackText = provider.oauth_api_key_fallback_enabled
            ? provider.oauth_api_key_fallback_available
                ? 'API key fallback enabled and available'
                : 'API key fallback enabled but no key is set'
            : 'API key fallback disabled';
        const selectedMode = formatAuthMode(provider.configured_auth_mode);
        const activeMode = formatAuthMode(provider.effective_auth_mode);
        const selectedModeText = provider.configured_auth_mode && provider.configured_auth_mode !== provider.effective_auth_mode
            ? `Selected ${selectedMode}`
            : '';
        const providerStatusMessage = provider.status_message || '';
        const statusTone = connected ? 'pill-success' : pending ? 'pill-warning' : 'pill-error';
        const disableControls = state.isOpenAiOauthBusy || !oauthEnabled;
        const disabledAttr = disableControls ? 'disabled' : '';
        const pasteValue = escapeHtml(state.openAiOauthPaste || '');
        const authUrl = state.openAiOauthAuthUrl || '';
        const authUrlValue = escapeHtml(authUrl);
        const deviceVerificationUrl = provider.oauth_device_verification_url || state.openAiOauthDeviceVerificationUrl || '';
        const deviceUserCode = provider.oauth_device_user_code || state.openAiOauthDeviceUserCode || '';
        const deviceExpiresAt = provider.oauth_pending_expires_at || state.openAiOauthDeviceExpiresAt || '';
        const devicePollInterval = provider.oauth_device_poll_interval_seconds || state.openAiOauthDevicePollIntervalSeconds;
        const authUrlPanel = authUrl
            ? `<div class="mt-3 space-y-2">
                    <div class="text-xs font-medium text-txt-secondary">OpenAI auth URL</div>
                    <textarea readonly class="w-full min-h-[76px] px-3 py-2 border border-border-secondary rounded-md bg-app-card text-txt-primary text-xs font-mono resize-y">${authUrlValue}</textarea>
                    <a href="${authUrlValue}" target="_blank" rel="noopener" class="inline-flex text-xs text-accent hover:text-accent-hover">Open in browser</a>
                </div>`
            : '';
        const devicePanel = deviceVerificationUrl || deviceUserCode
            ? `<div class="mt-3 rounded-md border border-border-secondary bg-app-card px-3 py-3 space-y-2">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <div class="text-xs font-medium text-txt-secondary">Device code</div>
                        ${pendingFlow ? `<div class="text-xs text-txt-secondary">${escapeHtml(pendingFlow === 'device_code' ? 'Device flow pending' : 'Browser flow pending')}</div>` : ''}
                    </div>
                    ${deviceVerificationUrl ? `<a href="${escapeHtml(deviceVerificationUrl)}" target="_blank" rel="noopener" class="inline-flex text-xs text-accent hover:text-accent-hover">${escapeHtml(deviceVerificationUrl)}</a>` : ''}
                    ${deviceUserCode ? `<div class="inline-flex items-center rounded-md border border-border-secondary bg-app-elevated px-3 py-2 font-mono text-sm tracking-wide text-txt-primary">${escapeHtml(deviceUserCode)}</div>` : ''}
                    <div class="text-xs text-txt-secondary">${deviceExpiresAt ? `Expires ${escapeHtml(formatDateTime(deviceExpiresAt))}` : ''}${devicePollInterval ? ` · Check every ${escapeHtml(String(devicePollInterval))}s` : ''}</div>
                </div>`
            : '';

        return `
            <div class="rounded-lg border border-border-secondary bg-app-elevated px-4 py-3">
                <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div class="space-y-2">
                        <div class="flex flex-wrap items-center gap-2">
                            <span class="text-xs font-medium text-txt-secondary">OpenAI OAuth</span>
                            <span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${statusTone} border">${escapeHtml(formatOAuthStatus(oauthStatus))}</span>
                        </div>
                        <div class="text-xs text-txt-secondary">Using ${escapeHtml(activeMode)}${selectedModeText ? ` · ${escapeHtml(selectedModeText)}` : ''}</div>
                        <div class="text-xs text-txt-secondary">${escapeHtml(accountText)} · ${escapeHtml(expiresText)} · ${escapeHtml(refreshText)}</div>
                        <div class="text-xs text-txt-secondary">${escapeHtml(fallbackText)}</div>
                        ${providerStatusMessage ? `<div class="text-xs state-warning">${escapeHtml(providerStatusMessage)}</div>` : ''}
                        ${provider.oauth_last_refresh_error ? `<div class="text-xs state-error">${escapeHtml(provider.oauth_last_refresh_error)}</div>` : ''}
                        ${!oauthEnabled ? `<div class="text-xs state-warning">${escapeHtml(disabledReason || 'Disabled by openai_oauth_enabled.')}</div>` : ''}
                    </div>
                    <div class="flex flex-wrap gap-2 justify-end">
                        <button type="button" data-action="openai-oauth-start" class="px-3 py-2 rounded-md border border-border-secondary bg-app-card text-xs font-medium text-txt-primary hover:border-border-secondary disabled:opacity-50 disabled:cursor-not-allowed" ${disabledAttr}>${connected ? 'Reconnect' : 'Connect'}</button>
                        <button type="button" data-action="openai-oauth-device-start" class="px-3 py-2 rounded-md border border-border-secondary bg-app-card text-xs font-medium text-txt-primary hover:border-border-secondary disabled:opacity-50 disabled:cursor-not-allowed" ${disabledAttr}>Device Code</button>
                        <button type="button" data-action="openai-oauth-device-check" class="px-3 py-2 rounded-md border border-border-secondary bg-app-card text-xs font-medium text-txt-primary hover:border-border-secondary disabled:opacity-50 disabled:cursor-not-allowed" ${state.isOpenAiOauthBusy || !oauthEnabled || pendingFlow !== 'device_code' ? 'disabled' : ''}>Check Status</button>
                        <button type="button" data-action="openai-oauth-disconnect" class="px-3 py-2 rounded-md border border-border-secondary bg-app-card text-xs font-medium text-txt-primary hover:border-border-secondary disabled:opacity-50 disabled:cursor-not-allowed" ${state.isOpenAiOauthBusy || !canClearOAuth ? 'disabled' : ''}>${pending ? 'Cancel' : 'Disconnect'}</button>
                    </div>
                </div>
                ${renderOpenAiOAuthUnsupportedWarning('mt-3')}
                <div class="mt-3 flex flex-col gap-2 md:flex-row">
                    <input data-openai-oauth-paste class="w-full flex-1 px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="Paste the final redirect URL or code" value="${pasteValue}" ${disabledAttr} />
                    <button type="button" data-action="openai-oauth-complete" class="shrink-0 px-3 py-2 rounded-md bg-accent text-white text-xs font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed" ${disableControls || !state.openAiOauthPaste.trim() ? 'disabled' : ''}>Complete OAuth</button>
                </div>
                ${authUrlPanel}
                ${devicePanel}
            </div>
        `;
    }

    function formatOAuthStatus(status) {
        const labels = {
            connected: 'Connected',
            pending: 'Pending',
            disconnected: 'Disconnected',
            disabled: 'Disabled',
        };
        return labels[status] || status || 'Unknown';
    }

    function formatAuthMode(mode) {
        return mode === 'oauth' ? 'OAuth' : 'API key';
    }

    function formatDateTime(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString();
    }

    function renderProviderEditCard(draft, { isNew }) {
        const rowKey = isNew ? '__new' : (state.providerEdit?.key || draft.name || '');
        const nameReadonly = isNew ? '' : 'readonly';
        const nameHelp = isNew
            ? 'Provider names identify custom endpoints used by models.'
            : 'Provider names are identities and cannot be renamed here.';
        const isOpenAiDraft = !isNew && draft.name === 'openai';
        const openAiAuthControls = isOpenAiDraft
            ? `
                <div class="rounded-lg border border-border-secondary bg-app-elevated px-4 py-3">
                    <div class="grid gap-4 md:grid-cols-2">
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Auth Mode</label>
                            <select data-provider-field="auth_mode" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors">
                                <option value="api_key" ${(draft.auth_mode || 'api_key') === 'api_key' ? 'selected' : ''}>API key</option>
                                <option value="oauth" ${draft.auth_mode === 'oauth' ? 'selected' : ''}>OAuth</option>
                            </select>
                            <p class="text-xs text-txt-secondary mt-1">OAuth requires openai_oauth_enabled and a connected account.</p>
                            ${draft.auth_mode === 'oauth' ? renderOpenAiOAuthUnsupportedWarning('mt-2') : ''}
                        </div>
                        <label class="flex items-start gap-3 rounded-md border border-border-secondary px-3 py-2">
                            <input data-provider-field="oauth_api_key_fallback_enabled" type="checkbox" class="mt-1 h-4 w-4 rounded border-border-secondary text-accent focus:ring-accent" ${draft.oauth_api_key_fallback_enabled ? 'checked' : ''} />
                            <span>
                                <span class="block text-xs font-medium text-txt-primary">Allow API key fallback</span>
                                <span class="block text-xs text-txt-secondary mt-1">Only use the API key when OAuth cannot be used.</span>
                            </span>
                        </label>
                    </div>
                </div>
            `
            : '';
        return `
            <div class="provider-card rounded-lg border border-border-primary bg-app-card editing-highlight px-5 py-4 shadow-sm" data-provider-row="${escapeHtml(rowKey)}" data-mode="edit" style="max-width: 1400px;">
                <div class="space-y-4">
                    <div class="grid gap-4 md:grid-cols-3">
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Provider Name</label>
                            <input data-provider-field="name" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="e.g. local-ollama" value="${escapeHtml(draft.name || '')}" ${nameReadonly} />
                            <p class="text-xs text-txt-secondary mt-1">${nameHelp}</p>
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">API Key Secret</label>
                            <input data-provider-field="api_key" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="SECRET_NAME (optional)" value="${escapeHtml(draft.api_key || '')}" />
                            <p class="text-xs text-txt-secondary mt-1">Enter the secret name; set the value in Secrets.</p>
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Base URL Secret</label>
                            <input data-provider-field="base_url" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="SECRET_NAME (optional)" value="${escapeHtml(draft.base_url || '')}" />
                            <p class="text-xs text-txt-secondary mt-1">Store base URLs as secrets; enter the secret name here.</p>
                        </div>
                    </div>
                    ${openAiAuthControls}
                    <div class="flex justify-end gap-2">
                        <button data-action="cancel-provider" ${iconButton('circleX', 'Cancel provider edit')}>${iconSvg('circleX')}</button>
                        <button data-action="save-provider" ${iconButton('save', 'Save provider', 'is-primary')}>${iconSvg('save')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    function focusProviderInput(field = 'name') {
        if (!state.providerEdit) return;
        requestAnimationFrame(() => {
            const editableName = state.providerEdit?.mode === 'new';
            const targetField = editableName ? field : (field === 'name' ? 'api_key' : field);
            const el = elements.providerList?.querySelector(`[data-provider-row][data-mode="edit"] [data-provider-field="${targetField}"]`);
            if (el instanceof HTMLInputElement) {
                el.focus();
                el.select();
            }
        });
    }

    async function loadModels() {
        if (!elements.modelList || state.isLoadingModels) return;

        state.isLoadingModels = true;
        setStatus(elements.modelFeedback, 'Loading models…', 'info');

        try {
            const response = await fetch('api/system/models');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            state.models = Array.isArray(data) ? data : [];

            if (state.modelEdit && state.modelEdit.mode === 'existing') {
                const stillExists = state.models.some(m => m.name === state.modelEdit.key);
                if (!stillExists) {
                    state.modelEdit = null;
                    state.modelDraft = null;
                }
            }

            renderModels();
            setStatus(elements.modelFeedback, '', 'info');
        } catch (error) {
            renderModels(true);
            setStatus(elements.modelFeedback, `Failed to load models: ${error.message}`, 'error');
        } finally {
            state.isLoadingModels = false;
        }
    }

    function renderModels(emptyOnError = false) {
        if (!elements.modelList) return;

        const cards = [];
        const editing = state.modelEdit;
        const draft = state.modelDraft || {};

        if (editing && editing.mode === 'new') {
            cards.push(renderModelEditCard(draft, { isNew: true }));
        }

        if (!state.models.length) {
            const message = emptyOnError ? 'Unable to load model mappings.' : 'No models configured.';
            cards.push(`
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    ${escapeHtml(message)}
                </div>
            `);
        } else {
            state.models.forEach((model) => {
                if (editing && editing.mode === 'existing' && editing.key === model.name) {
                    cards.push(renderModelEditCard(draft, { isNew: false }));
                } else {
                    cards.push(renderModelViewCard(model));
                }
            });
        }

        elements.modelList.innerHTML = cards.join('');
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char]));
    }

    function parseActivityLogEntries(content) {
        return (content || '')
            .split(/\r?\n/)
            .map((line, index) => parseActivityLogLine(line, index))
            .filter(Boolean);
    }

    function parseActivityLogLine(line, index) {
        const trimmed = (line || '').trim();
        if (!trimmed) return null;

        try {
            const record = JSON.parse(trimmed);
            const data = record && typeof record.data === 'object' && record.data !== null ? record.data : {};
            const searchText = [
                record.timestamp,
                record.level,
                record.tag,
                record.message,
                JSON.stringify(data)
            ].filter(Boolean).join(' ').toLowerCase();

            return {
                index,
                raw: trimmed,
                parsed: true,
                timestamp: record.timestamp || '',
                level: String(record.level || '').toLowerCase(),
                tag: record.tag || '',
                message: record.message || '',
                data,
                bootId: record.boot_id ?? null,
                searchText
            };
        } catch {
            return {
                index,
                raw: trimmed,
                parsed: false,
                timestamp: '',
                level: '',
                tag: '',
                message: trimmed,
                data: {},
                bootId: null,
                searchText: trimmed.toLowerCase()
            };
        }
    }

    function handleActivityLogFilterChange() {
        state.activityLogFilters = {
            query: (elements.activityLogSearch?.value || '').trim().toLowerCase(),
            levels: getCheckedActivityLogFilterValues(elements.activityLogLevelOptions),
            tags: getCheckedActivityLogFilterValues(elements.activityLogTagOptions),
            latestFirst: Boolean(elements.activityLogLatestFirst?.checked)
        };
        updateActivityLogFilterSummaries();
        renderActivityLog();
    }

    function populateActivityLogFilters() {
        renderActivityLogLevelOptions();
        renderActivityLogTagOptions();
        updateActivityLogFilterSummaries();
    }

    function renderActivityLogLevelOptions() {
        if (!elements.activityLogLevelOptions) return;

        const levels = ['error', 'warning', 'info', 'debug'];
        const selected = new Set(Array.isArray(state.activityLogFilters.levels) ? state.activityLogFilters.levels : levels);
        elements.activityLogLevelOptions.innerHTML = levels
            .map((level) => renderActivityLogCheckbox('level', level, formatActivityLogLevelLabel(level), selected.has(level)))
            .join('');
        state.activityLogFilters.levels = getCheckedActivityLogFilterValues(elements.activityLogLevelOptions);
    }

    function renderActivityLogTagOptions() {
        if (!elements.activityLogTagOptions) return;

        const previousOptions = Array.from(elements.activityLogTagOptions.querySelectorAll('input[type="checkbox"]')).map((input) => input.value);
        const previousSelected = getCheckedActivityLogFilterValues(elements.activityLogTagOptions);
        const previousWasAll = previousOptions.length === 0 || previousSelected.length === previousOptions.length;
        const tags = [...new Set(state.activityLogEntries.map((entry) => entry.tag).filter(Boolean))].sort();
        const selected = previousWasAll ? new Set(tags) : new Set(previousSelected.filter((tag) => tags.includes(tag)));

        elements.activityLogTagOptions.innerHTML = tags.length
            ? tags.map((tag) => renderActivityLogCheckbox('tag', tag, tag, selected.has(tag))).join('')
            : '<div class="tool-dropdown-menu-header">No tags loaded.</div>';
        state.activityLogFilters.tags = getCheckedActivityLogFilterValues(elements.activityLogTagOptions);
    }

    function renderActivityLogCheckbox(group, value, label, checked) {
        const id = `activity-log-${group}-${value.replace(/[^a-z0-9_-]/gi, '-')}`;
        return `
            <div class="tool-checkbox-wrapper">
                <label for="${escapeHtml(id)}">
                    <input id="${escapeHtml(id)}" type="checkbox" value="${escapeHtml(value)}" ${checked ? 'checked' : ''}>
                    <span class="tool-checkbox-name">${escapeHtml(label)}</span>
                </label>
            </div>
        `;
    }

    function getCheckedActivityLogFilterValues(container) {
        return Array.from(container?.querySelectorAll('input[type="checkbox"]:checked') || [])
            .map((input) => input.value);
    }

    function updateActivityLogFilterSummaries() {
        updateActivityLogFilterSummary(
            elements.activityLogLevelSummary,
            state.activityLogFilters.levels,
            ['error', 'warning', 'info', 'debug'],
            'All levels',
            'No levels'
        );
        const allTags = [...new Set(state.activityLogEntries.map((entry) => entry.tag).filter(Boolean))].sort();
        updateActivityLogFilterSummary(
            elements.activityLogTagSummary,
            state.activityLogFilters.tags,
            allTags,
            'All tags',
            'No tags'
        );
    }

    function updateActivityLogFilterSummary(element, selectedValues, allValues, allLabel, noneLabel) {
        if (!element) return;
        if (!allValues.length || !selectedValues.length) {
            element.textContent = noneLabel;
            return;
        }
        if (selectedValues.length === allValues.length) {
            element.textContent = allLabel;
            return;
        }
        element.textContent = `${selectedValues.length} selected`;
    }

    function formatActivityLogLevelLabel(level) {
        return {
            error: 'Error',
            warning: 'Warning',
            info: 'Info',
            debug: 'Debug'
        }[level] || level;
    }

    function setActivityLogFilterMenuOpen(menu, open) {
        state.activityLogFilterMenus[menu] = Boolean(open);
        if (open) {
            const otherMenu = menu === 'level' ? 'tag' : 'level';
            state.activityLogFilterMenus[otherMenu] = false;
            const otherDropdown = otherMenu === 'level' ? elements.activityLogLevelDropdown : elements.activityLogTagDropdown;
            const otherTrigger = otherMenu === 'level' ? elements.activityLogLevelTrigger : elements.activityLogTagTrigger;
            const otherPanel = otherMenu === 'level' ? elements.activityLogLevelMenu : elements.activityLogTagMenu;
            otherDropdown?.classList.remove('open');
            otherPanel?.classList.add('hidden');
            otherTrigger?.setAttribute('aria-expanded', 'false');
        }
        const dropdown = menu === 'level' ? elements.activityLogLevelDropdown : elements.activityLogTagDropdown;
        const trigger = menu === 'level' ? elements.activityLogLevelTrigger : elements.activityLogTagTrigger;
        const panel = menu === 'level' ? elements.activityLogLevelMenu : elements.activityLogTagMenu;

        dropdown?.classList.toggle('open', state.activityLogFilterMenus[menu]);
        panel?.classList.toggle('hidden', !state.activityLogFilterMenus[menu]);
        trigger?.setAttribute('aria-expanded', state.activityLogFilterMenus[menu] ? 'true' : 'false');
    }

    function handleActivityLogDocumentClick(event) {
        const target = event.target;
        if (!(target instanceof Node)) return;

        if (state.activityLogFilterMenus.level && !elements.activityLogLevelDropdown?.contains(target)) {
            setActivityLogFilterMenuOpen('level', false);
        }
        if (state.activityLogFilterMenus.tag && !elements.activityLogTagDropdown?.contains(target)) {
            setActivityLogFilterMenuOpen('tag', false);
        }
    }

    function renderActivityLog() {
        if (!elements.activityLogViewer) return;

        const entries = getFilteredActivityLogEntries();
        if (elements.activityLogCount) {
            const total = state.activityLogEntries.length;
            const shown = entries.length;
            const truncated = state.activityLog?.truncated ? ' Loaded from truncated log window.' : '';
            elements.activityLogCount.textContent = `${shown} of ${total} entries shown.${truncated}`;
        }

        if (!state.activityLogEntries.length) {
            elements.activityLogViewer.innerHTML = '<div class="p-3 text-txt-secondary">No activity log entries loaded.</div>';
            return;
        }

        if (!entries.length) {
            elements.activityLogViewer.innerHTML = '<div class="p-3 text-txt-secondary">No entries match the current filters.</div>';
            return;
        }

        elements.activityLogViewer.innerHTML = entries.map(renderActivityLogEntry).join('');
        elements.activityLogViewer.scrollTop = state.activityLogFilters.latestFirst ? 0 : elements.activityLogViewer.scrollHeight;
    }

    function getFilteredActivityLogEntries() {
        const filters = state.activityLogFilters;
        let entries = state.activityLogEntries.filter((entry) => {
            if (!filters.levels.includes(entry.level)) return false;
            if (entry.tag && !filters.tags.includes(entry.tag)) return false;
            if (filters.query && !entry.searchText.includes(filters.query)) return false;
            return true;
        });

        if (filters.latestFirst) {
            entries = [...entries].reverse();
        }
        return entries;
    }

    function renderActivityLogEntry(entry) {
        const levelClass = activityLogLevelClass(entry.level);
        const time = formatActivityLogTimestamp(entry.timestamp);
        const dataSummary = summarizeActivityLogData(entry.data, entry.bootId);

        return `
            <div class="activity-log-row ${levelClass}">
                <div class="text-txt-secondary">${escapeHtml(time || 'unknown time')}</div>
                <div class="font-semibold uppercase">${escapeHtml(entry.level || 'raw')}</div>
                <div class="text-txt-primary">${escapeHtml(entry.tag || 'unstructured')}</div>
                <div>
                    <div class="text-txt-primary">${escapeHtml(entry.message)}</div>
                    ${dataSummary ? `<div class="activity-log-meta">${dataSummary}</div>` : ''}
                </div>
            </div>
        `;
    }

    function activityLogLevelClass(level) {
        if (level === 'error' || level === 'critical' || level === 'fatal') return 'log-level-error';
        if (level === 'warning' || level === 'warn') return 'log-level-warn';
        if (level === 'info') return 'log-level-info';
        if (level === 'debug') return 'log-level-debug';
        return '';
    }

    function formatActivityLogTimestamp(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return timestamp;
        return date.toLocaleString(undefined, {
            month: 'short',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    function summarizeActivityLogData(data, bootId) {
        const fields = [];
        if (data && typeof data === 'object') {
            Object.entries(data).forEach(([key, value]) => {
                if (value === undefined || value === null || value === '') return;
                fields.push([key, value]);
            });
        }
        if (bootId !== null && bootId !== undefined) {
            fields.push(['boot_id', bootId]);
        }

        return fields
            .map(([key, value]) => {
                const rendered = typeof value === 'string' ? value : JSON.stringify(value);
                return `<span>${escapeHtml(key)}=${escapeHtml(truncateActivityLogValue(rendered))}</span>`;
            })
            .join('');
    }

    function truncateActivityLogValue(value, limit = 140) {
        const text = String(value ?? '');
        return text.length > limit ? `${text.slice(0, limit)}...` : text;
    }

    function buildProviderOptions(selected) {
        if (!state.providers.length) {
            return '<option value="">No providers available</option>';
        }

        return state.providers.map((provider) => {
            const isSelected = provider.name === selected ? 'selected' : '';
            const label = provider.user_editable === false
                ? `${provider.name} (built-in)`
                : provider.name;
            return `<option value="${escapeHtml(provider.name)}" ${isSelected}>${escapeHtml(label)}</option>`;
        }).join('');
    }

    function renderModelViewCard(model) {
        const editable = model.user_editable !== false;
        const availabilityBadge = model.available
            ? '<span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-success border">Available</span>'
            : '<span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-error border">Unavailable</span>';

        const reasonLine = model.status_message && !model.available
            ? `<div class="text-xs state-error mt-1">${escapeHtml(model.status_message)}</div>`
            : '';
        const capabilities = Array.isArray(model.capabilities) && model.capabilities.length
            ? model.capabilities.join(', ')
            : 'text';

        const actions = editable
            ? `
                <button data-action="edit" data-model="${escapeHtml(model.name)}" ${iconButton('edit', 'Edit model', 'is-primary')}>${iconSvg('edit')}</button>
                <button data-action="delete" data-model="${escapeHtml(model.name)}" ${iconButton('trash', 'Delete model', 'is-danger')}>${iconSvg('trash')}</button>
            `
            : `<span class="inline-block px-2 py-0.5 text-xs text-txt-secondary bg-app-elevated rounded border border-border-primary">Read-only</span>`;

        return `
            <div class="model-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-row="${escapeHtml(model.name)}" data-mode="view" style="max-width: 1400px;">
                <div class="space-y-4">
                    <div class="flex items-start justify-between gap-4">
                        <div class="min-w-0">
                            <div class="font-semibold text-txt-primary text-sm">${escapeHtml(model.name)}</div>
                            <div class="flex items-center gap-2 mt-1">
                                <div class="w-fit">${availabilityBadge}</div>
                            </div>
                            ${reasonLine}
                        </div>
                        <div class="flex gap-2 shrink-0">
                            ${actions}
                        </div>
                    </div>
                    <div class="flex gap-6 items-start flex-wrap">
                        <div>
                            <div class="text-xs font-medium text-txt-secondary mb-1">Provider</div>
                            <div class="text-sm text-txt-primary">${escapeHtml(model.provider)}</div>
                        </div>
                        <div>
                            <div class="text-xs font-medium text-txt-secondary mb-1">Model Identifier</div>
                            <div class="text-xs font-mono text-txt-primary bg-app-elevated px-2 py-1 rounded border border-border-primary inline-block max-w-xs break-words">${escapeHtml(model.model_string)}</div>
                        </div>
                        <div>
                            <div class="text-xs font-medium text-txt-secondary mb-1">Capabilities</div>
                            <div class="text-xs text-txt-primary bg-app-elevated px-2 py-1 rounded border border-border-primary inline-block max-w-xs break-words">${escapeHtml(capabilities)}</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderModelEditCard(draft, { isNew }) {
        const rowKey = isNew ? '__new' : (state.modelEdit?.key || draft.name || '');
        const selectedProvider = draft.provider !== undefined ? draft.provider : (state.providers[0]?.name || '');
        const providerOptions = buildProviderOptions(selectedProvider);

        const providerDisabled = state.providers.length === 0 ? 'disabled' : '';

        const renameHint = isNew
            ? '<p class="text-xs text-txt-secondary mt-1">Lowercase alias used in assistant files.</p>'
            : '<p class="text-xs text-txt-secondary mt-1">Renaming updates the model alias used in assistants.</p>';

        return `
            <div class="model-card rounded-lg border border-border-primary bg-app-card editing-highlight px-5 py-4 shadow-sm" data-row="${escapeHtml(rowKey)}" data-mode="edit" style="max-width: 1400px;">
                <div class="space-y-4">
                    <div class="grid gap-4 md:grid-cols-2">
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Model Name</label>
                            <input data-field="name" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="e.g. planning" value="${escapeHtml(draft.name || '')}" />
                            ${renameHint}
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Provider</label>
                            <select data-field="provider" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" ${providerDisabled}>
                                ${providerOptions}
                            </select>
                            <p class="text-xs text-txt-secondary mt-1">${state.providers.length ? 'Select the provider powering this model.' : 'Add a provider before creating models.'}</p>
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-txt-primary mb-1.5">Model Identifier</label>
                        <input data-field="model_string" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary font-mono text-sm transition-colors" placeholder="e.g. claude-sonnet-4-5" value="${escapeHtml(draft.model_string || '')}" />
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-txt-primary mb-1.5">Capabilities</label>
                        <input data-field="capabilities" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="e.g. text, vision" value="${escapeHtml(draft.capabilities || 'text')}" />
                        <p class="text-xs text-txt-secondary mt-1">Comma-separated values. Example: <code>text, vision</code>.</p>
                    </div>
                    <div class="flex justify-end gap-2">
                        <button data-action="cancel-model" ${iconButton('circleX', 'Cancel model edit')}>${iconSvg('circleX')}</button>
                        <button data-action="save-model" ${iconButton('save', 'Save model', 'is-primary')}>${iconSvg('save')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    function focusModelInput(field) {
        requestAnimationFrame(() => {
            const el = elements.modelList?.querySelector(`[data-row][data-mode="edit"] [data-field="${field}"]`);
            if (el) {
                el.focus();
            }
        });
    }

    function handleModelTableClick(event) {
        const actionButton = event.target.closest('[data-action]');
        if (!actionButton) return;

        const rowEl = actionButton.closest('[data-row]');
        const rowKey = rowEl?.dataset.row;
        const action = actionButton.dataset.action;

        if (action === 'edit' && rowKey) {
            startModelEdit(rowKey);
        } else if (action === 'delete' && rowKey) {
            deleteModel(rowKey);
        } else if (action === 'cancel-model') {
            cancelModelEdit();
        } else if (action === 'save-model' && rowKey) {
            saveModelRow(rowKey);
        }
    }

function handleModelInputChange(event) {
    if (!state.modelEdit || !event.target.dataset.field) {
        return;
    }
    const field = event.target.dataset.field;
    if (!state.modelDraft) {
        state.modelDraft = {};
    }
    if (field === 'name') {
        const normalized = event.target.value.trim().toLowerCase();
        state.modelDraft[field] = normalized;
        if (event.target.value !== normalized) {
            event.target.value = normalized;
        }
    } else {
        state.modelDraft[field] = event.target.value;
    }
}

function startModelEdit(modelName) {
    if (state.isSavingModel) return;
    if (state.modelEdit && state.modelEdit.mode === 'new') {
        setStatus(elements.modelFeedback, 'Finish creating the new model before editing another.', 'warning');
        return;
    }

    const model = state.models.find(m => m.name === modelName);
    if (!model || model.user_editable === false) {
        setStatus(elements.modelFeedback, 'This model is read-only.', 'warning');
        return;
    }

    state.modelEdit = { mode: 'existing', key: model.name };
    state.modelDraft = {
        name: model.name,
        provider: model.provider,
        model_string: model.model_string,
        capabilities: Array.isArray(model.capabilities) && model.capabilities.length
            ? model.capabilities.join(', ')
            : 'text'
    };

    renderModels();
    focusModelInput('name');
    setStatus(elements.modelFeedback, `Editing '${model.name}'.`, 'info');
}

function startNewModel() {
    if (state.isSavingModel) return;
    if (state.modelEdit) {
        setStatus(elements.modelFeedback, 'Finish editing the current row before adding a new model.', 'warning');
        return;
    }

    const defaultProvider = state.providers[0]?.name || '';
    state.modelEdit = { mode: 'new', key: '__new' };
    state.modelDraft = {
        name: '',
        provider: defaultProvider,
        model_string: '',
        capabilities: 'text'
    };

    renderModels();
    focusModelInput('name');
    setStatus(elements.modelFeedback, 'Enter details for the new model row and click Save.', 'info');
}

function cancelModelEdit(message = true) {
    state.modelEdit = null;
    state.modelDraft = null;
    renderModels();
    if (message) {
        setStatus(elements.modelFeedback, 'Editing cancelled.', 'info');
    }
}

async function saveModelRow(rowKey) {
    if (state.isSavingModel || !state.modelEdit || !state.modelDraft) return;

    const draft = state.modelDraft;
    let alias = (draft.name || '').trim().toLowerCase();
    const provider = (draft.provider || '').trim();
    const modelString = (draft.model_string || '').trim();
    const capabilitiesInput = (draft.capabilities || '').trim();
    const capabilities = capabilitiesInput
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter((item) => item.length > 0);

    const isNew = state.modelEdit.mode === 'new' || rowKey === '__new';
    const originalName = state.modelEdit.mode === 'existing' ? state.modelEdit.key : null;

    if (!alias) {
        setStatus(elements.modelFeedback, 'Model name is required.', 'error');
        return;
    }

    if (!provider || !modelString) {
        setStatus(elements.modelFeedback, 'Provider and model identifier are required.', 'error');
        return;
    }
    if (!capabilities.length) {
        setStatus(elements.modelFeedback, 'At least one capability is required (e.g. text).', 'error');
        return;
    }

    if ((isNew || alias !== originalName) && state.models.some(m => m.name === alias)) {
        setStatus(elements.modelFeedback, `Model '${alias}' already exists.`, 'error');
        return;
    }

    state.modelDraft.name = alias;
    state.isSavingModel = true;
    setStatus(elements.modelFeedback, 'Saving model…', 'info');

    try {
        const payload = {
            provider: provider,
            model_string: modelString,
            capabilities: capabilities
        };

        const response = await fetch(`api/system/models/${encodeURIComponent(alias)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await safeJson(response);
            throw new Error(errorData?.message || `HTTP ${response.status}`);
        }

        const result = await response.json();
        let restartRequired = Boolean(result && result.restart_required);

        if (originalName && alias !== originalName) {
            const deleteResponse = await fetch(`api/system/models/${encodeURIComponent(originalName)}`, {
                method: 'DELETE'
            });
            if (!deleteResponse.ok) {
                const deleteError = await safeJson(deleteResponse);
                throw new Error(deleteError?.message || `Failed to remove old alias '${originalName}'.`);
            }

            const deleteResult = await safeJson(deleteResponse);
            restartRequired = restartRequired || Boolean(deleteResult && deleteResult.restart_required);
        }

        cancelModelEdit(false);
        await loadModels();
        await notifyConfigChanged();
        const resultMessage = withRestartNotice(`Saved model '${alias}'.`, { restart_required: restartRequired });
        setStatus(elements.modelFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
    } catch (error) {
        setStatus(elements.modelFeedback, `Failed to save model: ${error.message}`, 'error');
    } finally {
        state.isSavingModel = false;
    }
}

    async function deleteModel(modelName) {
        if (!window.confirm(`Delete model '${modelName}'?`)) return;

        try {
            const response = await fetch(`api/system/models/${encodeURIComponent(modelName)}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const apiResult = await response.json();

            if (state.modelEdit && state.modelEdit.key === modelName) {
                cancelModelEdit(false);
            }
            await loadModels();
            await notifyConfigChanged();
            const resultMessage = withRestartNotice(`Removed model '${modelName}'.`, apiResult);
            setStatus(elements.modelFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.modelFeedback, `Failed to delete model: ${error.message}`, 'error');
        }
    }

    async function handleProviderTableClick(event) {
        const actionButton = event.target.closest('[data-action]');
        if (!actionButton) return;

        const providerName = actionButton.getAttribute('data-provider');
        const action = actionButton.dataset.action;

        if (action === 'edit') {
            startProviderEdit(providerName);
        } else if (action === 'delete') {
            await deleteProvider(providerName);
        } else if (action === 'cancel-provider') {
            cancelProviderEdit();
        } else if (action === 'save-provider') {
            await saveProviderRow(actionButton);
        } else if (action === 'openai-oauth-start') {
            await startOpenAiOAuth(actionButton);
        } else if (action === 'openai-oauth-device-start') {
            await startOpenAiOAuthDevice(actionButton);
        } else if (action === 'openai-oauth-device-check') {
            await checkOpenAiOAuthDevice(actionButton);
        } else if (action === 'openai-oauth-complete') {
            await completeOpenAiOAuth(actionButton);
        } else if (action === 'openai-oauth-disconnect') {
            await disconnectOpenAiOAuth(actionButton);
        }
    }

    function handleProviderInputChange(event) {
        const target = event.target;
        if (target instanceof HTMLInputElement && target.matches('[data-openai-oauth-paste]')) {
            state.openAiOauthPaste = target.value;
            const completeButton = elements.providerList?.querySelector('[data-action="openai-oauth-complete"]');
            if (completeButton instanceof HTMLButtonElement) {
                completeButton.disabled = state.isOpenAiOauthBusy || !target.value.trim();
            }
            return;
        }
        if (!state.providerEdit || !target.dataset.providerField) return;
        if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement)) return;

        if (!state.providerDraft) {
            state.providerDraft = {};
        }
        if (target instanceof HTMLInputElement && target.type === 'checkbox') {
            state.providerDraft[target.dataset.providerField] = target.checked;
        } else {
            state.providerDraft[target.dataset.providerField] = target.value;
        }
    }

    function startNewProvider() {
        if (state.providerEdit) {
            setStatus(elements.providerFeedback, 'Finish editing the current provider before adding another.', 'warning');
            return;
        }
        state.providerEdit = { mode: 'new', key: '__new' };
        state.providerDraft = {
            name: '',
            api_key: '',
            base_url: ''
        };
        renderProviders();
        setStatus(elements.providerFeedback, 'Enter details for the new provider and click Save.', 'info');
        focusProviderInput('name');
    }

    function startProviderEdit(providerName) {
        if (state.providerEdit) {
            setStatus(elements.providerFeedback, 'Finish editing the current provider before editing another.', 'warning');
            return;
        }
        const provider = state.providers.find(p => p.name === providerName);
        if (!provider) return;

        if (provider.user_editable === false) {
            setStatus(elements.providerFeedback, 'Built-in providers cannot be edited.', 'warning');
            return;
        }

        state.providerEdit = { mode: 'existing', key: provider.name };
        state.providerDraft = {
            name: provider.name,
            api_key: provider.api_key || '',
            base_url: provider.base_url || '',
            auth_mode: provider.configured_auth_mode || 'api_key',
            oauth_api_key_fallback_enabled: provider.oauth_api_key_fallback_enabled === true
        };
        renderProviders();
        setStatus(elements.providerFeedback, `Editing '${provider.name}'.`, 'info');
        focusProviderInput('api_key');
    }

    function cancelProviderEdit(showStatus = true) {
        state.providerEdit = null;
        state.providerDraft = null;
        renderProviders();
        if (showStatus) {
            setStatus(elements.providerFeedback, 'Editing cancelled.', 'info');
        }
    }

    async function saveProviderRow(button) {
        if (state.isSavingProvider || !state.providerEdit || !state.providerDraft) return;

        const draft = state.providerDraft;
        const name = (draft.name || '').trim();
        const apiKeyInput = (draft.api_key || '').trim();
        const baseUrlInput = (draft.base_url || '').trim();

        if (!name) {
            setStatus(elements.providerFeedback, 'Provider name is required.', 'error');
            return;
        }

        if (baseUrlInput && baseUrlInput.includes('://')) {
            setStatus(elements.providerFeedback, 'Base URL must reference a secret name; store the actual URL via the Secrets form.', 'error');
            return;
        }

        state.isSavingProvider = true;
        if (button) {
            button.disabled = true;
            setIconButtonLabel(button, 'Saving provider...');
        }
        setStatus(elements.providerFeedback, 'Saving provider…', 'info');

        try {
            const payload = {
                api_key: apiKeyInput ? normalizeSecretName(apiKeyInput) : '',
                base_url: baseUrlInput ? normalizeSecretName(baseUrlInput) : ''
            };
            if (name === 'openai') {
                payload.auth_mode = draft.auth_mode === 'oauth' ? 'oauth' : 'api_key';
                payload.oauth_api_key_fallback_enabled = draft.oauth_api_key_fallback_enabled === true;
            }

            const response = await fetch(`api/system/providers/${encodeURIComponent(name)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const providerResult = await response.json();
            cancelProviderEdit(false);
            await loadProviders();
            await loadModels(); // provider availability can update model availability
            await loadSecrets();
            await notifyConfigChanged();
            const resultMessage = withRestartNotice(`Saved provider '${name}'.`, providerResult);
            setStatus(elements.providerFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to save provider: ${error.message}`, 'error');
        } finally {
            if (button) {
                button.disabled = false;
                setIconButtonLabel(button, 'Save provider');
            }
            state.isSavingProvider = false;
        }
    }

    async function deleteProvider(providerName) {
        if (!window.confirm(`Delete provider '${providerName}'? Models referencing it must be removed first.`)) {
            return;
        }

        try {
            const response = await fetch(`api/system/providers/${encodeURIComponent(providerName)}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();

            await loadProviders();
            await loadModels();
            await loadSecrets();
            await notifyConfigChanged();
            if (state.providerEdit?.key === providerName) {
                cancelProviderEdit(false);
            }
            const resultMessage = withRestartNotice(`Removed provider '${providerName}'.`, result);
            setStatus(elements.providerFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to delete provider: ${error.message}`, 'error');
        }
    }

    async function startOpenAiOAuth(button) {
        if (state.isOpenAiOauthBusy) return;

        state.isOpenAiOauthBusy = true;
        setOpenAiOauthButtonBusy(button, 'Starting OAuth...');
        setStatus(elements.providerFeedback, 'Starting OpenAI OAuth…', 'info');

        try {
            const response = await fetch('api/system/providers/openai/oauth/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            const opened = window.open(result.auth_url, '_blank', 'noopener');
            state.openAiOauthPaste = '';
            state.openAiOauthAuthUrl = result.auth_url || '';
            clearOpenAiOauthDeviceDisplay();
            await loadProviders();
            const popupText = opened
                ? 'OpenAI OAuth URL opened. The URL is also shown in the OpenAI provider panel for manual copy/paste.'
                : 'Open the OAuth URL shown in the OpenAI provider panel, then paste the final redirect URL here.';
            setStatus(elements.providerFeedback, popupText, 'info');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to start OpenAI OAuth: ${error.message}`, 'error');
        } finally {
            state.isOpenAiOauthBusy = false;
            renderProviders();
            setOpenAiOauthButtonIdle(button, 'Connect');
        }
    }

    async function startOpenAiOAuthDevice(button) {
        if (state.isOpenAiOauthBusy) return;

        state.isOpenAiOauthBusy = true;
        setOpenAiOauthButtonBusy(button, 'Starting...');
        setStatus(elements.providerFeedback, 'Starting OpenAI OAuth device code…', 'info');

        try {
            const response = await fetch('api/system/providers/openai/oauth/device/start', {
                method: 'POST'
            });
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            state.openAiOauthPaste = '';
            state.openAiOauthAuthUrl = '';
            state.openAiOauthDeviceVerificationUrl = result.verification_url || '';
            state.openAiOauthDeviceUserCode = result.user_code || '';
            state.openAiOauthDeviceExpiresAt = result.expires_at || '';
            state.openAiOauthDevicePollIntervalSeconds = result.poll_interval_seconds || null;
            await loadProviders();
            setStatus(elements.providerFeedback, 'Open the device URL and enter the code, then check status.', 'info');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to start OpenAI OAuth device code: ${error.message}`, 'error');
        } finally {
            state.isOpenAiOauthBusy = false;
            renderProviders();
            setOpenAiOauthButtonIdle(button, 'Device Code');
        }
    }

    async function checkOpenAiOAuthDevice(button) {
        if (state.isOpenAiOauthBusy) return;

        state.isOpenAiOauthBusy = true;
        setOpenAiOauthButtonBusy(button, 'Checking...');
        setStatus(elements.providerFeedback, 'Checking OpenAI OAuth device code…', 'info');

        try {
            const response = await fetch('api/system/providers/openai/oauth/device/check', {
                method: 'POST'
            });
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            if (result.status === 'connected') {
                clearOpenAiOauthDeviceDisplay();
                await loadProviders();
                await loadModels();
                await notifyConfigChanged();
                setStatus(elements.providerFeedback, 'OpenAI OAuth connected.', 'success');
            } else {
                await loadProviders();
                setStatus(elements.providerFeedback, 'OpenAI OAuth device code is still pending.', 'info');
            }
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to check OpenAI OAuth device code: ${error.message}`, 'error');
        } finally {
            state.isOpenAiOauthBusy = false;
            renderProviders();
            setOpenAiOauthButtonIdle(button, 'Check Status');
        }
    }

    async function completeOpenAiOAuth(button) {
        if (state.isOpenAiOauthBusy) return;
        const pasted = (state.openAiOauthPaste || '').trim();
        if (!pasted) {
            setStatus(elements.providerFeedback, 'Paste the final redirect URL or code first.', 'warning');
            return;
        }

        state.isOpenAiOauthBusy = true;
        setOpenAiOauthButtonBusy(button, 'Completing OAuth...');
        setStatus(elements.providerFeedback, 'Completing OpenAI OAuth…', 'info');

        try {
            const payload = pasted.includes('://')
                ? { redirect_url: pasted }
                : { code: pasted };
            const response = await fetch('api/system/providers/openai/oauth/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            await response.json();
            state.openAiOauthPaste = '';
            state.openAiOauthAuthUrl = '';
            clearOpenAiOauthDeviceDisplay();
            await loadProviders();
            await loadModels();
            await notifyConfigChanged();
            setStatus(elements.providerFeedback, 'OpenAI OAuth connected.', 'success');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to complete OpenAI OAuth: ${error.message}`, 'error');
        } finally {
            state.isOpenAiOauthBusy = false;
            renderProviders();
            setOpenAiOauthButtonIdle(button, 'Complete OAuth');
        }
    }

    async function disconnectOpenAiOAuth(button) {
        if (state.isOpenAiOauthBusy) return;
        if (!window.confirm('Disconnect the OpenAI OAuth account?')) return;

        state.isOpenAiOauthBusy = true;
        setOpenAiOauthButtonBusy(button, 'Disconnecting...');
        setStatus(elements.providerFeedback, 'Disconnecting OpenAI OAuth…', 'info');

        try {
            const response = await fetch('api/system/providers/openai/oauth', {
                method: 'DELETE'
            });
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            await response.json();
            state.openAiOauthPaste = '';
            state.openAiOauthAuthUrl = '';
            clearOpenAiOauthDeviceDisplay();
            await loadProviders();
            await loadModels();
            await notifyConfigChanged();
            setStatus(elements.providerFeedback, 'OpenAI OAuth disconnected.', 'success');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to disconnect OpenAI OAuth: ${error.message}`, 'error');
        } finally {
            state.isOpenAiOauthBusy = false;
            renderProviders();
            setOpenAiOauthButtonIdle(button, 'Disconnect');
        }
    }

    function clearOpenAiOauthDeviceDisplay() {
        state.openAiOauthDeviceVerificationUrl = '';
        state.openAiOauthDeviceUserCode = '';
        state.openAiOauthDeviceExpiresAt = '';
        state.openAiOauthDevicePollIntervalSeconds = null;
    }

    function setOpenAiOauthButtonBusy(button, label) {
        if (button instanceof HTMLButtonElement) {
            button.disabled = true;
            button.textContent = label;
        }
    }

    function setOpenAiOauthButtonIdle(button, label) {
        if (button instanceof HTMLButtonElement) {
            button.disabled = false;
            button.textContent = label;
        }
    }

    async function loadSecrets() {
        if (!elements.secretsList || state.isLoadingSecrets) return;

        state.isLoadingSecrets = true;
        try {
            const response = await fetch('api/system/secrets');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            state.secrets = Array.isArray(data) ? data : [];
            if (state.secretEdit && state.secretEdit.mode === 'existing') {
                const stillExists = state.secrets.some(secret => secret.name === state.secretEdit.key);
                if (!stillExists) {
                    state.secretEdit = null;
                    state.secretDraft = null;
                }
            }
            renderSecretsTable();
            updateImportOcrAvailability();
        } catch (error) {
            elements.secretsList.innerHTML = `
                <div class="rounded-lg border state-surface-error px-4 py-3 text-sm text-center shadow-sm">
                    Failed to load secrets: ${escapeHtml(error.message)}
                </div>
            `;
        } finally {
            state.isLoadingSecrets = false;
        }
    }

    function renderSecretsTable() {
        if (!elements.secretsList) return;

        const cards = [];
        const editing = state.secretEdit;
        const draft = state.secretDraft || {};

        if (editing && editing.mode === 'new') {
            cards.push(renderSecretEditCard(draft, { isNew: true }));
        }

        if (!state.secrets.length) {
            cards.push(`
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    No secrets registered yet.
                </div>
            `);
            elements.secretsList.innerHTML = cards.join('');
            focusSecretInput();
            return;
        }

        state.secrets.forEach((entry) => {
            if (editing && editing.mode === 'existing' && editing.key === entry.name) {
                cards.push(renderSecretEditCard(draft, { isNew: false }));
                return;
            }
            const metadata = SECRET_METADATA[entry.name] || null;
            const label = metadata?.label || entry.name;
            const hasValue = Boolean(entry.has_value);
            const stored = Boolean(entry.stored);
            const statusBadge = hasValue
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-success border">Set</span>'
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium pill-error border">Not set</span>';

            const description = metadata?.description
                ? `<div class="text-xs text-txt-secondary mt-1">${escapeHtml(metadata.description)}</div>`
                : '';

            const deleteButton = stored
                ? `<button data-secret-action="delete" ${iconButton('trash', 'Delete secret', 'is-danger')}>${iconSvg('trash')}</button>`
                : '';

            cards.push(`
                <div class="secret-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-secret="${escapeHtml(entry.name)}" style="max-width: 1400px;">
                    <div class="space-y-4">
                        <div class="flex items-start justify-between gap-4">
                            <div class="min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <div class="font-medium text-txt-primary text-sm">${escapeHtml(label)}</div>
                                    <div class="w-fit">${statusBadge}</div>
                                </div>
                                <div class="font-mono text-xs text-txt-secondary mt-0.5 break-all">${escapeHtml(entry.name)}</div>
                                ${description}
                            </div>
                            <div class="flex items-center gap-2 justify-end shrink-0 flex-wrap">
                                <button data-secret-action="set" ${iconButton('edit', 'Update secret', 'is-primary')}>${iconSvg('edit')}</button>
                                <button data-secret-action="clear" ${iconButton('x', 'Clear secret', 'is-danger')}>${iconSvg('x')}</button>
                                ${deleteButton}
                            </div>
                        </div>
                    </div>
                </div>
            `);
        });

        elements.secretsList.innerHTML = cards.join('');
        focusSecretInput();
        updateImportOcrAvailability();
    }

    function renderSecretEditCard(draft, { isNew }) {
        const rowKey = isNew ? '__new' : (state.secretEdit?.key || draft.name || '');
        const nameReadonly = isNew ? '' : 'readonly';
        const nameHelp = isNew
            ? 'Use uppercase letters, numbers, or underscores.'
            : 'Secret names are identities and cannot be renamed here.';
        return `
            <div class="secret-card rounded-lg border border-border-primary bg-app-card editing-highlight px-5 py-4 shadow-sm" data-secret="${escapeHtml(rowKey)}" data-mode="edit" style="max-width: 1400px;">
                <div class="space-y-4">
                    <div class="grid gap-4 md:grid-cols-2">
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Secret Name</label>
                            <input data-secret-field="name" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary font-mono text-sm transition-colors" placeholder="e.g. LOCAL_MODEL_TOKEN" value="${escapeHtml(draft.name || '')}" ${nameReadonly} />
                            <p class="text-xs text-txt-secondary mt-1">${nameHelp}</p>
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-txt-primary mb-1.5">Secret Value</label>
                            <input data-secret-field="value" type="password" class="w-full px-3 py-2 border border-border-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent bg-app-card text-txt-primary text-sm transition-colors" placeholder="Enter the credential" value="${escapeHtml(draft.value || '')}" />
                            <p class="text-xs text-txt-secondary mt-1">Values are stored as plain text inside <code>system/secrets.yaml</code>.</p>
                        </div>
                    </div>
                    <div class="flex justify-end gap-2">
                        <button data-secret-action="cancel-secret" ${iconButton('circleX', 'Cancel secret edit')}>${iconSvg('circleX')}</button>
                        <button data-secret-action="save-secret" ${iconButton('save', 'Save secret', 'is-primary')}>${iconSvg('save')}</button>
                    </div>
                </div>
            </div>
        `;
    }

    function focusSecretInput(field = 'name') {
        if (!state.secretEdit) return;
        requestAnimationFrame(() => {
            const editableName = state.secretEdit?.mode === 'new';
            const targetField = editableName ? field : (field === 'name' ? 'value' : field);
            const el = elements.secretsList?.querySelector(`[data-secret][data-mode="edit"] [data-secret-field="${targetField}"]`);
            if (el instanceof HTMLInputElement) {
                el.focus();
                el.select();
            }
        });
    }

    function updateImportOcrAvailability() {
        if (!elements.importUseOcrCheckbox) return;
        const hasMistral = state.secrets.some(
            (entry) => entry.name === 'MISTRAL_API_KEY' && entry.has_value
        );
        const isPageImagesMode = (elements.importPdfModeSelect?.value || 'markdown') === 'page_images';
        const disableOcrControls = !hasMistral || isPageImagesMode;

        elements.importUseOcrCheckbox.disabled = disableOcrControls;
        if (elements.importCaptureOcrImagesCheckbox) {
            elements.importCaptureOcrImagesCheckbox.disabled = disableOcrControls;
        }
        if (isPageImagesMode) {
            elements.importUseOcrCheckbox.title = 'Disabled for PDF mode: Page Images';
            if (elements.importCaptureOcrImagesCheckbox) {
                elements.importCaptureOcrImagesCheckbox.title = 'Disabled for PDF mode: Page Images';
            }
        } else {
            elements.importUseOcrCheckbox.title = hasMistral
                ? ''
                : 'Requires MISTRAL_API_KEY secret';
            if (elements.importCaptureOcrImagesCheckbox) {
                elements.importCaptureOcrImagesCheckbox.title = hasMistral
                    ? ''
                    : 'Requires MISTRAL_API_KEY secret';
            }
        }
        if (elements.importCaptureOcrImagesCheckbox) {
            // title is set above to keep mode/secret messaging consistent
        }
        if (disableOcrControls) {
            elements.importUseOcrCheckbox.checked = false;
            if (elements.importCaptureOcrImagesCheckbox) {
                elements.importCaptureOcrImagesCheckbox.checked = false;
            }
        }
    }

    async function handleSecretsTableClick(event) {
        const actionBtn = event.target.closest('[data-secret-action]');
        if (!actionBtn) return;

        const row = actionBtn.closest('[data-secret]');
        const name = row?.dataset.secret;
        if (!name) return;

        const action = actionBtn.dataset.secretAction;

        if (action === 'set') {
            startSecretEdit(name);
        } else if (action === 'clear') {
            if (!window.confirm(`Clear the stored value for ${name}?`)) {
                return;
            }
            try {
                const result = await updateSecretValue(name, '');
                const resultMessage = withRestartNotice(`Cleared secret '${name}'.`, result);
                setStatus(elements.secretFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
            } catch (error) {
                setStatus(elements.secretFeedback, `Failed to clear secret: ${error.message}`, 'error');
            }
        } else if (action === 'delete') {
            if (!window.confirm(`Delete secret '${name}' from the system? This cannot be undone.`)) {
                return;
            }
            try {
                const result = await deleteSecret(name);
                const resultMessage = withRestartNotice(`Deleted secret '${name}'.`, result);
                setStatus(elements.secretFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
            } catch (error) {
                setStatus(elements.secretFeedback, `Failed to delete secret: ${error.message}`, 'error');
            }
        } else if (action === 'cancel-secret') {
            cancelSecretEdit();
        } else if (action === 'save-secret') {
            await saveSecretRow(actionBtn);
        }
    }

    function handleSecretInputChange(event) {
        const target = event.target;
        if (!state.secretEdit || !(target instanceof HTMLInputElement) || !target.dataset.secretField) {
            return;
        }
        if (!state.secretDraft) {
            state.secretDraft = {};
        }
        state.secretDraft[target.dataset.secretField] = target.value;
    }

    function startNewSecret() {
        if (state.secretEdit) {
            setStatus(elements.secretFeedback, 'Finish editing the current secret before adding another.', 'warning');
            return;
        }
        state.secretEdit = { mode: 'new', key: '__new' };
        state.secretDraft = {
            name: '',
            value: ''
        };
        renderSecretsTable();
        setStatus(elements.secretFeedback, 'Enter details for the new secret and click Save.', 'info');
        focusSecretInput('name');
    }

    function startSecretEdit(name) {
        if (state.secretEdit) {
            setStatus(elements.secretFeedback, 'Finish editing the current secret before editing another.', 'warning');
            return;
        }
        if (!state.secrets.some(secret => secret.name === name)) return;
        state.secretEdit = { mode: 'existing', key: name };
        state.secretDraft = {
            name,
            value: ''
        };
        renderSecretsTable();
        setStatus(elements.secretFeedback, `Updating '${name}'. Enter a new value and save.`, 'info');
        focusSecretInput('value');
    }

    function cancelSecretEdit(showStatus = true) {
        state.secretEdit = null;
        state.secretDraft = null;
        renderSecretsTable();
        if (showStatus) {
            setStatus(elements.secretFeedback, 'Editing cancelled.', 'info');
        }
    }

    async function saveSecretRow(button) {
        if (state.isSavingSecret || !state.secretEdit || !state.secretDraft) return;

        let name = (state.secretDraft.name || '').trim();
        const value = state.secretDraft.value || '';

        if (!name) {
            setStatus(elements.secretFeedback, 'Secret name is required.', 'error');
            return;
        }
        if (!value) {
            setStatus(elements.secretFeedback, 'Secret value is required.', 'error');
            return;
        }

        const normalized = normalizeSecretName(name);
        if (!normalized) {
            setStatus(elements.secretFeedback, 'Secret name must contain letters, numbers, or underscores.', 'error');
            return;
        }
        name = normalized;
        state.secretDraft.name = normalized;

        state.isSavingSecret = true;
        if (button) {
            button.disabled = true;
            setIconButtonLabel(button, 'Saving secret...');
        }
        setStatus(elements.secretFeedback, `Saving ${name}…`, 'info');

        try {
            const result = await updateSecretValue(name, value);
            cancelSecretEdit(false);
            const resultMessage = withRestartNotice(`Saved secret '${name}'.`, result);
            setStatus(elements.secretFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.secretFeedback, `Failed to save secret: ${error.message}`, 'error');
        } finally {
            if (button) {
                button.disabled = false;
                setIconButtonLabel(button, 'Save secret');
            }
            state.isSavingSecret = false;
        }
    }

    function normalizeSecretName(name) {
        if (!name) return '';
        return name.replace(/\s+/g, '_').toUpperCase();
    }

    async function updateSecretValue(name, value) {
        const response = await fetch('api/system/secrets', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, value })
        });

        if (!response.ok) {
            const errorData = await safeJson(response);
            throw new Error(errorData?.message || `HTTP ${response.status}`);
        }

        const result = await response.json();
        await loadSecrets();
        await loadProviders();
        await notifyConfigChanged();
        return result;
    }

    async function deleteSecret(name) {
        const response = await fetch(`api/system/secrets/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const errorData = await safeJson(response);
            throw new Error(errorData?.message || `HTTP ${response.status}`);
        }

        const result = await response.json();
        await loadSecrets();
        await loadProviders();
        await notifyConfigChanged();
        return result;
    }

    async function loadVaultOptions(select) {
        if (!select) return;

        const cachedVaults = window.App && window.App.metadata && Array.isArray(window.App.metadata.vaults)
            ? window.App.metadata.vaults
            : null;
        const vaults = cachedVaults || await (async () => {
            try {
                const response = await fetch('api/metadata');
                if (!response.ok) return [];
                const data = await response.json();
                window.App = window.App || {};
                window.App.metadata = data;
                return Array.isArray(data?.vaults) ? data.vaults : [];
            } catch { return []; }
        })();

        select.innerHTML = '<option value="">Select vault…</option>';
        vaults.forEach((vault) => {
            const opt = document.createElement('option');
            opt.value = vault;
            opt.textContent = vault;
            select.appendChild(opt);
        });
    }

    async function loadPurgeSessionsVaults() {
        await loadVaultOptions(elements.purgeSessionsVault);
    }

    async function loadCleanupGoalsVaults() {
        await loadVaultOptions(elements.cleanupGoalsVault);
    }

    async function handlePurgeSessions() {
        const btn = elements.purgeSessionsBtn;
        if (!btn || btn.disabled) return;

        const vaultName = elements.purgeSessionsVault?.value;
        if (!vaultName) {
            setStatus(elements.purgeSessionsFeedback, 'Select a vault first.', 'warning');
            return;
        }

        const ageValue = elements.purgeSessionsAge?.value;
        const olderThanDays = ageValue ? parseInt(ageValue, 10) : null;

        const ageLabel = ageValue ? `older than ${ageValue} days` : 'all sessions';
        if (!confirm(`Delete ${ageLabel} in vault "${vaultName}"? This cannot be undone.`)) return;

        btn.disabled = true;
        const originalLabel = btn.dataset.iconLabel || btn.title || 'Purge Sessions';
        setIconButtonLabel(btn, 'Purging sessions...');
        setStatus(elements.purgeSessionsFeedback, 'Purging sessions…', 'info');

        try {
            const response = await fetch('api/chat/sessions/purge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ vault_name: vaultName, older_than_days: olderThanDays }),
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            setStatus(elements.purgeSessionsFeedback, result.message, 'success');
        } catch (error) {
            setStatus(elements.purgeSessionsFeedback, `Failed to purge sessions: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            setIconButtonLabel(btn, originalLabel);
        }
    }

    async function handleCleanupGoals() {
        const btn = elements.cleanupGoalsBtn;
        if (!btn || btn.disabled || state.isCleaningGoals) return;

        const vaultName = elements.cleanupGoalsVault?.value;
        if (!vaultName) {
            setStatus(elements.cleanupGoalsFeedback, 'Select a vault first.', 'warning');
            return;
        }

        const statusValue = elements.cleanupGoalsStatus?.value || 'completed';
        const ageValue = elements.cleanupGoalsAge?.value;
        const olderThanDays = ageValue ? parseInt(ageValue, 10) : null;
        const statusLabel = elements.cleanupGoalsStatus?.selectedOptions?.[0]?.textContent || 'matching goals';
        const ageLabel = ageValue ? `older than ${ageValue} days` : 'of any age';

        if (!confirm(`Delete ${statusLabel.toLowerCase()} ${ageLabel} in vault "${vaultName}"? This cannot be undone.`)) return;

        state.isCleaningGoals = true;
        btn.disabled = true;
        const originalLabel = btn.dataset.iconLabel || btn.title || 'Clean Up Goals';
        setIconButtonLabel(btn, 'Cleaning goals...');
        setStatus(elements.cleanupGoalsFeedback, 'Cleaning up goals…', 'info');

        try {
            const response = await fetch('api/system/goals/cleanup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    vault_name: vaultName,
                    status: statusValue,
                    older_than_days: olderThanDays,
                }),
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            setStatus(elements.cleanupGoalsFeedback, result.message, 'success');
        } catch (error) {
            setStatus(elements.cleanupGoalsFeedback, `Failed to clean up goals: ${error.message}`, 'error');
        } finally {
            state.isCleaningGoals = false;
            btn.disabled = false;
            setIconButtonLabel(btn, originalLabel);
        }
    }

    async function handlePurgeExpiredCache() {
        if (!elements.purgeExpiredCacheBtn || state.isPurgingCache) return;

        state.isPurgingCache = true;
        const button = elements.purgeExpiredCacheBtn;
        const originalLabel = button.dataset.iconLabel || button.title || 'Purge Expired Cache';
        button.disabled = true;
        setIconButtonLabel(button, 'Purging expired cache...');
        setStatus(elements.miscFeedback, 'Purging expired cache artifacts…', 'info');

        try {
            const response = await fetch('api/system/cache/purge-expired', {
                method: 'POST'
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            setStatus(
                elements.miscFeedback,
                result?.message || `Purged ${result?.purged_count ?? 0} expired cache artifact(s).`,
                'success'
            );
        } catch (error) {
            setStatus(elements.miscFeedback, `Failed to purge cache: ${error.message}`, 'error');
        } finally {
            button.disabled = false;
            setIconButtonLabel(button, originalLabel);
            state.isPurgingCache = false;
        }
    }

    async function handleRefreshSystemAuthoring() {
        if (!elements.refreshSystemAuthoringBtn || state.isRefreshingSystemAuthoring) return;

        const confirmed = window.confirm(
            'Refresh system authoring scripts?\n\n'
            + 'This will overwrite scripts in system/Authoring. Use this if you have customized '
            + 'the system scripts and want to return to baseline or update to the latest version '
            + 'of system scripts. Vault scripts in AssistantMD/Authoring are not touched.'
        );
        if (!confirmed) return;

        state.isRefreshingSystemAuthoring = true;
        const button = elements.refreshSystemAuthoringBtn;
        const originalLabel = button.dataset.iconLabel || button.title || 'Refresh System Scripts';
        button.disabled = true;
        setIconButtonLabel(button, 'Refreshing system scripts...');
        setStatus(elements.refreshSystemAuthoringFeedback, 'Refreshing system authoring scripts…', 'info');

        try {
            const response = await fetch('api/system/authoring/seed-refresh', {
                method: 'POST'
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            setStatus(
                elements.refreshSystemAuthoringFeedback,
                result?.message || 'System authoring scripts refreshed.',
                result?.success === false ? 'warning' : 'success'
            );
            await callbacks.refreshStatus?.();
        } catch (error) {
            setStatus(
                elements.refreshSystemAuthoringFeedback,
                `Failed to refresh system authoring scripts: ${error.message}`,
                'error'
            );
        } finally {
            button.disabled = false;
            setIconButtonLabel(button, originalLabel);
            state.isRefreshingSystemAuthoring = false;
        }
    }

    async function handleCleanupVaultState() {
        if (!elements.cleanupVaultStateBtn || state.isCleaningVaultState) return;

        state.isCleaningVaultState = true;
        const button = elements.cleanupVaultStateBtn;
        const originalLabel = button.dataset.iconLabel || button.title || 'Clean Up Vault State';
        button.disabled = true;
        setIconButtonLabel(button, 'Cleaning vault state...');
        setStatus(elements.cleanupVaultStateFeedback, 'Cleaning expired vault-state artifacts…', 'info');

        try {
            const response = await fetch('api/vault-state/cleanup', {
                method: 'POST'
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            const message = result?.message || (
                `Deleted ${result?.expired_mutation_rows_deleted ?? 0} mutation row(s), `
                + `${result?.expired_snapshot_rows_deleted ?? 0} snapshot row(s), `
                + `${result?.snapshot_files_deleted ?? 0} snapshot file(s).`
            );
            setStatus(elements.cleanupVaultStateFeedback, message, 'success');
        } catch (error) {
            setStatus(
                elements.cleanupVaultStateFeedback,
                `Failed to clean vault state: ${error.message}`,
                'error'
            );
        } finally {
            button.disabled = false;
            setIconButtonLabel(button, originalLabel);
            state.isCleaningVaultState = false;
        }
    }

    async function loadSystemJobs() {
        if (!elements.systemJobsList || state.isLoadingSystemJobs) return;

        state.isLoadingSystemJobs = true;
        const button = elements.refreshSystemJobsBtn;
        const originalLabel = button ? (button.dataset.iconLabel || button.title || 'Refresh System Jobs') : '';
        if (button) {
            button.disabled = true;
            setIconButtonLabel(button, 'Refreshing system jobs...');
        }

        try {
            const response = await fetch('api/status');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const payload = await response.json();
            const jobs = payload?.scheduler?.job_details || [];
            state.systemJobs = jobs.filter((job) => job.job_type === 'system');
            renderSystemJobs();
        } catch (error) {
            elements.systemJobsList.innerHTML = `
                <div class="state-error">Failed to load system jobs: ${escapeHtml(error.message)}</div>
            `;
        } finally {
            if (button) {
                button.disabled = false;
                setIconButtonLabel(button, originalLabel);
            }
            state.isLoadingSystemJobs = false;
        }
    }

    function renderSystemJobs() {
        if (!elements.systemJobsList) return;

        if (!state.systemJobs.length) {
            elements.systemJobsList.innerHTML = `
                <div class="text-sm text-txt-secondary">No system scheduler jobs are currently registered.</div>
            `;
            return;
        }

        const rows = state.systemJobs.map((job) => {
            const lastRun = formatDateTime(job.last_run_time);
            const nextRun = formatDateTime(job.next_run_time);
            const status = job.last_status || 'not run';
            const error = job.last_error
                ? `<div class="state-error text-xs mt-1">${escapeHtml(job.last_error)}</div>`
                : '';
            return `
                <tr>
                    <td>
                        <strong>${escapeHtml(job.name || job.id)}</strong>
                        <div class="cell-xs cell-mono subtle">${escapeHtml(job.id)}</div>
                    </td>
                    <td class="cell-xs">${escapeHtml(status)}${error}</td>
                    <td class="cell-xs">${escapeHtml(lastRun)}</td>
                    <td class="cell-xs">${escapeHtml(nextRun)}</td>
                </tr>
            `;
        }).join('');

        elements.systemJobsList.innerHTML = `
            <div class="overflow-x-auto">
                <table class="dashboard-table">
                    <thead>
                        <tr>
                            <th>Job</th>
                            <th>Status</th>
                            <th>Last Run</th>
                            <th>Next Run</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    async function loadSystemMigrations() {
        if (!elements.systemMigrationsStatus || state.isLoadingSystemMigrations) return;

        state.isLoadingSystemMigrations = true;
        const button = elements.refreshSystemMigrationsBtn;
        const originalLabel = button ? (button.dataset.iconLabel || button.title || 'Refresh Database Migrations') : '';
        if (button) {
            button.disabled = true;
            setIconButtonLabel(button, 'Refreshing database migrations...');
        }

        try {
            const response = await fetch('api/system/migrations/status');
            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            state.systemMigrations = await response.json();
            renderSystemMigrations();
            setStatus(elements.systemMigrationsFeedback, state.systemMigrations.message || '', 'info');
        } catch (error) {
            elements.systemMigrationsStatus.innerHTML = `
                <div class="state-error">Failed to load database migrations: ${escapeHtml(error.message)}</div>
            `;
            updateSystemMigrationsButton(null);
        } finally {
            if (button) {
                button.disabled = false;
                setIconButtonLabel(button, originalLabel);
            }
            state.isLoadingSystemMigrations = false;
        }
    }

    async function handleRunSystemMigrations() {
        if (!elements.runSystemMigrationsBtn || state.isRunningSystemMigrations) return;
        const pendingCount = Number(state.systemMigrations?.pending_count ?? 0);
        if (pendingCount <= 0) return;

        state.isRunningSystemMigrations = true;
        const button = elements.runSystemMigrationsBtn;
        button.disabled = true;
        setIconButtonLabel(button, 'Running database migrations...');
        if (elements.refreshSystemMigrationsBtn) {
            elements.refreshSystemMigrationsBtn.disabled = true;
        }
        setStatus(elements.systemMigrationsFeedback, 'Running system database migrations…', 'info');

        try {
            const response = await fetch('api/system/migrations/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ backup: true }),
            });

            if (!response.ok) {
                const errorData = await safeJson(response);
                throw new Error(errorData?.message || `HTTP ${response.status}`);
            }

            const result = await response.json();
            state.systemMigrations = result;
            renderSystemMigrations();
            const backupCount = Array.isArray(result.backups_created) ? result.backups_created.length : 0;
            const backupText = backupCount > 0 ? ` ${backupCount} backup file(s) created.` : '';
            setStatus(elements.systemMigrationsFeedback, `${result.message || 'System database migrations completed.'}${backupText}`, 'success');
            await callbacks.refreshStatus?.();
        } catch (error) {
            setStatus(elements.systemMigrationsFeedback, `Failed to run database migrations: ${error.message}`, 'error');
        } finally {
            updateSystemMigrationsButton(state.systemMigrations);
            if (elements.refreshSystemMigrationsBtn) {
                elements.refreshSystemMigrationsBtn.disabled = false;
            }
            state.isRunningSystemMigrations = false;
        }
    }

    function renderSystemMigrations() {
        if (!elements.systemMigrationsStatus) return;

        const payload = state.systemMigrations;
        const targets = Array.isArray(payload?.targets) ? payload.targets : [];
        if (!targets.length) {
            elements.systemMigrationsStatus.innerHTML = `
                <div class="text-sm text-txt-secondary">No registered system database migrations were found.</div>
            `;
            updateSystemMigrationsButton(payload);
            return;
        }

        const rows = targets.map((target) => {
            const applied = formatVersionList(target.applied_versions);
            const pending = formatVersionList(target.pending_versions);
            const exists = target.exists ? 'yes' : 'no';
            const backup = target.backup_path
                ? `<div class="cell-xs cell-mono subtle mt-1">backup: ${escapeHtml(target.backup_path)}</div>`
                : '';
            return `
                <tr>
                    <td>
                        <strong>${escapeHtml(target.db_name)}</strong>
                        <div class="cell-xs cell-mono subtle">${escapeHtml(target.namespace)}</div>
                        ${backup}
                    </td>
                    <td class="cell-xs">${escapeHtml(exists)}</td>
                    <td class="cell-xs">${escapeHtml(applied)}</td>
                    <td class="cell-xs">${escapeHtml(pending)}</td>
                </tr>
            `;
        }).join('');

        const pendingCount = Number(payload?.pending_count ?? 0);
        const summaryTone = pendingCount > 0 ? 'state-warning' : 'state-success';
        const summary = payload?.message || (
            pendingCount > 0
                ? `${pendingCount} system database migration(s) pending.`
                : 'All registered system database migrations are applied.'
        );

        elements.systemMigrationsStatus.innerHTML = `
            <div class="${summaryTone} mb-2">${escapeHtml(summary)}</div>
            <div class="overflow-x-auto">
                <table class="dashboard-table">
                    <thead>
                        <tr>
                            <th>Database</th>
                            <th>Exists</th>
                            <th>Applied</th>
                            <th>Pending</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
        updateSystemMigrationsButton(payload);
    }

    function formatVersionList(value) {
        if (!Array.isArray(value) || value.length === 0) return 'none';
        return value.map((version) => String(version)).join(', ');
    }

    function updateSystemMigrationsButton(payload) {
        const button = elements.runSystemMigrationsBtn;
        if (!button || state.isRunningSystemMigrations) return;

        const pendingCount = Number(payload?.pending_count ?? 0);
        const hasPending = pendingCount > 0;
        button.disabled = !hasPending;
        setIconButtonLabel(button, hasPending ? `Run ${pendingCount} Migration${pendingCount === 1 ? '' : 's'}` : 'Database migrations up to date');
        button.classList.toggle('is-primary', hasPending);
    }

    function formatDateTime(value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '—';
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    }

    async function notifyConfigChanged() {
        if (typeof callbacks.refreshMetadata === 'function') {
            try {
                await callbacks.refreshMetadata();
            } catch (error) {
                console.error('Failed to refresh metadata:', error);
            }
        }

        if (typeof callbacks.refreshStatus === 'function') {
            try {
                await callbacks.refreshStatus();
            } catch (error) {
                console.error('Failed to refresh system status:', error);
            }
        }
    }

    async function safeJson(response) {
        try {
            return await response.json();
        } catch (_) {
            return null;
        }
    }

    async function refreshAll() {
        await refreshActivityLog();
        await loadProviders();
        await loadGeneralSettings();
        await loadModels();
        await loadSecrets();
        await loadSystemJobs();
        await loadSystemMigrations();
        await loadImportVaults();
        await loadPurgeSessionsVaults();
        await loadCleanupGoalsVaults();
        state.hasLoadedOnce = true;
    }

    function externalSetRestartRequired() {
        // Configuration panel no longer tracks a dedicated restart banner.
    }

    function init(options = {}) {
        if (state.initialized) return;

        callbacks.refreshMetadata = options.refreshMetadata || null;
        callbacks.refreshStatus = options.refreshStatus || null;

        cacheElements();
        bindEvents();

        state.initialized = true;
    }

    function onTabActivated() {
        if (!state.initialized) return;
        refreshAll();
    }

    async function onDashboardActivated() {
        if (!state.initialized) return;
        await loadSecrets();
        await loadImportVaults();
    }

    function renderImportVaults() {
        const select = elements.importVaultSelect;
        if (!select) return;
        select.innerHTML = '<option value="">Select vault…</option>';
        if (!state.importVaults || state.importVaults.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'No vaults detected';
            opt.disabled = true;
            select.appendChild(opt);
            return;
        }
        state.importVaults.forEach((vault) => {
            const opt = document.createElement('option');
            opt.value = vault;
            opt.textContent = vault;
            select.appendChild(opt);
        });
    }

    async function loadImportVaults(force = false) {
        if (state.isLoadingImportVaults) return;
        state.isLoadingImportVaults = true;
        setStatus(elements.importStatus, 'Loading vaults…', 'info');

        // Prefer cached metadata from main app if available
        const cachedVaults = window.App && window.App.metadata && Array.isArray(window.App.metadata.vaults)
            ? window.App.metadata.vaults
            : null;
        if (cachedVaults && !force) {
            state.importVaults = cachedVaults;
            renderImportVaults();
            setStatus(elements.importStatus, '', 'info');
        }

        try {
            // Always refresh from API to stay current
            const response = await fetch('api/metadata');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            state.importVaults = Array.isArray(data?.vaults) ? data.vaults : [];
            renderImportVaults();
            setStatus(elements.importStatus, '', 'info');
            // Keep cache in sync for other modules
            window.App = window.App || {};
            window.App.metadata = data;
        } catch (error) {
            if (!cachedVaults) {
                state.importVaults = [];
                renderImportVaults();
            }
            setStatus(elements.importStatus, `Failed to load vaults: ${error.message}`, 'error');
        } finally {
            state.isLoadingImportVaults = false;
        }
    }

    async function handleImportVaultRescan() {
        if (!elements.importRefreshVaultsBtn || state.isLoadingImportVaults) return;
        const btn = elements.importRefreshVaultsBtn;
        const originalLabel = btn.dataset.iconLabel || btn.title || 'Refresh Vaults';
        btn.disabled = true;
        setIconButtonLabel(btn, 'Rescanning vaults...');
        setStatus(elements.importStatus, 'Rescanning vaults…', 'info');
        try {
            const response = await fetch('api/vaults/rescan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            // Refresh global status/metadata if caller provided callbacks
            if (callbacks.refreshStatus) await callbacks.refreshStatus();
            if (callbacks.refreshMetadata) await callbacks.refreshMetadata();
            // Reload vault list for import select
            await loadImportVaults(true);
            setStatus(elements.importStatus, 'Vaults refreshed.', 'success');
        } catch (error) {
            setStatus(elements.importStatus, `Rescan failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            setIconButtonLabel(btn, originalLabel);
        }
    }

    function normalizeOutputPaths(outputs) {
        if (!Array.isArray(outputs)) return [];
        const seen = new Set();
        const normalized = [];
        outputs.forEach((value) => {
            const path = String(value || '').trim();
            if (!path || seen.has(path)) return;
            seen.add(path);
            normalized.push(path);
        });
        return normalized;
    }

    function summarizeImportOutputs(outputs) {
        const paths = normalizeOutputPaths(outputs);
        if (!paths.length) {
            return {
                destinationLabel: 'No output files',
                filesLabel: '0 files',
            };
        }

        const directorySegments = paths.map((path) => {
            const slashIndex = path.lastIndexOf('/');
            const folder = slashIndex >= 0 ? path.slice(0, slashIndex) : '';
            return folder ? folder.split('/').filter(Boolean) : [];
        });

        let commonDir = directorySegments[0] ? directorySegments[0].slice() : [];
        for (let i = 1; i < directorySegments.length; i += 1) {
            const current = directorySegments[i];
            let prefixLen = 0;
            while (
                prefixLen < commonDir.length &&
                prefixLen < current.length &&
                commonDir[prefixLen] === current[prefixLen]
            ) {
                prefixLen += 1;
            }
            commonDir = commonDir.slice(0, prefixLen);
            if (!commonDir.length) break;
        }

        // Import outputs generally live under Imported/<import-set>/...
        // Prefer showing that root folder instead of deep subfolders like /pages.
        const destinationSegments = (
            commonDir.length >= 2 && commonDir[0] === 'Imported'
                ? commonDir.slice(0, 2)
                : commonDir
        );
        const destinationLabel = destinationSegments.length
            ? destinationSegments.join('/')
            : '(vault root)';

        const extensionCounts = new Map();
        paths.forEach((path) => {
            const slashIndex = path.lastIndexOf('/');
            const filename = slashIndex >= 0 ? path.slice(slashIndex + 1) : path;
            const dotIndex = filename.lastIndexOf('.');
            const extension = dotIndex > 0
                ? filename.slice(dotIndex + 1).toLowerCase()
                : 'no-ext';
            extensionCounts.set(extension, (extensionCounts.get(extension) || 0) + 1);
        });

        const typeParts = Array.from(extensionCounts.entries())
            .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
            .map(([ext, count]) => `${count} ${ext}`);

        const filesLabel = `${paths.length} file${paths.length === 1 ? '' : 's'} (${typeParts.join(', ')})`;

        return { destinationLabel, filesLabel };
    }

    function renderImportResults() {
        if (!elements.importResults) return;
        const results = state.importResults;
        const urlResult = state.importUrlResult;

        let sections = [];

        if (results) {
            const jobs = Array.isArray(results.jobs_created) ? results.jobs_created : [];
            const skipped = Array.isArray(results.skipped) ? results.skipped : [];
            let html = '';
            if (jobs.length > 0) {
                html += `<div class="space-y-2"><div class="font-medium text-txt-primary">File imports (${jobs.length})</div>`;
                html += '<ul class="list-disc list-inside space-y-1">';
                html += jobs
                    .map((job) => {
                        const outputSummary = summarizeImportOutputs(job.outputs);
                        const status = job.status || 'queued';
                        const source = job.source_uri || 'unknown';
                        return `
                            <li>
                                <span class="text-txt-primary font-medium">${escapeHtml(source)}</span>
                                <span class="subtle">(${escapeHtml(status)})</span>
                                <div class="text-xs text-txt-secondary ml-4">
                                    Destination: <span class="text-txt-primary">${escapeHtml(outputSummary.destinationLabel)}</span>
                                </div>
                                <div class="text-xs text-txt-secondary ml-4">
                                    Files: ${escapeHtml(outputSummary.filesLabel)}
                                </div>
                            </li>
                        `;
                    })
                    .join('');
                html += '</ul></div>';
            }
            if (skipped.length > 0) {
                html += `<div class="space-y-2 pt-3 border-t border-border-primary"><div class="font-medium text-txt-primary">Skipped (${skipped.length})</div>`;
                html += '<ul class="list-disc list-inside space-y-1">';
                html += skipped.map((name) => `<li>${escapeHtml(name)}</li>`).join('');
                html += '</ul></div>';
            }
            if (html) sections.push(html);
        }

        if (urlResult) {
            const outputSummary = summarizeImportOutputs(urlResult.outputs);
            const status = urlResult.status || 'unknown';
            const error = urlResult.error;
            const source = urlResult.source_uri || urlResult.url || 'unknown';

            let html = `<div class="space-y-2"><div class="font-medium text-txt-primary">Latest URL import</div>`;
            html += `<div class="text-sm"><span class="text-txt-primary font-medium">${escapeHtml(source)}</span> <span class="subtle">(${escapeHtml(status)})</span></div>`;
            html += `<div class="text-sm text-txt-secondary">Destination: <span class="text-txt-primary">${escapeHtml(outputSummary.destinationLabel)}</span></div>`;
            html += `<div class="text-sm text-txt-secondary">Files: ${escapeHtml(outputSummary.filesLabel)}</div>`;
            if (error) {
                html += `<div class="text-sm state-error">Error: ${escapeHtml(error)}</div>`;
            }
            html += '</div>';
            sections.push(html);
        }

        elements.importResults.innerHTML = sections.join('<div class="pt-3 border-t border-border-primary"></div>') || 'No imports yet.';
    }

    async function handleImportScan() {
        if (!elements.importScanBtn || state.isScanningImport) return;

        const vault = elements.importVaultSelect?.value || '';
        if (!vault) {
            setStatus(elements.importStatus, 'Select a vault before scanning.', 'warning');
            return;
        }

        const queueOnly = Boolean(elements.importQueueCheckbox?.checked);
        const useOcr = Boolean(elements.importUseOcrCheckbox?.checked);
        const captureOcrImages = Boolean(elements.importCaptureOcrImagesCheckbox?.checked);
        const pdfMode = (elements.importPdfModeSelect?.value || 'markdown').trim();

        const payload = { vault, queue_only: queueOnly };
        if (pdfMode === 'page_images') {
            payload.pdf_mode = 'page_images';
        }
        if (useOcr) {
            payload.strategies = ["pdf_ocr", "pdf_text", "image_ocr"];
        }
        if (captureOcrImages) {
            payload.capture_ocr_images = true;
        }

        state.isScanningImport = true;
        // Reset URL status when starting a file import
        state.importUrlResult = null;
        renderImportResults();
        const btn = elements.importScanBtn;
        const originalLabel = btn.dataset.iconLabel || btn.title || 'Import Files';
        btn.disabled = true;
        setIconButtonLabel(btn, queueOnly ? 'Queueing import jobs...' : 'Importing files...');
        setStatus(
            elements.importStatus,
            queueOnly ? 'Queueing import jobs…' : 'Scanning import folder and processing…',
            'info'
        );

        try {
            const response = await fetch('api/import/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            state.importResults = data;
            renderImportResults();
            setStatus(
                elements.importStatus,
                queueOnly ? 'Jobs queued.' : 'Import completed.',
                'success'
            );
            if (callbacks.refreshStatus) callbacks.refreshStatus();
        } catch (error) {
            setStatus(elements.importStatus, `Import failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            setIconButtonLabel(btn, originalLabel);
            state.isScanningImport = false;
        }
    }

    async function handleImportUrl() {
        if (!elements.importUrlSubmit || state.isImportingUrl) return;

        const vault = elements.importVaultSelect?.value || '';
        const url = (elements.importUrlInput?.value || '').trim();
        if (!vault || !url) {
            setStatus(elements.importStatus, 'Select a vault and enter a URL.', 'warning');
            return;
        }

        // Reset file status when starting a URL import
        state.importResults = null;
        renderImportResults();
        state.isImportingUrl = true;
        const btn = elements.importUrlSubmit;
        const originalLabel = btn.dataset.iconLabel || btn.title || 'Import URL';
        btn.disabled = true;
        setIconButtonLabel(btn, 'Ingesting URL...');
        setStatus(elements.importStatus, 'Ingesting URL…', 'info');

        try {
            const response = await fetch('api/import/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ vault, url, clean_html: true })
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            state.importUrlResult = data;
            setStatus(elements.importStatus, 'URL ingested.', data.error ? 'warning' : 'success');
            if (callbacks.refreshStatus) callbacks.refreshStatus();
            renderImportResults();
        } catch (error) {
            setStatus(elements.importStatus, `Import failed: ${error.message}`, 'error');
        } finally {
            btn.disabled = false;
            setIconButtonLabel(btn, originalLabel);
            state.isImportingUrl = false;
        }
    }

    window.ConfigurationPanel = {
        init,
        onTabActivated,
        onDashboardActivated,
        refreshActivityLog,
        setRestartRequired: externalSetRestartRequired
    };
}(window, document));
