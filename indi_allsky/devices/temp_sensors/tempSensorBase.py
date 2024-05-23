
class TempSensorBase(object):
    def __init__(self, config):
        self.config = config


    def update(self):
        # override in child class
        raise Exception('Not implemented')

