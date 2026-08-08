/**
 * Failure-safe browser storage with an in-memory fallback.
 *
 * Accessing localStorage can itself throw SecurityError for opaque origins,
 * including sandboxed iframes. Callers should use this boundary exclusively.
 */
(function browserStorageModule(window) {
    const memory = new Map();
    let persistentStorageUsable = true;

    function getItem(key) {
        const normalizedKey = String(key);
        if (persistentStorageUsable) {
            try {
                const value = window.localStorage.getItem(normalizedKey);
                if (value === null) {
                    memory.delete(normalizedKey);
                } else {
                    memory.set(normalizedKey, value);
                }
                return value;
            } catch (_) {
                persistentStorageUsable = false;
            }
        }
        return memory.get(normalizedKey) ?? null;
    }

    function setItem(key, value) {
        const normalizedKey = String(key);
        const normalizedValue = String(value);
        memory.set(normalizedKey, normalizedValue);
        if (persistentStorageUsable) {
            try {
                window.localStorage.setItem(normalizedKey, normalizedValue);
            } catch (_) {
                persistentStorageUsable = false;
            }
        }
    }

    function removeItem(key) {
        const normalizedKey = String(key);
        memory.delete(normalizedKey);
        if (persistentStorageUsable) {
            try {
                window.localStorage.removeItem(normalizedKey);
            } catch (_) {
                persistentStorageUsable = false;
            }
        }
    }

    window.AssistantMDBrowserStorage = Object.freeze({
        getItem,
        setItem,
        removeItem,
    });
}(window));
