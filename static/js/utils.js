(function utilsModule(window, document, navigator) {
    function escapeHtml(value) {
        if (!value) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function truncateText(value, maxLength) {
        const text = String(value || '').trim();
        if (!text || text.length <= maxLength) return text;
        return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
    }

    function formatShortDate(value) {
        if (!value) return '—';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return '—';
        return parsed.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
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

    window.AssistantMDUtils = Object.freeze({
        escapeHtml,
        truncateText,
        formatShortDate,
        getCopyableText,
        handleCopy,
        flashCopyFeedback,
    });
})(window, document, navigator);
