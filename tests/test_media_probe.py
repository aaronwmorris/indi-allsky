from indi_allsky.media_probe import verified_media


def test_repair_cache_rechecks_a_replaced_asset(tmp_path):
    path = tmp_path / 'movie'
    reads = []

    def decode(file):
        reads.append(file.read_bytes())
        return reads[-1] == b'good'

    assert not verified_media(path, decode)
    path.write_bytes(b'good')
    assert verified_media(path, decode)
    assert verified_media(path, decode)
    alternate = tmp_path / 'replacement'
    alternate.write_bytes(b'fail')
    alternate.replace(path)
    assert not verified_media(path, decode)
    assert reads == [b'good', b'fail']
