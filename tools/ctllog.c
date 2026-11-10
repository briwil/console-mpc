/*
 * ctllog.c - passive logger for the MPC Sample control-surface MIDI port.
 *
 * Loaded into the stock app with LD_PRELOAD. It watches open/read/write on
 * any file whose path ends in "midiC0D0" and appends what it sees to
 * /tmp/ctl.log (RAM only). It never changes the data: every call is passed
 * straight through to the real function.
 *
 * Log lines:   <ms> O <path> flags=<n> fd=<n>      (port opened)
 *              <ms> R <n>: aa bb cc ...           (bytes the app READ)
 *              <ms> W <n>: aa bb cc ...           (bytes the app WROTE)
 * Only the first 512 bytes of a big transfer are printed (n is the full size).
 * Logging stops by itself after 8 MB so RAM cannot fill up.
 *
 * Freestanding on purpose (no headers, only dlsym), so it builds with a plain
 * cross-compiler and needs no target sysroot.
 */

typedef unsigned long size_t;
typedef long ssize_t;

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)

#define MAXFD 1024
#define LOG_LIMIT (8UL << 20)
#define MAX_DUMP 512

/* x86_64 and aarch64 Linux agree on these */
#define O_WRONLY_ 01
#define O_CREAT_ 0100
#define O_APPEND_ 02000
#define O_CLOEXEC_ 02000000

struct ts { long sec; long nsec; };

static unsigned char tracked[MAXFD];
static volatile int state;      /* 0 = not started, 1 = starting, 2 = ready, 3 = failed */
static int logfd = -1;
static volatile unsigned long logged;

static int (*real_open)(const char *, int, unsigned);
static int (*real_open64)(const char *, int, unsigned);
static int (*real_openat)(int, const char *, int, unsigned);
static int (*real_openat64)(int, const char *, int, unsigned);
static int (*real_close)(int);
static ssize_t (*real_read)(int, void *, size_t);
static ssize_t (*real_write)(int, const void *, size_t);
static int (*real_clock_gettime)(int, struct ts *);

#define RESOLVE(var, name) do { if (!(var)) *(void **)&(var) = dlsym(RTLD_NEXT, name); } while (0)

static long start_ms = -1;

static long now_ms(void)
{
    struct ts t;
    RESOLVE(real_clock_gettime, "clock_gettime");
    if (!real_clock_gettime || real_clock_gettime(1, &t) != 0)
        return 0;
    long ms = t.sec * 1000L + t.nsec / 1000000L;
    if (start_ms < 0)
        start_ms = ms;
    return ms - start_ms;
}

static char *put_str(char *p, const char *s)
{
    while (*s)
        *p++ = *s++;
    return p;
}

static char *put_u(char *p, unsigned long v)
{
    char tmp[24];
    int n = 0;
    if (v == 0)
        tmp[n++] = '0';
    while (v) {
        tmp[n++] = (char)('0' + v % 10);
        v /= 10;
    }
    while (n)
        *p++ = tmp[--n];
    return p;
}

static void log_ready(void)
{
    if (state == 2 || state == 3)
        return;
    if (__sync_bool_compare_and_swap(&state, 0, 1)) {
        RESOLVE(real_open, "open");
        RESOLVE(real_write, "write");
        if (real_open && real_write) {
            logfd = real_open("/tmp/ctl.log",
                              O_WRONLY_ | O_CREAT_ | O_APPEND_ | O_CLOEXEC_, 0644);
        }
        state = (logfd >= 0) ? 2 : 3;
    }
}

static void emit(const char *buf, size_t n)
{
    log_ready();
    if (state != 2 || logged > LOG_LIMIT)
        return;
    logged += n;
    real_write(logfd, buf, n);   /* one write on an O_APPEND fd: lines stay whole */
}

static void log_open(const char *path, int flags, int fd)
{
    char line[512];
    char *p = line;
    p = put_u(p, (unsigned long)now_ms());
    p = put_str(p, " O ");
    int i = 0;
    while (path[i] && i < 200)
        *p++ = path[i++];
    p = put_str(p, " flags=");
    p = put_u(p, (unsigned long)flags);
    p = put_str(p, " fd=");
    p = put_u(p, (unsigned long)fd);
    *p++ = '\n';
    emit(line, (size_t)(p - line));
}

static void log_bytes(char dir, const unsigned char *d, ssize_t n)
{
    char line[64 + MAX_DUMP * 3];
    static const char hex[] = "0123456789abcdef";
    char *p = line;
    p = put_u(p, (unsigned long)now_ms());
    *p++ = ' ';
    *p++ = dir;
    *p++ = ' ';
    p = put_u(p, (unsigned long)n);
    *p++ = ':';
    ssize_t m = n > MAX_DUMP ? MAX_DUMP : n;
    for (ssize_t i = 0; i < m; i++) {
        *p++ = ' ';
        *p++ = hex[d[i] >> 4];
        *p++ = hex[d[i] & 15];
    }
    *p++ = '\n';
    emit(line, (size_t)(p - line));
}

