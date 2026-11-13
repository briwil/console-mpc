"""Drawing on the Move's screen: 128 x 64 pixels, one bit each, sent to the core as "MOVEDISP" + 1024 bytes
(8 strips of 128 bytes, each byte 8 pixels going down, bit 0 at the top).

    f = Frame()
    f.text(1, 1, "HELLO")            # 5x7 letters, 6 pixels apart
    f.small(1, 10, "SMALLER 123")    # 3x5 letters, 4 pixels apart
    f.rect(0, 20, 128, 1)            # filled; f.frame(...) for an outline; colour 0 draws black
    core.display(f.bytes())
"""
import numpy as np

W, H = 128, 64

FONT = {  # 5x7, one byte per column, bit 0 = top row
    "A": (0x7C, 0x12, 0x11, 0x12, 0x7C), "B": (0x7F, 0x49, 0x49, 0x49, 0x36), "C": (0x3E, 0x41, 0x41, 0x41, 0x22),
    "D": (0x7F, 0x41, 0x41, 0x22, 0x1C), "E": (0x7F, 0x49, 0x49, 0x49, 0x41), "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A), "H": (0x7F, 0x08, 0x08, 0x08, 0x7F), "I": (0x00, 0x41, 0x7F, 0x41, 0x00),
    "J": (0x20, 0x40, 0x41, 0x3F, 0x01), "K": (0x7F, 0x08, 0x14, 0x22, 0x41), "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F), "N": (0x7F, 0x04, 0x08, 0x10, 0x7F), "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    "P": (0x7F, 0x09, 0x09, 0x09, 0x06), "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E), "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31), "T": (0x01, 0x01, 0x7F, 0x01, 0x01), "U": (0x3F, 0x40, 0x40, 0x40, 0x3F),
    "V": (0x1F, 0x20, 0x40, 0x20, 0x1F), "W": (0x3F, 0x40, 0x38, 0x40, 0x3F), "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07), "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E), "1": (0x00, 0x42, 0x7F, 0x40, 0x00), "2": (0x42, 0x61, 0x51, 0x49, 0x46),
    "3": (0x21, 0x41, 0x45, 0x4B, 0x31), "4": (0x18, 0x14, 0x12, 0x7F, 0x10), "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30), "7": (0x01, 0x71, 0x09, 0x05, 0x03), "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E), ":": (0x00, 0x36, 0x36, 0x00, 0x00), "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    "+": (0x08, 0x08, 0x3E, 0x08, 0x08), ".": (0x00, 0x60, 0x60, 0x00, 0x00), "/": (0x20, 0x10, 0x08, 0x04, 0x02),
    ">": (0x41, 0x22, 0x14, 0x08, 0x00), "<": (0x00, 0x08, 0x14, 0x22, 0x41), "%": (0x23, 0x13, 0x08, 0x64, 0x62),
    "(": (0x00, 0x1C, 0x22, 0x41, 0x00), ")": (0x00, 0x41, 0x22, 0x1C, 0x00),
    "[": (0x00, 0x7F, 0x41, 0x41, 0x00), "]": (0x00, 0x41, 0x41, 0x7F, 0x00), "'": (0x00, 0x05, 0x03, 0x00, 0x00),
    "!": (0x00, 0x00, 0x5F, 0x00, 0x00), "?": (0x02, 0x01, 0x51, 0x09, 0x06), ",": (0x00, 0x50, 0x30, 0x00, 0x00),
    "=": (0x14, 0x14, 0x14, 0x14, 0x14), "#": (0x14, 0x7F, 0x14, 0x7F, 0x14), "&": (0x36, 0x49, 0x55, 0x22, 0x50),
    "_": (0x40, 0x40, 0x40, 0x40, 0x40), "*": (0x14, 0x08, 0x3E, 0x08, 0x14), " ": (0, 0, 0, 0, 0),
}

