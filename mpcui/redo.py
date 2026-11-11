"""REDO for Console's tape: Console only has UNDO. This wraps Engine.undo so that what an undo puts back is kept (the other way round:
what it overwrote), and redo() puts it back again. Any new edit or recording in between ends the redo."""
import threading

KEEP = 20


def _capture(e, entry):
    """The same entry, but holding what is on the tape now (so applying it undoes the undo). None when an item can't be turned round."""
    out = []
    for item in entry:
        if item[0] == "regions":
            out.append(("regions", item[1], [list(r) for r in e.regions[item[1]]]))
        elif item[0] == "volume":
            out.append(("volume", item[1], e.volumes[item[1]]))
        elif item[0] == "pan":
            out.append(("pan", item[1], e.pans[item[1]]))
        elif item[0] == "stereo":
            return None
        else:
            t, a, old = item
            arr = e.tracks[t]
            if arr is None:
                return None
            out.append((t, a, arr[a:a + len(old)].copy()))
    return out


def _sig(e):
    return tuple(id(x) for x in e.undo_stack)


def install(Engine):
    orig_undo = Engine.undo

    def undo(self):
        with self.lock:
            while self.undo_stack and not self.undo_stack[-1]:
                self.undo_stack.pop()
            entry = self.undo_stack[-1] if (self.undo_stack and not self.recording) else None
            inv = _capture(self, entry) if entry else None
            chain = getattr(self, "_redo_sig", None) == _sig(self)       # still the same run of undos / redos
        ok = orig_undo(self)
        if not ok:
            return False
        if not chain or getattr(self, "_redo", None) is None:
            self._redo = []                             # (something else happened since: start again)
        if inv is not None:
            self._redo.append(inv)
            del self._redo[:-KEEP]
        else:
            self._redo.clear()
        self._redo_sig = _sig(self)
        return True

    def redo(self):
        with self.lock:
            stack = getattr(self, "_redo", None)
            if not stack or self.recording or getattr(self, "_redo_sig", None) != _sig(self):
                if stack:
                    stack.clear()
                return False
            inv = stack.pop()
            back = _capture(self, inv)                  # what to undo this redo with
            if back is None:
                stack.clear()
                return False
            self.undo_stack.append(inv)
        ok = orig_undo(self)                            # applies inv (and takes it off the stack again)
        with self.lock:
            self.undo_stack.append(back)
            del self.undo_stack[:-getattr(__import__("audio"), "UNDO_STEPS", 8)]
            self._redo_sig = _sig(self)
        return ok

    Engine.undo, Engine.redo = undo, redo
