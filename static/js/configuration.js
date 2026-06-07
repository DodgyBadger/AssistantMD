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
        editingProviderName: null
    };

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
        settingsList: null,

        modelFeedback: null,
        modelList: null,
        modelAddBtn: null,

        providerFeedback: null,
        providerList: null,
        providerForm: null,
        providerFormStatus: null,
        providerNameInput: null,
        providerApiKeyInput: null,
        providerBaseUrlInput: null,
        providerResetBtn: null,
        providerSubmitBtn: null,

        secretsList: null,
        secretForm: null,
        secretNameInput: null,
        secretValueInput: null,
        secretFormStatus: null,
        secretSubmitBtn: null,
        secretResetBtn: null,

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
        elements.settingsList = document.getElementById('settings-list');

        elements.modelFeedback = document.getElementById('model-feedback');
        elements.modelList = document.getElementById('model-list');
        elements.modelAddBtn = document.getElementById('model-add-row');

        elements.providerFeedback = document.getElementById('provider-feedback');
        elements.providerList = document.getElementById('provider-list');
        elements.providerForm = document.getElementById('provider-form');
        elements.providerFormStatus = document.getElementById('provider-form-status');
        elements.providerNameInput = document.getElementById('provider-name');
        elements.providerApiKeyInput = document.getElementById('provider-api-key');
        elements.providerBaseUrlInput = document.getElementById('provider-base-url');
        elements.providerResetBtn = document.getElementById('provider-reset');
        elements.providerSubmitBtn = document.getElementById('provider-submit');

        elements.secretsList = document.getElementById('secrets-list');
        elements.secretForm = document.getElementById('secret-form');
        elements.secretNameInput = document.getElementById('secret-name');
        elements.secretValueInput = document.getElementById('secret-value');
        elements.secretFormStatus = document.getElementById('secret-form-status');
        elements.secretSubmitBtn = document.getElementById('secret-submit');
        elements.secretResetBtn = document.getElementById('secret-reset');

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

        elements.modelAddBtn?.addEventListener('click', startNewModel);
        elements.modelList?.addEventListener('click', handleModelTableClick);
        elements.modelList?.addEventListener('input', handleModelInputChange);
        elements.modelList?.addEventListener('change', handleModelInputChange);

        elements.providerList?.addEventListener('click', handleProviderTableClick);
        elements.providerForm?.addEventListener('submit', handleProviderSubmit);
        elements.providerResetBtn?.addEventListener('click', resetProviderForm);

        elements.secretsList?.addEventListener('click', handleSecretsTableClick);
        elements.secretForm?.addEventListener('submit', handleSecretFormSubmit);
        elements.secretResetBtn?.addEventListener('click', () => resetSecretForm());
        elements.refreshSystemAuthoringBtn?.addEventListener('click', handleRefreshSystemAuthoring);
        elements.purgeExpiredCacheBtn?.addEventListener('click', handlePurgeExpiredCache);
        elements.cleanupVaultStateBtn?.addEventListener('click', handleCleanupVaultState);
        elements.refreshSystemJobsBtn?.addEventListener('click', loadSystemJobs);
        elements.refreshSystemMigrationsBtn?.addEventListener('click', loadSystemMigrations);
        elements.runSystemMigrationsBtn?.addEventListener('click', handleRunSystemMigrations);
        elements.purgeSessionsBtn?.addEventListener('click', handlePurgeSessions);

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
        const prevLabel = refreshBtn ? refreshBtn.textContent : '';

        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Refreshing…';
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
                refreshBtn.textContent = prevLabel;
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

        if (!state.settings.length) {
            const message = emptyOnError
                ? 'Unable to load settings.'
                : 'No configurable settings found.';
            elements.settingsList.innerHTML = `
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    ${escapeHtml(message)}
                </div>
            `;
            return;
        }

        const sortedSettings = [...state.settings].sort((a, b) =>
            String(a?.key ?? '').localeCompare(String(b?.key ?? ''), undefined, { sensitivity: 'base' })
        );

        const cards = sortedSettings.map((setting) => {
            if (state.settingEditKey === setting.key) {
                return renderSettingEditCard(setting);
            }
            return renderSettingViewCard(setting);
        }).join('');

        elements.settingsList.innerHTML = cards;
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
                        <button data-action="edit-setting" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors shrink-0">
                            Edit
                        </button>
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
                        <button data-action="cancel-setting" class="px-4 py-2 text-sm btn-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Cancel
                        </button>
                        <button data-action="save-setting" class="px-4 py-2 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Save
                        </button>
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

        if (!state.providers.length) {
            const message = emptyOnError
                ? 'Unable to load providers.'
                : 'No custom providers configured.';
            elements.providerList.innerHTML = `
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    ${escapeHtml(message)}
                </div>
            `;
            return;
        }

        const cards = state.providers.map((provider) => {
            const editable = provider.user_editable === true;

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

            const actions = editable
                ? `
                    <button data-action="edit" data-provider="${escapeHtml(provider.name)}" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors">Edit</button>
                    <button data-action="delete" data-provider="${escapeHtml(provider.name)}" class="px-3 py-1.5 text-sm rounded-md border state-surface-error focus:outline-none focus:ring-2 focus:ring-accent transition-colors">Delete</button>
                `
                : '';

            const providerMeta = provider.user_editable === false
                ? '<div class="text-xs text-txt-secondary mt-0.5">Built-in provider</div>'
                : '';

            return `
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
                    </div>
                </div>
            `;
        }).join('');

        elements.providerList.innerHTML = cards;
    }

    function populateProviderOptions() {
        // provider options are built per-row during render; nothing to do here.
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
                        <button data-action="edit" data-model="${escapeHtml(model.name)}" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Edit
                        </button>
                        <button data-action="delete" data-model="${escapeHtml(model.name)}" class="px-3 py-1.5 text-sm rounded-md border state-surface-error focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Delete
                        </button>
                    `
                    : `<span class="inline-block px-2 py-0.5 text-xs text-txt-secondary bg-app-elevated rounded border border-border-primary">Read-only</span>`;

        return `
            <div class="model-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-row="${escapeHtml(model.name)}" data-mode="view" style="max-width: 1400px;">
                <div class="grid gap-4 md:grid-cols-[minmax(180px,1fr)_minmax(400px,2.5fr)_minmax(140px,auto)] md:items-center">
                    <div>
                        <div class="font-semibold text-txt-primary text-sm">${escapeHtml(model.name)}</div>
                        <div class="flex items-center gap-2 mt-1">
                            <div class="w-fit">${availabilityBadge}</div>
                        </div>
                        ${reasonLine}
                    </div>
                    <div class="flex gap-6 items-start">
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
                    <div class="flex gap-2 justify-start md:justify-end shrink-0">
                        ${actions}
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
                        <button data-action="cancel-model" class="px-4 py-2 text-sm btn-secondary rounded-md focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Cancel
                        </button>
                        <button data-action="save-model" class="px-4 py-2 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors">
                            Save
                        </button>
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
        }
    }

    function startProviderEdit(providerName) {
        const provider = state.providers.find(p => p.name === providerName);
        if (!provider) return;

        if (provider.user_editable === false) {
            setStatus(elements.providerFormStatus, 'Built-in providers cannot be edited.', 'warning');
            return;
        }

        elements.providerNameInput.value = provider.name;
        elements.providerApiKeyInput.value = provider.api_key || '';
        elements.providerApiKeyInput.placeholder = 'SECRET_NAME (optional)';
        elements.providerBaseUrlInput.value = provider.base_url || '';
        elements.providerBaseUrlInput.placeholder = 'SECRET_NAME (optional)';
        elements.providerForm.dataset.currentApiKeySecret = provider.api_key || '';
        elements.providerForm.dataset.currentBaseUrl = provider.base_url || '';

        state.editingProviderName = provider.name;
        elements.providerSubmitBtn.textContent = 'Update Provider';
        setStatus(elements.providerFormStatus, `Editing ${provider.name}`, 'info');
    }

    function resetProviderForm() {
        if (elements.providerForm) {
            elements.providerForm.reset();
            delete elements.providerForm.dataset.currentApiKeySecret;
            delete elements.providerForm.dataset.currentBaseUrl;
        }
        if (elements.providerApiKeyInput) {
            elements.providerApiKeyInput.placeholder = 'SECRET_NAME (optional)';
        }
        if (elements.providerBaseUrlInput) {
            elements.providerBaseUrlInput.placeholder = 'SECRET_NAME (optional)';
        }
        state.editingProviderName = null;
        elements.providerSubmitBtn.textContent = 'Save Provider';
        setStatus(elements.providerFormStatus, '', 'info');
    }

    async function handleProviderSubmit(event) {
        event.preventDefault();
        if (state.isSavingProvider || !elements.providerForm) return;

        const name = elements.providerNameInput.value.trim();
        const apiKeyInput = (elements.providerApiKeyInput.value || '').trim();
        const baseUrlInput = (elements.providerBaseUrlInput.value || '').trim();
        const currentApiKeySecret = elements.providerForm?.dataset.currentApiKeySecret ?? '';
        const currentBaseUrl = elements.providerForm?.dataset.currentBaseUrl ?? '';

        if (!name) {
            setStatus(elements.providerFormStatus, 'Provider name is required.', 'error');
            return;
        }

        if (baseUrlInput && baseUrlInput.includes('://')) {
            setStatus(elements.providerFormStatus, 'Base URL must reference a secret name; store the actual URL via the Secrets form.', 'error');
            return;
        }

        state.isSavingProvider = true;
        elements.providerSubmitBtn.disabled = true;
        elements.providerSubmitBtn.textContent = 'Saving…';
        setStatus(elements.providerFormStatus, 'Saving provider…', 'info');

        try {
        const payload = {};
        let hasChanges = false;

        if (apiKeyInput !== currentApiKeySecret) {
            if (apiKeyInput) {
                const normalizedSecret = normalizeSecretName(apiKeyInput);
                payload.api_key = normalizedSecret;
            } else {
                payload.api_key = '';
            }
            hasChanges = true;
        }

        if (baseUrlInput !== currentBaseUrl) {
            if (baseUrlInput) {
                payload.base_url = normalizeSecretName(baseUrlInput);
            } else {
                payload.base_url = '';
            }
            hasChanges = true;
        }

        if (!hasChanges) {
            setStatus(elements.providerFormStatus, 'No provider changes to save.', 'info');
            elements.providerSubmitBtn.disabled = false;
            elements.providerSubmitBtn.textContent = state.editingProviderName ? 'Update Provider' : 'Save Provider';
            state.isSavingProvider = false;
            return;
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
            resetProviderForm();
            await loadProviders();
            await loadModels(); // provider availability can update model availability
            await loadSecrets();
            await notifyConfigChanged();
            const resultMessage = withRestartNotice(`Saved provider '${name}'.`, providerResult);
            setStatus(elements.providerFormStatus, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.providerFormStatus, `Failed to save provider: ${error.message}`, 'error');
        } finally {
            elements.providerSubmitBtn.disabled = false;
            elements.providerSubmitBtn.textContent = state.editingProviderName ? 'Update Provider' : 'Save Provider';
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
            if (state.editingProviderName === providerName) {
                resetProviderForm();
            }
            const resultMessage = withRestartNotice(`Removed provider '${providerName}'.`, result);
            setStatus(elements.providerFeedback, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.providerFeedback, `Failed to delete provider: ${error.message}`, 'error');
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

        if (!state.secrets.length) {
            elements.secretsList.innerHTML = `
                <div class="rounded-lg border border-border-primary bg-app-card px-4 py-3 text-sm text-txt-secondary text-center shadow-sm">
                    No secrets registered yet.
                </div>
            `;
            return;
        }

        const cards = state.secrets
            .map((entry) => {
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
                    ? '<button data-secret-action="delete" class="px-3 py-1.5 text-sm rounded-md border state-surface-error focus:outline-none focus:ring-2 focus:ring-accent transition-colors">Delete</button>'
                    : '';

                return `
                    <div class="secret-card rounded-lg border border-border-primary bg-app-card px-5 py-4 shadow-sm hover:shadow transition-shadow" data-secret="${escapeHtml(entry.name)}" style="max-width: 1400px;">
                        <div class="grid gap-4 md:grid-cols-[minmax(200px,2fr)_minmax(140px,auto)] md:items-center">
                            <div>
                                <div class="flex items-center gap-2">
                                    <div class="font-medium text-txt-primary text-sm">${escapeHtml(label)}</div>
                                    <div class="w-fit">${statusBadge}</div>
                                </div>
                                <div class="font-mono text-xs text-txt-secondary mt-0.5">${escapeHtml(entry.name)}</div>
                                ${description}
                            </div>
                            <div class="flex items-center gap-2 justify-start md:justify-end shrink-0 flex-wrap">
                                <button data-secret-action="set" class="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent transition-colors">Update</button>
                                <button data-secret-action="clear" class="px-3 py-1.5 text-sm rounded-md border state-surface-error focus:outline-none focus:ring-2 focus:ring-accent transition-colors">Clear</button>
                                ${deleteButton}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

        elements.secretsList.innerHTML = cards;
        updateImportOcrAvailability();
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
            beginSecretEdit(name);
        } else if (action === 'clear') {
            if (!window.confirm(`Clear the stored value for ${name}?`)) {
                return;
            }
            try {
                const result = await updateSecretValue(name, '');
                const resultMessage = withRestartNotice(`Cleared secret '${name}'.`, result);
                setStatus(elements.secretFormStatus, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
            } catch (error) {
                setStatus(elements.secretFormStatus, `Failed to clear secret: ${error.message}`, 'error');
            }
        } else if (action === 'delete') {
            if (!window.confirm(`Delete secret '${name}' from the system? This cannot be undone.`)) {
                return;
            }
            try {
                const result = await deleteSecret(name);
                const resultMessage = withRestartNotice(`Deleted secret '${name}'.`, result);
                setStatus(elements.secretFormStatus, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
            } catch (error) {
                setStatus(elements.secretFormStatus, `Failed to delete secret: ${error.message}`, 'error');
            }
        }
    }

    function beginSecretEdit(name) {
        if (!elements.secretNameInput || !elements.secretValueInput) return;
        elements.secretNameInput.value = name;
        elements.secretValueInput.value = '';
        setStatus(elements.secretFormStatus, `Updating ${name}. Enter a new value and save.`, 'info');
        requestAnimationFrame(() => {
            elements.secretValueInput?.focus();
        });
    }

    async function handleSecretFormSubmit(event) {
        event.preventDefault();
        if (state.isSavingSecret || !elements.secretNameInput || !elements.secretValueInput) return;

        let name = (elements.secretNameInput.value || '').trim();
        const value = elements.secretValueInput.value;

        if (!name) {
            setStatus(elements.secretFormStatus, 'Secret name is required.', 'error');
            return;
        }
        if (!value) {
            setStatus(elements.secretFormStatus, 'Secret value is required.', 'error');
            return;
        }

        const normalized = normalizeSecretName(name);
        if (!normalized) {
            setStatus(elements.secretFormStatus, 'Secret name must contain letters, numbers, or underscores.', 'error');
            return;
        }
        elements.secretNameInput.value = normalized;
        name = normalized;

        state.isSavingSecret = true;
        if (elements.secretSubmitBtn) {
            elements.secretSubmitBtn.disabled = true;
            elements.secretSubmitBtn.textContent = 'Saving…';
        }
        setStatus(elements.secretFormStatus, `Saving ${name}…`, 'info');

        try {
            const result = await updateSecretValue(name, value);
            resetSecretForm(false);
            const resultMessage = withRestartNotice(`Saved secret '${name}'.`, result);
            setStatus(elements.secretFormStatus, resultMessage.text, resultMessage.restart ? 'warning' : 'success');
        } catch (error) {
            setStatus(elements.secretFormStatus, `Failed to save secret: ${error.message}`, 'error');
        } finally {
            if (elements.secretSubmitBtn) {
                elements.secretSubmitBtn.disabled = false;
                elements.secretSubmitBtn.textContent = 'Save Secret';
            }
            state.isSavingSecret = false;
        }
    }

    function resetSecretForm(clearStatus = true) {
        if (elements.secretForm) {
            elements.secretForm.reset();
        }
        if (clearStatus) {
            setStatus(elements.secretFormStatus, '', 'info');
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

    async function loadPurgeSessionsVaults() {
        const select = elements.purgeSessionsVault;
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
        const originalLabel = btn.textContent;
        btn.textContent = 'Purging…';
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
            btn.textContent = originalLabel;
        }
    }

    async function handlePurgeExpiredCache() {
        if (!elements.purgeExpiredCacheBtn || state.isPurgingCache) return;

        state.isPurgingCache = true;
        const button = elements.purgeExpiredCacheBtn;
        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = 'Purging…';
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
            button.textContent = originalLabel;
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
        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = 'Refreshing…';
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
            button.textContent = originalLabel;
            state.isRefreshingSystemAuthoring = false;
        }
    }

    async function handleCleanupVaultState() {
        if (!elements.cleanupVaultStateBtn || state.isCleaningVaultState) return;

        state.isCleaningVaultState = true;
        const button = elements.cleanupVaultStateBtn;
        const originalLabel = button.textContent;
        button.disabled = true;
        button.textContent = 'Cleaning…';
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
            button.textContent = originalLabel;
            state.isCleaningVaultState = false;
        }
    }

    async function loadSystemJobs() {
        if (!elements.systemJobsList || state.isLoadingSystemJobs) return;

        state.isLoadingSystemJobs = true;
        const button = elements.refreshSystemJobsBtn;
        const originalLabel = button ? button.textContent : '';
        if (button) {
            button.disabled = true;
            button.textContent = 'Refreshing…';
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
                button.textContent = originalLabel;
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
        const originalLabel = button ? button.textContent : '';
        if (button) {
            button.disabled = true;
            button.textContent = 'Refreshing…';
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
                button.textContent = originalLabel;
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
        button.textContent = 'Running…';
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
        button.textContent = hasPending ? `Run ${pendingCount} Migration${pendingCount === 1 ? '' : 's'}` : 'Up to date';
        button.classList.remove('btn-secondary', 'btn-warning');
        button.classList.add(hasPending ? 'btn-warning' : 'btn-secondary');
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
        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Rescanning…';
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
            btn.textContent = originalLabel;
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
        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = queueOnly ? 'Queueing…' : 'Importing…';
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
            btn.textContent = originalLabel;
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
        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Ingesting…';
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
            btn.textContent = originalLabel;
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
