#!/usr/bin/env python3
"""
Minimal changelog database interface.

Just basic SQL operations and markdown export - no unnecessary abstractions.
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from .changelog_config import DATABASE_PATH, DEFAULT_EXPORT_PATH
except ImportError:
    # When running as a script, use direct paths
    DATABASE_PATH = "/app/changelog.db"
    DEFAULT_EXPORT_PATH = "/app/changelog.md"


def add_entry(
    title: str,
    content: str,
    category: str = "feat",
    phases: Optional[str] = None,
    status: str = "completed",
    date: Optional[str] = None,
    db_path: str = DATABASE_PATH
) -> int:
    """Add changelog entry. Returns entry ID."""
    init_db(db_path)  # Ensure database exists
    
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO changelog_entries (date, title, category, phases, status, content)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date, title, category, phases, status, content))
        return cursor.lastrowid


def get_entries(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: str = DATABASE_PATH
) -> List[Dict[str, Any]]:
    """Get changelog entries as dictionaries."""
    init_db(db_path)  # Ensure database exists
    
    query = "SELECT * FROM changelog_entries WHERE 1=1"
    params = []
    
    if category:
        query += " AND category = ?"
        params.append(category)
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY date DESC"
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def export_markdown(
    output_path: str = DEFAULT_EXPORT_PATH,
    db_path: str = DATABASE_PATH
) -> str:
    """Export entries to markdown. Returns generated content."""
    init_db(db_path)  # Ensure database exists
    entries = get_entries(db_path=db_path)
    
    lines = ["# Changelog", ""]
    
    for entry in entries:
        # Header
        header = f"## {entry['date']} - {entry['title']}"
        if entry['phases']:
            header += f" ({entry['phases']})"
        lines.append(header)
        lines.append("")
        
        # Content
        lines.append(entry['content'].strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Remove trailing separator
    if lines and lines[-2] == "---":
        lines = lines[:-2]
    
    content = "\n".join(lines)
    
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    return content


def init_db(db_path: str = DATABASE_PATH):
    """Initialize database if it doesn't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS changelog_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                phases TEXT,
                status TEXT DEFAULT 'completed',
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def show_help():
    """Show available commands and usage."""
    print("Minimal Changelog Database CLI")
    print("=" * 30)
    print()
    print("Commands:")
    print("  add 'Title' 'Content' [category] [phases]")
    print("    Add new changelog entry")
    print("    - category: feat (default), fix, refactor, docs")
    print("    - phases: optional phase info (e.g., 'Phase 2')")
    print()
    print("  list [category] [limit]")
    print("    List recent entries")
    print("    - category: filter by category (optional)")
    print("    - limit: max entries to show (default: 10)")
    print()
    print("  export")
    print("    Export database to changelog.md")
    print()
    print("  help")
    print("    Show this help message")
    print()
    print("Examples:")
    print("  uv run scripts/changelog.py add 'Fix Bug' '**Fixed critical issue**' fix")
    print("  uv run scripts/changelog.py list feat 5")
    print("  uv run scripts/changelog.py export")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2 or sys.argv[1] in ['help', '--help', '-h']:
        show_help()
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command in ["addentry", "add"]:
        if len(sys.argv) < 4:
            print("Usage: add 'Title' 'Content' [category] [phases]")
            sys.exit(1)
        
        title = sys.argv[2]
        content = sys.argv[3]
        category = sys.argv[4] if len(sys.argv) > 4 else "feat"
        phases = sys.argv[5] if len(sys.argv) > 5 else None
        
        entry_id = add_entry(title, content, category, phases)
        print(f"✅ Added entry {entry_id}: {title}")
        export_markdown()
        print("📄 Exported to changelog.md")
    
    elif command == "list":
        category = sys.argv[2] if len(sys.argv) > 2 else None
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        
        entries = get_entries(category=category, limit=limit)
        print(f"📋 Latest {len(entries)} entries:")
        for entry in entries:
            phases = f" ({entry['phases']})" if entry['phases'] else ""
            print(f"  {entry['date']} - {entry['title']}{phases}")
    
    elif command == "export":
        export_markdown()
        print("📄 Exported to changelog.md")
    
    else:
        print(f"Unknown command: {command}")
        print("Run 'uv run scripts/changelog.py help' for available commands")
        sys.exit(1)