"""Read-only local image helpers for gallery preview and metadata."""
from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path


def decode_image(data: bytes):
    """Decode image bytes fully before the stream disappears."""
    from PIL import Image
    image=Image.open(io.BytesIO(data)); image.load()
    return image.copy()


def local_capture_time(path: Path) -> str:
    """Read DateTimeOriginal without decoding the full photograph."""
    from PIL import Image, ExifTags
    try:
        with Image.open(path) as image:
            exif=image.getexif()
            try: sub=exif.get_ifd(ExifTags.IFD.Exif)
            except (AttributeError,KeyError,TypeError,ValueError): sub={}
            value=sub.get(36867) or exif.get(36867)
            return str(value).strip() if value else ''
    except (OSError,ValueError,TypeError): return ''


def _number(value):
    """Accept Pillow rationals, `(numerator, denominator)`, and plain numbers safely."""
    try:
        if isinstance(value,(tuple,list)) and len(value) == 2: return float(Fraction(int(value[0]),int(value[1])))
        if hasattr(value,'numerator') and hasattr(value,'denominator'): return float(value.numerator/value.denominator)
        return float(value)
    except (TypeError,ValueError,ZeroDivisionError,OverflowError): return None


def _trim(value, places=1):
    return f'{value:.{places}f}'.rstrip('0').rstrip('.')


def format_exif_fields(exif, fallback=None) -> dict[str,str]:
    """Format only recognized EXIF values; invalid or unknown values are blank."""
    def value(tag):
        try:
            result=exif.get(tag)
            if result is not None: return result
            return fallback.get(tag) if fallback is not None else None
        except (AttributeError,TypeError): return None
    iso=_number(value(34855)); aperture=_number(value(33437)); exposure=_number(value(33434)); focal=_number(value(37386)); compensation=_number(value(37380))
    fields={
        'iso':f'ISO {int(iso)}' if iso is not None and iso > 0 else '',
        'aperture':f'f/{_trim(aperture)}' if aperture is not None and aperture > 0 else '',
        'focal_length':f'{_trim(focal)} mm' if focal is not None and focal > 0 else '',
        'exposure_compensation':f'{compensation:+.1f} EV' if compensation is not None else '',
        'lens_model':str(value(42036)).strip() if value(42036) else '',
    }
    if exposure is not None and exposure > 0:
        fields['shutter_speed']=f'1/{round(1/exposure)} sec' if exposure < 1 else f'{_trim(exposure,2)} sec'
    else: fields['shutter_speed']=''
    # Some cameras use ExposureMode (41986), others only ExposureProgram (34850).
    mode=value(41986)
    if mode is None: mode=value(34850)
    fields['exposure_mode']={0:'Auto exposure',1:'Manual exposure',2:'Auto bracket'}.get(mode,'')
    flash=value(37385)
    try: fields['flash_status']='Flash fired' if int(flash) & 1 else 'Flash did not fire'
    except (TypeError,ValueError): fields['flash_status']=''
    return fields


def local_image_metadata(path: Path) -> dict[str,str]:
    """Return only values actually present in a local image; callers label omissions."""
    from PIL import Image, ExifTags
    image=Image.open(path)
    try:
        image.load()
        exif=image.getexif()
        names={value:key for key,value in ExifTags.TAGS.items()}
        capture=exif.get(names.get('DateTimeOriginal')) or exif.get(names.get('DateTime'))
        model=exif.get(names.get('Model'))
        try: sub_ifd=exif.get_ifd(ExifTags.IFD.Exif)
        except (AttributeError,KeyError,TypeError,ValueError): sub_ifd={}
        return {
            'dimensions':f'{image.width} × {image.height}',
            'capture_time':str(capture) if capture else '',
            'camera_model':str(model) if model else '',
            **format_exif_fields(sub_ifd,exif),
        }
    finally:
        image.close()
