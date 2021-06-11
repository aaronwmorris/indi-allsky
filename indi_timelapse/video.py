import os
import time
from pathlib import Path
import subprocess

from multiprocessing import Process
#from threading import Thread
import multiprocessing

logger = multiprocessing.get_logger()


class VideoProcessWorker(Process):
    def __init__(self, idx, config, video_q):
        super(VideoProcessWorker, self).__init__()

        #self.threadID = idx
        self.name = 'VideoProcessWorker{0:03d}'.format(idx)

        self.config = config
        self.video_q = video_q


    def run(self):
        while True:
            v_dict = self.video_q.get()

            if v_dict.get('stop'):
                return

            timespec = v_dict['timespec']
            img_folder = v_dict['img_folder']


            if not img_folder.exists():
                logger.error('Image folder does not exist: %s', img_folder)
                return


            video_file = img_folder.joinpath('allsky-{0:s}.mp4'.format(timespec))

            if video_file.exists():
                logger.warning('Video is already generated: %s', video_file)
                return


            seqfolder = img_folder.joinpath('.sequence')

            if not seqfolder.exists():
                logger.info('Creating sequence folder %s', seqfolder)
                seqfolder.mkdir()


            # delete all existing symlinks in seqfolder
            rmlinks = list(filter(lambda p: p.is_symlink(), seqfolder.iterdir()))
            if rmlinks:
                logger.warning('Removing existing symlinks in %s', seqfolder)
                for l_p in rmlinks:
                    l_p.unlink()


            # find all files
            timelapse_files = list()
            self.getFolderImgFiles(img_folder, timelapse_files)


            logger.info('Creating symlinked files for timelapse')
            timelapse_files_sorted = sorted(timelapse_files, key=lambda p: p.stat().st_mtime)
            for i, f in enumerate(timelapse_files_sorted):
                symlink_p = seqfolder.joinpath('{0:04d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
                symlink_p.symlink_to(f)


            start = time.time()

            cmd = 'ffmpeg -y -f image2 -r {0:d} -i {1:s}/%04d.{2:s} -vcodec libx264 -b:v {3:s} -pix_fmt yuv420p -movflags +faststart {4:s}'.format(self.config['FFMPEG_FRAMERATE'], str(seqfolder), self.config['IMAGE_FILE_TYPE'], self.config['FFMPEG_BITRATE'], str(video_file)).split()

            subprocess.run(cmd, preexec_fn=lambda: os.nice(19))

            elapsed_s = time.time() - start
            logger.info('Timelapse generated in %0.4f s', elapsed_s)

            # delete all existing symlinks in seqfolder
            rmlinks = list(filter(lambda p: p.is_symlink(), Path(seqfolder).iterdir()))
            if rmlinks:
                logger.warning('Removing existing symlinks in %s', seqfolder)
                for l_p in rmlinks:
                    l_p.unlink()


            # remove sequence folder
            try:
                seqfolder.rmdir()
            except OSError as e:
                logger.error('Cannote remove sequence folder: %s', str(e))


    def getFolderImgFiles(self, folder, file_list):
        logger.info('Searching for image files in %s', folder)

        # Add all files in current folder
        img_files = filter(lambda p: p.is_file(), Path(folder).glob('*.{0:s}'.format(self.config['IMAGE_FILE_TYPE'])))
        file_list.extend(img_files)

        # Recurse through all sub folders
        folders = filter(lambda p: p.is_dir(), Path(folder).iterdir())
        for f in folders:
            self.getFolderImgFiles(f, file_list)  # recursion


