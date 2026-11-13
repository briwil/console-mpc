/* The C functions Console calls (drums.py, through ctypes). One engine per library file: drums.py loads
 * a second copy of the file for the engine you play by hand, as it does for the LXR. */
static engine_t *E = 0;

extern "C" {
int sw_init(float sample_rate) { if(!E) E = create(sample_rate); return E ? VOICES : 0; }
int sw_voices(void) { return VOICES; }
void sw_set(const char *key, int value)
{
    char b[16];
    snprintf(b, sizeof b, "%d", value);
    if(E) set_param(E, key, b);
}
int sw_get(const char *key)
{
    char b[32];
    if(!E || get_param(E, key, b, sizeof b) < 0) return -1;
    return atoi(b);
}
void sw_trigger(int voice, int velocity) { if(E && voice >= 0 && voice < VOICES && velocity > 0) trigger(E, voice, velocity); }
void sw_render(float *out, int frames) { if(E) render_voices(E, out, frames); }
}
