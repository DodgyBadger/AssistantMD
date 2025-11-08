"""
Configuration constants for changelog management system.

Centralizes all file paths and settings to eliminate hardcoded values
throughout the changelog scripts.
"""

import os

# Base directory for all changelog files
CHANGELOG_ROOT = "/app"

# Database configuration
DATABASE_PATH = os.path.join(CHANGELOG_ROOT, "changelog.db")

# Markdown file paths
CHANGELOG_MARKDOWN_PATH = os.path.join(CHANGELOG_ROOT, "changelog.md")
ORIGINAL_CHANGELOG_PATH = os.path.join(CHANGELOG_ROOT, "changelog-original.md")
LEGACY_CHANGELOG_PATH = os.path.join(CHANGELOG_ROOT, "docs", "changelog.md")

# Default category mappings for auto-classification
CATEGORY_KEYWORDS = {
    'fix': ['fix', 'bug', 'critical', 'error'],
    'feat': ['implementation', 'system', 'architecture', 'framework'],
    'refactor': ['refactor', 'cleanup', 'rename', 'reorganize'],
    'docs': ['documentation', 'improvements', 'guide']
}

# Default fallback category
DEFAULT_CATEGORY = 'feat'

# Export settings
DEFAULT_EXPORT_PATH = CHANGELOG_MARKDOWN_PATH
DEFAULT_BACKUP_PATH = ORIGINAL_CHANGELOG_PATH