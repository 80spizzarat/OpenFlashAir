"""Destination-only filename templates for downloaded FlashAir files."""
from __future__ import annotations

import re
from pathlib import Path

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
FIELDS = {'prefix','date','time','original','sequence'}


class FilenameTemplateError(ValueError): pass


class FilenamePolicy:
    """Renders a safe destination basename; it never changes the remote path."""
    def __init__(self, template: str = '{original}', prefix: str = ''):
        self.template, self.prefix = template.strip() or '{original}', prefix.strip()
        self._validate_template()

    def _validate_template(self):
        try:
            fields={field_name for _,field_name,_,_ in __import__('string').Formatter().parse(self.template) if field_name}
        except ValueError as exc: raise FilenameTemplateError(f'Invalid template: {exc}') from exc
        unknown=fields-FIELDS
        if unknown: raise FilenameTemplateError(f'Unknown field: {sorted(unknown)[0]}')
        self._validate_component(self.prefix, 'Prefix')
        # Literals are checked after expansion too; this catches immediately dangerous input.
        self._validate_component(re.sub(r'\{[^}]+\}', '', self.template), 'Template')

    @staticmethod
    def _validate_component(value: str, label: str):
        if INVALID.search(value) or value.endswith((' ','.')):
            raise FilenameTemplateError(f'{label} contains an invalid Windows filename character')

    def render(self, remote, sequence: int = 1) -> str:
        source=Path(remote.path)
        stamp=remote.modified_utc
        values={
            'prefix': self.prefix,
            'date': stamp.strftime('%Y-%m-%d') if stamp else 'unknown-date',
            'time': stamp.strftime('%H-%M-%S') if stamp else 'unknown-time',
            'original': source.stem,
            'sequence': f'{sequence:03d}',
        }
        try: stem=self.template.format_map(values)
        except (KeyError,ValueError) as exc: raise FilenameTemplateError(f'Invalid template: {exc}') from exc
        if self.prefix and '{prefix}' not in self.template: stem=f'{self.prefix}_{stem}'
        stem=stem.strip()
        self._validate_component(stem, 'Rendered filename')
        if not stem: raise FilenameTemplateError('Rendered filename is empty')
        if stem.upper() in RESERVED: raise FilenameTemplateError('Rendered filename is a reserved Windows name')
        suffix=source.suffix
        if not suffix: raise FilenameTemplateError('Source file has no extension')
        return stem+suffix
