"""FITS metadata shared by every dark-master stacking implementation."""


def set_master_fits_metadata(header, image_type, temperature):
    """Set master identity and keep missing temperatures out of the header."""
    header['IMAGETYP'] = image_type
    if temperature is None:
        if 'CCD-TEMP' in header:
            del header['CCD-TEMP']
        return

    header['CCD-TEMP'] = float(temperature)
