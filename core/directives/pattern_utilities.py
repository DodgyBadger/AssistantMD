"""
Shared utilities for pattern resolution across directives.

Common date/time logic without directive-specific semantics.
"""

import os
import re
import glob
from typing import List, Optional, Tuple
from datetime import datetime, timedelta


class PatternUtilities:
    """Shared utilities for date/time calculations and file operations."""
    
    @staticmethod
    def parse_pattern_with_count(pattern: str) -> Tuple[str, Optional[int]]:
        """Parse pattern like 'latest:3' into ('latest', 3)."""
        if ':' in pattern:
            parts = pattern.split(':', 1)
            try:
                count = int(parts[1])
                return parts[0], count
            except ValueError:
                return pattern, None
        return pattern, None
    
    @staticmethod
    def resolve_date_pattern(pattern: str, reference_date: datetime, week_start_day: int = 0) -> str:
        """Resolve date patterns to YYYY-MM-DD strings."""
        base_pattern, _ = PatternUtilities.parse_pattern_with_count(pattern)
        
        if base_pattern == 'today':
            return reference_date.strftime('%Y-%m-%d')
        elif base_pattern == 'yesterday':
            return (reference_date - timedelta(days=1)).strftime('%Y-%m-%d')
        elif base_pattern == 'tomorrow':
            return (reference_date + timedelta(days=1)).strftime('%Y-%m-%d')
        elif base_pattern == 'this-week':
            return PatternUtilities._get_week_start_date(reference_date, week_start_day, 0).strftime('%Y-%m-%d')
        elif base_pattern == 'last-week':
            return PatternUtilities._get_week_start_date(reference_date, week_start_day, -1).strftime('%Y-%m-%d')
        elif base_pattern == 'next-week':
            return PatternUtilities._get_week_start_date(reference_date, week_start_day, 1).strftime('%Y-%m-%d')
        elif base_pattern == 'this-month':
            return reference_date.strftime('%Y-%m')
        elif base_pattern == 'last-month':
            last_month = reference_date.replace(day=1) - timedelta(days=1)
            return last_month.strftime('%Y-%m')
        elif base_pattern == 'day-name':
            return reference_date.strftime('%A')  # Full day name (e.g., Monday)
        elif base_pattern == 'month-name':
            return reference_date.strftime('%B')  # Full month name (e.g., January)
        else:
            return pattern
    
    @staticmethod
    def get_directory_files(directory: str, extension: str = '.md') -> List[str]:
        """Get all files of specified type in directory, sorted chronologically (oldest first)."""
        if not os.path.exists(directory):
            return []
        
        all_files = []
        for filename in os.listdir(directory):
            if filename.endswith(extension):
                filepath = os.path.join(directory, filename)
                if os.path.isfile(filepath):
                    all_files.append(filepath)
        
        # Sort by creation time (oldest first)
        all_files.sort(key=lambda x: os.path.getctime(x))
        return all_files
    
    @staticmethod
    def resolve_safe_glob(pattern: str, vault_root: str) -> List[str]:
        """Resolve glob patterns with security restrictions (no recursion)."""
        absolute_pattern = os.path.join(vault_root, pattern)
        matched_files = glob.glob(absolute_pattern)
        
        # Filter to only .md files and sort alphabetically  
        md_files = [f for f in matched_files if f.endswith('.md') and os.path.isfile(f)]
        md_files.sort()
        
        return md_files
    
    @staticmethod
    def extract_date_from_filename(filepath: str) -> Optional[datetime]:
        """Extract date from filename using common patterns."""
        filename = os.path.basename(filepath)
        
        # Common date patterns
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
            r'(\d{4}_\d{2}_\d{2})',  # YYYY_MM_DD
            r'(\d{2}-\d{2}-\d{4})',  # MM-DD-YYYY
            r'(\d{8})',              # YYYYMMDD
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, filename)
            if match:
                date_str = match.group(1)
                try:
                    if len(date_str) == 8:  # YYYYMMDD
                        return datetime.strptime(date_str, '%Y%m%d')
                    elif '-' in date_str and date_str.count('-') == 2:
                        parts = date_str.split('-')
                        if len(parts[0]) == 4:  # YYYY-MM-DD
                            return datetime.strptime(date_str, '%Y-%m-%d')
                        else:  # MM-DD-YYYY
                            return datetime.strptime(date_str, '%m-%d-%Y')
                    elif '_' in date_str:  # YYYY_MM_DD
                        return datetime.strptime(date_str, '%Y_%m_%d')
                except ValueError:
                    continue
        
        return None
    
    @staticmethod
    def get_latest_files(files: List[str], count: int) -> List[str]:
        """Get the N most recent files by date from filename."""
        date_files = []
        for filepath in files:
            file_date = PatternUtilities.extract_date_from_filename(filepath)
            if file_date:
                date_files.append((file_date, filepath))
        
        # Sort by date (most recent first) and take top N
        date_files.sort(key=lambda x: x[0], reverse=True)
        return [filepath for _, filepath in date_files[:count]]
    
    @staticmethod
    def filter_files_by_date_range(files: List[str], start_date: datetime, end_date: datetime) -> List[str]:
        """Filter files by date range based on filename dates."""
        filtered_files = []
        for filepath in files:
            file_date = PatternUtilities.extract_date_from_filename(filepath)
            if file_date and start_date <= file_date <= end_date:
                filtered_files.append(filepath)
        
        return sorted(filtered_files)
    
    @staticmethod
    def _get_week_start_date(reference_date: datetime, week_start_day: int, week_offset: int) -> datetime:
        """Calculate week start date with offset."""
        # Calculate days since the start of the week
        days_since_start = (reference_date.weekday() - week_start_day) % 7
        
        # Calculate the start of the current week
        current_week_start = reference_date - timedelta(days=days_since_start)
        
        # Apply week offset
        target_week_start = current_week_start + timedelta(weeks=week_offset)
        
        return target_week_start