/* panelsniff.so: a listener for finding out what the stock MPC app says to the pad / button panel at start-up.
   LD_PRELOAD it into the stock app: every read and write on /dev/snd/midiC0D0 goes through, unchanged, and is also logged to
   /tmp/panelsniff.log as   "W|R <ms>: <hex bytes>" (the stock app talks to the panel through ALSA sequencer events: 28 bytes each, sysex data after).  No libc needed except __errno_location (raw system calls, aarch64). */
extern int *__errno_location(void);

static long sc4(long n, long a, long b, long c, long d)
{
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
    return x0;
}

#define SYS_OPENAT 56
#define SYS_CLOSE 57
#define SYS_READ 63
#define SYS_WRITE 64
#define SYS_READLINKAT 78
#define SYS_CLOCK_GETTIME 113
#define EXPORT __attribute__((visibility("default")))

static signed char kind[1024];                       /* per fd: 0 = not looked at yet, 1 = the panel, -1 = something else */
static int logfd = -2;
static unsigned nlog;

static int is_midi(int fd)
{
    if (fd < 0 || fd >= 1024) return 0;
    if (kind[fd] == 0) {
        char p[40] = "/proc/self/fd/";
        int k = 14, m = 0, v = fd;
        char t[8];
        do { t[m++] = (char)('0' + v % 10); v /= 10; } while (v);
        while (m) p[k++] = t[--m];
        p[k] = 0;
        char buf[96];
        long r = sc4(SYS_READLINKAT, -100, (long)p, (long)buf, 95);
        int hit = 0;
        for (long i = 0; r > 7 && i + 8 <= r; i++) {           /* the panel directly (midiC0D0) or through the ALSA sequencer (snd/seq) */
            const char *w = "midiC0D0";
            const char *q = "snd/seq";
            int j = 0, h = 0;
            while (j < 8 && buf[i + j] == w[j]) j++;
            while (h < 7 && buf[i + h] == q[h]) h++;
            if (j == 8 || h == 7) { hit = 1; break; }
        }
        kind[fd] = hit ? 1 : -1;
    }
    return kind[fd] == 1;
}

static void logev(char dir, const unsigned char *b, long n)
{
    if (logfd == -2) logfd = (int)sc4(SYS_OPENAT, -100, (long)"/tmp/panelsniff.log", 1 | 64 | 1024, 0644);
    if (logfd < 0 || nlog > 4000) return;
    nlog++;
    struct { long s, ns; } ts = { 0, 0 };
    sc4(SYS_CLOCK_GETTIME, 1, (long)&ts, 0, 0);
    long ms = ts.s * 1000 + ts.ns / 1000000;
    char line[700];
    int k = 0;
    line[k++] = dir;
    line[k++] = ' ';
    char t[24];
    int m = 0;
    do { t[m++] = (char)('0' + ms % 10); ms /= 10; } while (ms);
    while (m) line[k++] = t[--m];
    line[k++] = ':';
    static const char hx[] = "0123456789abcdef";
    for (long i = 0; i < n && i < 200; i++) {
        line[k++] = ' ';
        line[k++] = hx[b[i] >> 4];
        line[k++] = hx[b[i] & 15];
    }
    line[k++] = '\n';
    sc4(SYS_WRITE, logfd, (long)line, k, 0);
}

EXPORT long write(int fd, const void *b, unsigned long n)
{
    long r = sc4(SYS_WRITE, fd, (long)b, (long)n, 0);
    if (r < 0) { *__errno_location() = (int)-r; return -1; }
    if (is_midi(fd)) logev('W', (const unsigned char *)b, r);
    return r;
}

EXPORT long read(int fd, void *b, unsigned long n)
{
    long r = sc4(SYS_READ, fd, (long)b, (long)n, 0);
    if (r < 0) { *__errno_location() = (int)-r; return -1; }
    if (r > 0 && is_midi(fd)) logev('R', (const unsigned char *)b, r);
    return r;
}

EXPORT int close(int fd)
{
    if (fd >= 0 && fd < 1024) kind[fd] = 0;
    long r = sc4(SYS_CLOSE, fd, 0, 0, 0);
    if (r < 0) { *__errno_location() = (int)-r; return -1; }
    return 0;
}
