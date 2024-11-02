from pathlib import Path
import tempfile


class PreProcessorBase(object):

    def __init__(self, *args, **kwargs):
        self.config = args[0]


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        # this needs to be a class variable
        self.temp_seqfolder = tempfile.TemporaryDirectory(dir=self.image_dir, suffix='_timelapse')  # context manager automatically deletes files when finished
        self._seqfolder = Path(self.temp_seqfolder.name)


    @property
    def seqfolder(self):
        return self._seqfolder


    def main(self, *args, **kwargs):
        raise Exception()

