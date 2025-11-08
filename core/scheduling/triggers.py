"""
Dynamic trigger creation for APScheduler based on parsed schedule data.

Converts ParsedSchedule objects into appropriate APScheduler trigger instances
(CronTrigger, DateTrigger) for job scheduling.
"""

from typing import Union
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.base import BaseTrigger

from .parser import ParsedSchedule, ScheduleParsingError
from core.logger import UnifiedLogger

# Create module logger
logger = UnifiedLogger(tag="scheduling-triggers")


def create_schedule_trigger(parsed_schedule: ParsedSchedule) -> BaseTrigger:
    """
    Create APScheduler trigger from parsed schedule data.

    Args:
        parsed_schedule: ParsedSchedule object from parser

    Returns:
        Appropriate APScheduler trigger instance (CronTrigger or DateTrigger)

    Raises:
        ScheduleParsingError: If schedule type is unsupported or trigger creation fails
    """
    try:
        if parsed_schedule.is_cron():
            # CronTrigger already created during parsing
            return parsed_schedule.parameters['trigger']
        elif parsed_schedule.is_date():
            # Create DateTrigger for one-time schedules
            return DateTrigger(**parsed_schedule.parameters)
        else:
            raise ScheduleParsingError(f"Unsupported schedule type: {parsed_schedule.schedule_type}")

    except Exception as e:
        if isinstance(e, ScheduleParsingError):
            raise
        # Convert APScheduler exceptions to our format
        raise ScheduleParsingError(f"Failed to create trigger: {str(e)}") from e