# 3x5, rows top to bottom, 3 bits each (left = 4)
_SMALL = {
    "A": "25775", "B": "65656", "C": "34443", "D": "65556", "E": "74747", "F": "74744", "G": "34553", "H": "55755",
    "I": "72227", "J": "11153", "K": "55655", "L": "44447", "M": "57755", "N": "65555", "O": "25552", "P": "65644",
    "Q": "25563", "R": "65655", "S": "34216", "T": "72222", "U": "55557", "V": "55552", "W": "55775", "X": "55255",
    "Y": "55222", "Z": "71247", "0": "75557", "1": "26227", "2": "61247", "3": "61216", "4": "55711", "5": "74616",
    "6": "34757", "7": "71222", "8": "75757", "9": "75711", " ": "00000", ".": "00002", ":": "02020", "-": "00700",
    "+": "02720", "/": "11244", "%": "51245", ">": "42124", "<": "12421", "(": "12221", ")": "42224", "[": "64446", "]": "31113", "'": "22000",
    "!": "22202", "?": "61202", ",": "00024", "=": "07070", "#": "57575", "&": "25257", "_": "00007", "*": "05250",
}
SMALL = {ch: [[(int(r) >> (2 - c)) & 1 for c in range(3)] for r in rows] for ch, rows in _SMALL.items()}


class Frame:
    def __init__(self):
        self.px = np.zeros((H, W), np.uint8)

    def clear(self):
        self.px[:] = 0

    def rect(self, x, y, w, h, c=1):
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = c

    def frame(self, x, y, w, h, c=1):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def dot(self, x, y, c=1):
        if 0 <= x < W and 0 <= y < H:
            self.px[y, x] = c

    def text(self, x, y, s, c=1, limit=None):
        """5x7 letters (uppercase), 6 pixels apart. Returns the width drawn."""
        s = str(s).upper()
        if limit is not None:
            s = s[:max(0, limit // 6)]
        for k, ch in enumerate(s):
            cols = FONT.get(ch, FONT["?"] if ch.strip() else FONT[" "])
            for col, bits in enumerate(cols):
                for row in range(7):
                    if bits >> row & 1:
                        self.dot(x + k * 6 + col, y + row, c)
        return len(s) * 6 - 1

    def big(self, x, y, s, c=1):
        """The 5x7 letters at double size (10 x 14 pixels, 12 apart). Returns the width drawn."""
        s = str(s).upper()
        for k, ch in enumerate(s):
            cols = FONT.get(ch, FONT["?"] if ch.strip() else FONT[" "])
            for col, bits in enumerate(cols):
                for row in range(7):
                    if bits >> row & 1:
                        self.rect(x + k * 12 + col * 2, y + row * 2, 2, 2, c)
        return len(s) * 12 - 2

    def small(self, x, y, s, c=1, limit=None):
        """3x5 letters, 4 pixels apart. Returns the width drawn."""
        s = str(s).upper()
        if limit is not None:
            s = s[:max(0, limit // 4)]
        for k, ch in enumerate(s):
            g = SMALL.get(ch, SMALL["?"] if ch.strip() else SMALL[" "])
            for r in range(5):
                for col in range(3):
                    if g[r][col]:
                        self.dot(x + k * 4 + col, y + r, c)
        return len(s) * 4 - 1

    @staticmethod
    def width(s, small=False):
        return len(str(s)) * (4 if small else 6) - 1

    def right(self, x, y, s, small=False, c=1):
        """Text ending at x."""
        w = self.width(s, small)
        (self.small if small else self.text)(x - w, y, s, c)

    def centre(self, x, y, s, small=False, c=1):
        w = self.width(s, small)
        (self.small if small else self.text)(x - w // 2, y, s, c)

    def bar_lines(self, cx, cy, frac, lines=29, pitch=4, tall=30, short=1, fall=2.2):
        """The drum page's setting picture: thin vertical lines, tallest at the value."""
        peak = max(0.0, min(1.0, frac)) * (lines - 1)
        x0 = cx - ((lines - 1) * pitch) // 2
        for k in range(lines):
            h = max(short, int(round(tall * np.exp(-abs(k - peak) / fall))))
            self.rect(x0 + k * pitch, cy - h // 2, 1, max(1, h))

    def bytes(self):
        """For core.display: "MOVEDISP" + 1024 bytes."""
        strips = self.px.reshape(8, 8, W)                     # strip, row in strip, x
        weights = (1 << np.arange(8)).reshape(1, 8, 1)
        packed = (strips * weights).sum(axis=1).astype(np.uint8)
        return b"MOVEDISP" + packed.tobytes()
