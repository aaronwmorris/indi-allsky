
class GenericBase(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]


    def deinit(self):
        pass

