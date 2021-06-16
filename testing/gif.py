#!/usr/bin/env python3

import imageio


filenames = (
    '20210613_234008.jpg',
    '20210613_234023.jpg',
    '20210613_234038.jpg',
    '20210613_234053.jpg',
    '20210613_234108.jpg',
    '20210613_234123.jpg',
    '20210613_234138.jpg',
    '20210613_234153.jpg',
)

with imageio.get_writer('movie.gif', mode='I', duration=0.2) as writer:
    for filename in filenames:
        image = imageio.imread(filename)
        writer.append_data(image)

