from .preProcessorBase import PreProcessorBase


class PreProcessorStandard(PreProcessorBase):

    def __init__(self, *args, **kwargs):
        super(PreProcessorStandard, self).__init__(*args, **kwargs)


    def main(self, file_list):
        for i, f in enumerate(file_list):
            # the symlink files must start at index 0 or ffmpeg will fail
            p_symlink = self.seqfolder.joinpath('{0:05d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            p_symlink.symlink_to(f)

