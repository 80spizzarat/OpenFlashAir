"""Presentation-only date formatting; EXIF clock values stay camera-local."""
from datetime import datetime

DATE_FORMATS = {'MM/DD/YYYY': '%m/%d/%Y', 'DD/MM/YYYY': '%d/%m/%Y', 'YYYY-MM-DD': '%Y-%m-%d'}
TIME_FORMATS = {'12-hour (AM/PM)': '%I:%M:%S %p', '24-hour': '%H:%M:%S'}

def format_timestamp(value, date_format, time_format):
    if not value:
        return 'Unavailable'
    if isinstance(value, str):
        try:
            value = datetime.strptime(value.strip(), '%Y:%m:%d %H:%M:%S')
        except ValueError:
            try: value = datetime.fromisoformat(value.strip())
            except ValueError: return 'Unavailable'
    if not isinstance(value, datetime):
        return 'Unavailable'
    return value.strftime(DATE_FORMATS[date_format] + ' ' + TIME_FORMATS[time_format])
