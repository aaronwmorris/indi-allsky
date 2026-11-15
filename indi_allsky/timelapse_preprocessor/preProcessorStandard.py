from pathlib import Path
import tempfile
import logging

import cv2
import numpy
from PIL import Image

from ..exceptions import TimelapseException

from .preProcessorBase import PreProcessorBase


logger = logging.getLogger('indi_allsky')


class PreProcessorStandard(PreProcessorBase):

    def __init__(self, *args, **kwargs):
        super(PreProcessorStandard, self).__init__(*args, **kwargs)


        # this needs to be a class variable
        # tmp folder needs to be in /tmp so symlinks are supported (image_dir might be fat32)
        self.temp_seqfolder = tempfile.TemporaryDirectory(suffix='_timelapse')  # context manager automatically deletes files when finished
        self._seqfolder = Path(self.temp_seqfolder.name)


    def main(self, file_list):
        for i, f in enumerate(file_list):
            # the symlink files must start at index 0 or ffmpeg will fail
            p_symlink = self.seqfolder.joinpath('{0:05d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            p_symlink.symlink_to(f)


    def encoded_frames(self, paths, suffix):
        """Stream reprojected frames without creating another copy of the night."""
        for path in paths:
            if path not in self.frame_alignments and path.suffix.lower() == suffix:
                yield path.read_bytes()
                continue
            try:
                with Image.open(path) as frame:
                    image = cv2.cvtColor(numpy.asarray(frame.convert('RGB')), cv2.COLOR_RGB2BGR)
            except (OSError, ValueError, cv2.error) as exc:
                raise TimelapseException('Could not decode timelapse frame: %s' % path) from exc
            try:
                image = self.aligned_image(path, image)
                ok, encoded = cv2.imencode(suffix, image)
            except cv2.error as exc:
                raise TimelapseException('Could not reproject timelapse frame: %s' % path) from exc
            if not ok:
                raise TimelapseException('Could not encode oriented timelapse frame: %s' % path)
            yield memoryview(encoded)
