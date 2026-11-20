"""Small shared helpers."""
import sys


def say(*args):
    """print() that never aborts a long run when stdout has gone away (closed terminal / dead tee pipe)."""
    try:
        print(*args, flush=True)
    except (BrokenPipeError, OSError, ValueError):
        try:
            sys.stdout = open("/dev/null", "w")
        except OSError:
            pass
