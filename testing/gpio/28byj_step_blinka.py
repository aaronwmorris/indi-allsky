#!/usr/bin/env python3

import curses
import time
import board
import digitalio
import logging


IN1 = board.D17
IN2 = board.D18
IN3 = board.D27
IN4 = board.D22


logging.basicConfig(level=logging.INFO)
logger = logging


class Stepper(object):
    SEQ = [
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1],
        [1, 0, 0, 1],
    ]


    def __init__(self):
        self.pins = [
            digitalio.DigitalInOut(IN1),
            digitalio.DigitalInOut(IN2),
            digitalio.DigitalInOut(IN3),
            digitalio.DigitalInOut(IN4),
        ]

        for pin in self.pins:
            # set all pins to output
            pin.direction = digitalio.Direction.OUTPUT


    def set_step(self, w1, w2, w3, w4):
        self.pins[0].value = w1
        self.pins[1].value = w2
        self.pins[2].value = w3
        self.pins[3].value = w4


    def step(self, direction, steps):
        if direction == 'cw':
            seq = self.SEQ[::-1]
        elif direction == 'ccw':
            seq = self.SEQ

        for i in range(steps):
            for j in seq:
                self.set_step(*j)
                time.sleep(0.005)


    def control_motor(self, stdscr):
        self.set_step(0, 0, 0, 0)  # reset

        stdscr.clear()
        stdscr.addstr("Use up and down arrow keys")
        stdscr.refresh()

        while True:
            key = stdscr.getch()
            if key == curses.KEY_UP:
                self.step('cw', 10)
            elif key == curses.KEY_DOWN:
                self.step('ccw', 10)
            elif key == ord('q'):
                break

            time.sleep(0.005)

        self.set_step(0, 0, 0, 0)  # reset


if __name__ == "__main__":
    s = Stepper()
    curses.wrapper(s.control_motor)
