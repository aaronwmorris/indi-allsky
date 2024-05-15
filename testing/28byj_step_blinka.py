#!/usr/bin/env python3

import curses
import time
import board
import digitalio
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class Stepper(object):
    SEQ = [
        [1, 0, 0, 1],
        [1, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 1],
        [0, 0, 0, 1]
    ]


    def __init__(self):
        self.IN1 = digitalio.DigitalInOut(board.D17)
        self.IN2 = digitalio.DigitalInOut(board.D18)
        self.IN3 = digitalio.DigitalInOut(board.D27)
        self.IN4 = digitalio.DigitalInOut(board.D22)

        self.IN1.direction = digitalio.Direction.OUTPUT
        self.IN2.direction = digitalio.Direction.OUTPUT
        self.IN3.direction = digitalio.Direction.OUTPUT
        self.IN4.direction = digitalio.Direction.OUTPUT


    def set_step(self, w1, w2, w3, w4):
        self.IN1.value = w1
        self.IN2.value = w2
        self.IN3.value = w3
        self.IN4.value = w4


    def step(self, steps, direction):
        if direction == 'cw':
            seq = self.SEQ
        elif direction == 'ccw':
            seq = self.SEQ[::-1]

        for i in range(steps):
            for j in range(8):
                self.set_step(*seq[j])
                time.sleep(0.005)


    def control_motor(self, stdscr):
        stdscr.clear()
        stdscr.addstr("Use up and down arrow keys")
        stdscr.refresh()

        while True:
            key = stdscr.getch()
            if key == curses.KEY_UP:
                self.step(10, 'cw')
            elif key == curses.KEY_DOWN:
                self.step(10, 'ccw')
            elif key == ord('q'):
                break



if __name__ == "__main__":
    s = Stepper()
    curses.wrapper(s.control_motor)
