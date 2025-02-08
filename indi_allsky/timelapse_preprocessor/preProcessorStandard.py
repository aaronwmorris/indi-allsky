from pathlib import Path
import tempfile
import logging

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