static int is_ctl_path(const char *path)
{
    size_t n = 0;
    static const char want[] = "midiC0D0";
    if (!path)
        return 0;
    while (path[n])
        n++;
    if (n < 8)
        return 0;
    for (int i = 0; i < 8; i++)
        if (path[n - 8 + i] != want[i])
            return 0;
    return 1;
}

static void note_open(const char *path, int flags, int fd)
{
    if (fd < 0 || fd >= MAXFD)
        return;
    if (is_ctl_path(path)) {
        tracked[fd] = 1;
        log_open(path, flags, fd);
    } else {
        tracked[fd] = 0;
    }
}

int open(const char *path, int flags, unsigned mode)
{
    RESOLVE(real_open, "open");
    int fd = real_open(path, flags, mode);
    note_open(path, flags, fd);
    return fd;
}

int open64(const char *path, int flags, unsigned mode)
{
    RESOLVE(real_open64, "open64");
    int fd = real_open64(path, flags, mode);
    note_open(path, flags, fd);
    return fd;
}

int openat(int dirfd, const char *path, int flags, unsigned mode)
{
    RESOLVE(real_openat, "openat");
    int fd = real_openat(dirfd, path, flags, mode);
    note_open(path, flags, fd);
    return fd;
}

int openat64(int dirfd, const char *path, int flags, unsigned mode)
{
    RESOLVE(real_openat64, "openat64");
    int fd = real_openat64(dirfd, path, flags, mode);
    note_open(path, flags, fd);
    return fd;
}

int close(int fd)
{
    RESOLVE(real_close, "close");
    if (fd >= 0 && fd < MAXFD)
        tracked[fd] = 0;
    return real_close(fd);
}

ssize_t read(int fd, void *buf, size_t n)
{
    RESOLVE(real_read, "read");
    ssize_t r = real_read(fd, buf, n);
    if (r > 0 && fd >= 0 && fd < MAXFD && tracked[fd])
        log_bytes('R', (const unsigned char *)buf, r);
    return r;
}

ssize_t write(int fd, const void *buf, size_t n)
{
    RESOLVE(real_write, "write");
    ssize_t r = real_write(fd, buf, n);
    if (r > 0 && fd >= 0 && fd < MAXFD && tracked[fd])
        log_bytes('W', (const unsigned char *)buf, r);
    return r;
}

/* Hardened (FORTIFY_SOURCE) builds call these instead of open/openat/read. */
static int (*real_open_2)(const char *, int);
static int (*real_open64_2)(const char *, int);
static int (*real_openat_2)(int, const char *, int);
static int (*real_openat64_2)(int, const char *, int);
static ssize_t (*real_read_chk)(int, void *, size_t, size_t);

int __open_2(const char *path, int flags)
{
    RESOLVE(real_open_2, "__open_2");
    int fd = real_open_2(path, flags);
    note_open(path, flags, fd);
    return fd;
}

int __open64_2(const char *path, int flags)
{
    RESOLVE(real_open64_2, "__open64_2");
    int fd = real_open64_2(path, flags);
    note_open(path, flags, fd);
    return fd;
}

int __openat_2(int dirfd, const char *path, int flags)
{
    RESOLVE(real_openat_2, "__openat_2");
    int fd = real_openat_2(dirfd, path, flags);
    note_open(path, flags, fd);
    return fd;
}

int __openat64_2(int dirfd, const char *path, int flags)
{
    RESOLVE(real_openat64_2, "__openat64_2");
    int fd = real_openat64_2(dirfd, path, flags);
    note_open(path, flags, fd);
    return fd;
}

ssize_t __read_chk(int fd, void *buf, size_t n, size_t buflen)
{
    RESOLVE(real_read_chk, "__read_chk");
    ssize_t r = real_read_chk(fd, buf, n, buflen);
    if (r > 0 && fd >= 0 && fd < MAXFD && tracked[fd])
        log_bytes('R', (const unsigned char *)buf, r);
    return r;
}

/* Marker: every process that loads the logger writes one line saying so. */
static int (*real_getpid)(void);

__attribute__((constructor)) static void ctl_loaded(void)
{
    char line[160];
    char comm[32];
    char *p = line;
    int i = 0;
    comm[0] = 0;
    RESOLVE(real_open, "open");
    RESOLVE(real_read, "read");
    RESOLVE(real_close, "close");
    RESOLVE(real_getpid, "getpid");
    if (real_open && real_read && real_close) {
        int fd = real_open("/proc/self/comm", 0, 0);
        if (fd >= 0) {
            ssize_t n = real_read(fd, comm, sizeof comm - 1);
            real_close(fd);
            comm[n > 0 ? n : 0] = 0;
            while (comm[i] && comm[i] != '\n')
                i++;
            comm[i] = 0;
        }
    }
    p = put_u(p, (unsigned long)now_ms());
    p = put_str(p, " L loaded pid=");
    p = put_u(p, real_getpid ? (unsigned long)real_getpid() : 0);
    p = put_str(p, " comm=");
    p = put_str(p, comm);
    *p++ = '\n';
    emit(line, (size_t)(p - line));
}
