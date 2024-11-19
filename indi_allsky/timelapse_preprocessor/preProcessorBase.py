from pathlib import Path
import logging

logger = logging.getLogger('indi_allsky')


class PreProcessorBase(object):

    def __init__(self, *args, **kwargs):
        self.config = args[0]


        self._seqfolder = None
        self._keogram = None
        self._pre_scale = 100


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    @property
    def seqfolder(self):
        return self._seqfolder


    @property
    def keogram(self):
        return self._keogram

    @keogram.setter
    def keogram(self, new_keogram):
        if isinstance(new_keogram, type(None)):
            self._keogram = None
            return

        self._keogram = Path(str(new_keogram)).absolute()


    @property
    def pre_scale(self):
        return self._pre_scale

    @pre_scale.setter
    def pre_scale(self, new_pre_scale):
        self._pre_scale = int(new_pre_scale)
        #logger.info('Setting timelapse image pre-scaler to %d%%', self._pre_scale)


    def main(self, *args, **kwargs):
        raise Exception()

