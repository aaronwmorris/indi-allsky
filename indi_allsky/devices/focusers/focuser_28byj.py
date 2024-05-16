#import digitalio

from focuserBase import FocuserBase

#logger = logging.getLogger('indi_allsky')


class focuser_28byj(FocuserBase):
    def __init__(self, *args, **kwargs):
        super(focuser_28byj, self).__init__(*args, **kwargs)


