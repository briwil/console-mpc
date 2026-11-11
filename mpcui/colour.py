"""The colour blocks look: a palette of block colours, each with its own darker label band and lighter 'filled' part, and a
stable (not changing from frame to frame) random placement of the colours."""
import random
import zlib

# block colours (the body): blue, sky, sage, orange, yellow, brown, periwinkle
BODIES = [(70, 95, 175), (135, 206, 235), (150, 205, 170), (213, 130, 60), (232, 193, 80), (110, 72, 40), (138, 143, 200)]


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def light(c):
    return mix(c, (255, 255, 255), 0.45)       # the filled part (the value)


def band(c):
    return mix(c, (60, 60, 72), 0.5)           # the label band: the colour, greyed and darker


def ink(c):
    """Text on that colour: white on dark colours, near-black on pale ones."""
    lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    return (255, 255, 255) if lum < 150 else (24, 26, 34)


def pick(key, n):
    """n colours (a list of BODIES) placed 'randomly' but the same every time for the same key (a drum, a page...)."""
    rnd = random.Random(zlib.crc32(str(key).encode()))
    order = list(range(len(BODIES)))
    rnd.shuffle(order)
    return [BODIES[order[i % len(order)]] for i in range(n)]
