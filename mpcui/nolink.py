"""SETTINGS > SYNC on the MPC: INTERNAL or EXTERNAL only (no Ableton Link: the MPC has no network for it)."""


def install(menu_mod):
    M = menu_mod.Menu
    o_change = M.change

    def change(self, delta, fine=False):
        e = self.engine
        if e is not None and menu_mod.SETTINGS[self.row] == "SYNC":
            e.set_sync_mode("internal" if e.sync_mode == "external" else "external")
            self.say({"internal": "CONSOLE SENDS MIDI CLOCK, START AND STOP",
                      "external": "CONSOLE FOLLOWS THE CLOCK, START AND STOP IT IS SENT"}[e.sync_mode])
            return
        o_change(self, delta, fine)

    M.change = change
