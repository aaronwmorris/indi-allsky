from indi_allsky.dark_fits import set_master_fits_metadata


def test_bad_pixel_map_metadata_overrides_source_dark_header():
    header = {'IMAGETYP': 'Dark Frame', 'CCD-TEMP': 14.7}

    set_master_fits_metadata(header, 'Bad Pixel Map', 12.3)

    assert header['IMAGETYP'] == 'Bad Pixel Map'
    assert header['CCD-TEMP'] == 12.3


def test_master_metadata_removes_stale_temperature_without_a_reading():
    header = {'IMAGETYP': 'Dark Frame', 'CCD-TEMP': 14.7}

    set_master_fits_metadata(header, 'Dark Frame', None)

    assert header['IMAGETYP'] == 'Dark Frame'
    assert 'CCD-TEMP' not in header
