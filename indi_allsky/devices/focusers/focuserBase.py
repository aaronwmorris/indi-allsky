from typing import Callable, Optional


class FocuserBase(object):
    # One step is one driver step as each driver defines it.  Positive steps are outward (cw).
    STEPS_PER_TURN: int        # steps for one turn of the shaft (override in child class)
    STEPS_PER_SECOND: float    # usual speed (override in child class)
    CAN_STOP: bool             # can the move stop part-way (override in child class)


    def __init__(self, *args, **kwargs):
        self.config = args[0]


    def deinit(self):
        pass


    def move(self, *args):
        # override in child class
        raise Exception('Not Implemented')


    def move_steps(self, steps: int, should_stop: Optional[Callable[[], bool]] = None) -> int:
        """Move the lens by a signed number of steps, positive is outward (cw).

        A CAN_STOP driver calls should_stop() once after each completed step and stops
        when it returns True.  A driver that cannot stop never calls it.

        Returns the signed steps actually moved.
        """
        # override in child class
        raise NotImplementedError('Override in subclass')
