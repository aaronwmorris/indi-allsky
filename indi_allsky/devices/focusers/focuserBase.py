
class FocuserBase(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]


    def deinit(self):
        pass


    def move(self, *args):
        # override in child class
        raise Exception('Not Implemented')

