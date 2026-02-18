"""
Schedule syntax parser for crontab and explicit datetime schedules.

Supports:
- 'cron: <crontab>' - Standard 5-field crontab for recurring schedules
- 'once: <datetime>' - Explicit datetime for one-time schedules

Uses APScheduler's CronTrigger and explicit datetime parsing via python-dateutil.
"""

from datetime import datetime
from typing import Dict, Any
from dataclasses import dataclass
from dateutil import parser as dateutil_parser
from apscheduler.triggers.cron import CronTrigger

from core.logger import UnifiedLogger

# Create module logger
logger = UnifiedLogger(tag="schedule-parser")


#######################################################################
## Exception Classes
#######################################################################

class ScheduleParsingError(Exception):
    """Raised when schedule syntax cannot be parsed."""
    pass


#######################################################################
## Data Classes
#######################################################################

@dataclass
class ParsedSchedule:
    """Result of parsing a schedule string.

    Contains the schedule type and parameters needed for trigger creation.
    """
    schedule_type: str              # 'cron' or 'date'
    parameters: Dict[str, Any]      # Parameters for trigger creation

    def is_cron(self) -> bool:
        """Check if this is a cron-based schedule."""
        return self.schedule_type == 'cron'

    def is_date(self) -> bool:
        """Check if this is a one-time date schedule."""
        return self.schedule_type == 'date'


#######################################################################
## Core Parsing Functions
#######################################################################

def parse_schedule_syntax(schedule_input: str) -> ParsedSchedule:
    """Parse schedule string with explicit type prefixes.

    Supports:
    - 'cron: 0 8 * * *' - Recurring crontab schedules
    - 'once: 2025-12-25 10:00' - One-time explicit schedules

    Args:
        schedule_input: Schedule string to parse

    Returns:
        ParsedSchedule with type and parameters for trigger creation

    Raises:
        ScheduleParsingError: If syntax is invalid or unsupported
    """
    if not schedule_input or not schedule_input.strip():
        raise ScheduleParsingError("Schedule input cannot be empty")

    schedule_text = schedule_input.strip()

    # Check for cron schedule prefix
    if schedule_text.lower().startswith('cron:'):
        cron_expr = schedule_text[5:].strip()
        return parse_cron_schedule(cron_expr)

    # Check for one-time schedule prefix
    elif schedule_text.lower().startswith('once:'):
        datetime_str = schedule_text[5:].strip()
        return parse_once_schedule(datetime_str)

    else:
        raise ScheduleParsingError(
            f"Invalid schedule: '{schedule_input}'\n"
            f"Use 'cron: 0 8 * * *' for recurring schedules\n"
            f"Use 'once: 2025-12-25 10:00' for one-time schedules\n"
            f"See https://crontab.guru for crontab syntax help"
        )


def parse_cron_schedule(cron_expr: str) -> ParsedSchedule:
    """Parse crontab expression into CronTrigger.

    Args:
        cron_expr: Standard 5-field crontab expression (e.g., '0 8 * * *')

    Returns:
        ParsedSchedule with cron type and trigger

    Raises:
        ScheduleParsingError: If crontab expression is invalid
    """
    try:
        # Use APScheduler's built-in crontab parser
        trigger = CronTrigger.from_crontab(cron_expr)

        return ParsedSchedule(
            schedule_type='cron',
            parameters={'trigger': trigger}
        )
    except (ValueError, TypeError) as e:
        raise ScheduleParsingError(
            f"Invalid crontab expression: '{cron_expr}'\n"
            f"Expected format: 'minute hour day month day_of_week'\n"
            f"Example: '0 8 * * *' (daily at 8am)\n"
            f"Error: {str(e)}\n"
            f"See https://crontab.guru for help"
        )


def parse_once_schedule(datetime_str: str) -> ParsedSchedule:
    """Parse explicit datetime for one-time schedule.

    Args:
        datetime_str: Explicit datetime string (no relative terms)

    Returns:
        ParsedSchedule with date type and run_date

    Raises:
        ScheduleParsingError: If datetime is invalid or in the past
    """
    # Check for disallowed relative terms
    if _contains_relative_terms(datetime_str):
        raise ScheduleParsingError(
            f"Relative time terms not allowed in schedule: '{datetime_str}'\n"
            f"Use explicit datetime like 'once: 2025-12-25 10:00' instead"
        )

    # Parse datetime
    run_date = _parse_explicit_datetime(datetime_str)

    # Validate it's in the future
    if run_date <= datetime.now():
        raise ScheduleParsingError(
            f"One-time schedule must be in the future: '{datetime_str}' "
            f"resolves to {run_date.isoformat()}"
        )

    return ParsedSchedule(
        schedule_type='date',
        parameters={'run_date': run_date}
    )


#######################################################################
## Helper Functions
#######################################################################

def _parse_explicit_datetime(datetime_str: str) -> datetime:
    """Parse explicit datetime string using dateutil.

    Supports formats like:
    - 2025-12-25 10:00
    - 2025-12-25T10:00:00
    - December 25, 2025 at 10am
    - 12/25/2025 10:00

    Args:
        datetime_str: Datetime string to parse

    Returns:
        Parsed datetime object

    Raises:
        ScheduleParsingError: If datetime cannot be parsed
    """
    try:
        # Use dateutil's flexible parser
        dt = dateutil_parser.parse(datetime_str, fuzzy=True)

        # If time is midnight and no time indicators in string, default to 9am
        if dt.hour == 0 and dt.minute == 0 and not _contains_time(datetime_str):
            dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)

        return dt

    except (ValueError, TypeError):
        raise ScheduleParsingError(
            f"Could not parse datetime: '{datetime_str}'\n"
            f"Use explicit formats like '2025-12-25 10:00' or 'December 25, 2025 at 10am'"
        )


def _contains_time(s: str) -> bool:
    """Check if string explicitly specifies time.

    Args:
        s: String to check

    Returns:
        True if string contains time indicators
    """
    time_indicators = [':', 'am', 'pm', 'AM', 'PM']
    return any(indicator in s for indicator in time_indicators)


def _contains_relative_terms(s: str) -> bool:
    """Check if string contains relative time terms.

    Args:
        s: String to check

    Returns:
        True if string contains relative terms that make no sense in config files
    """
    relative_terms = [
        'tomorrow', 'today', 'yesterday',
        'next', 'last', 'this',
        'in ', ' ago',
        'now'
    ]
    s_lower = s.lower()
    return any(term in s_lower for term in relative_terms)
