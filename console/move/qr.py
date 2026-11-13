"""A small QR code maker (byte mode, error correction M, versions 1-5: up to 84 characters), for the big
screen's address on the Move's own screen. matrix(text) -> list of rows of 0/1 (1: a dark module)."""

# version: (data codewords per block, blocks, ec codewords per block), alignment pattern centre
_SPEC = {1: (16, 1, 10, None), 2: (28, 1, 16, 18), 3: (44, 1, 26, 22), 4: (32, 2, 18, 26), 5: (43, 2, 24, 30)}

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _ec(data, n):
    gen = [1]
    for i in range(n):
        gen = [a ^ b for a, b in zip(gen + [0], [0] + [_mul(c, _EXP[i]) for c in gen])]
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(gen)):
                rem[i + j] ^= _mul(gen[j], c)
    return rem[len(data):]


def _codewords(text, version):
    dpb, blocks, ecn, _a = _SPEC[version]
    raw = text.encode("utf-8")
    bits = "0100" + format(len(raw), "08b") + "".join(format(b, "08b") for b in raw)
    cap = dpb * blocks * 8
    bits += "0" * min(4, cap - len(bits))
    bits += "0" * (-len(bits) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    k = 0
    while len(data) < dpb * blocks:
        data.append((0xEC, 0x11)[k % 2])
        k += 1
    bl = [data[i * dpb:(i + 1) * dpb] for i in range(blocks)]
    ecs = [_ec(b, ecn) for b in bl]
    out = [b[i] for i in range(dpb) for b in bl] + [e[i] for i in range(ecn) for e in ecs]
    return out


def _format_bits(mask):
    d = (0b00 << 3) | mask                                  # error correction M: 00
    v = d << 10
    for i in range(14, 9, -1):
        if v & (1 << i):
            v ^= 0b10100110111 << (i - 10)
    return ((d << 10) | v) ^ 0b101010000010010


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _build(version, words, mask):
    n = 17 + 4 * version
    m = [[0] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]

    def put(r, c, v):
        if 0 <= r < n and 0 <= c < n:
            m[r][c], fixed[r][c] = v, True

    for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):       # the three finders, with their white edges
        for r in range(-1, 8):
            for c in range(-1, 8):
                inside = 0 <= r <= 6 and 0 <= c <= 6
                v = inside and (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
                put(r0 + r, c0 + c, 1 if v else 0)
    a = _SPEC[version][3]
    if a:
        for r in range(-2, 3):
            for c in range(-2, 3):
                put(a + r, a + c, 1 if max(abs(r), abs(c)) != 1 else 0)
    for i in range(8, n - 8):                                # timing
        put(6, i, 1 if i % 2 == 0 else 0)
        put(i, 6, 1 if i % 2 == 0 else 0)
    put(n - 8, 8, 1)                                         # the dark module
    fb = _format_bits(mask)
    for i in range(15):
        bit = (fb >> i) & 1
        if i < 6:                                            # around the top-left finder
            put(i, 8, bit)
        elif i == 6:
            put(7, 8, bit)
        elif i == 7:
            put(8, 8, bit)
        elif i == 8:
            put(8, 7, bit)
        else:
            put(8, 14 - i, bit)
        if i < 8:                                            # and the copy beside the other two
            put(8, n - 1 - i, bit)
        else:
            put(n - 15 + i, 8, bit)
    bits = "".join(format(w, "08b") for w in words)
    k = 0
    up = True
    c = n - 1
    while c > 0:
        if c == 6:
            c -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for r in rows:
            for cc in (c, c - 1):
                if not fixed[r][cc]:
                    v = int(bits[k]) if k < len(bits) else 0
                    k += 1
                    if _MASKS[mask](r, cc):
                        v ^= 1
                    m[r][cc] = v
        up = not up
        c -= 2
    return m


def _penalty(m):
    n, p = len(m), 0
    for line in m + [list(col) for col in zip(*m)]:
        run, last = 0, None
        for v in line:
            run = run + 1 if v == last else 1
            last = v
            if run == 5:
                p += 3
            elif run > 5:
                p += 1
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(map(sum, m))
    p += abs(dark * 100 // (n * n) - 50) // 5 * 10
    return p


def matrix(text):
    raw = len(text.encode("utf-8"))
    for v in sorted(_SPEC):
        dpb, blocks, _e, _a = _SPEC[v]
        if raw + 2 <= dpb * blocks:
            words = _codewords(text, v)
            return min((_build(v, words, k) for k in range(8)), key=_penalty)
    raise ValueError("too long for a small QR code")
