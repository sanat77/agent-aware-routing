"""File attachments stored on disk under a per-task directory."""
import os

from .errors import NotFoundError, ValidationError

MAX_FILENAME = 100


def safe_filename(name):
    """Reduce a user-supplied name to a safe base filename or raise ValidationError."""
    if not isinstance(name, str):
        raise ValidationError("filename must be a string", {"filename": "invalid"})
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = base.replace(" ", "_")
    if base in ("", ".", "..") or base.startswith("."):
        raise ValidationError("invalid filename", {"filename": "invalid"})
    if len(base) > MAX_FILENAME:
        raise ValidationError("filename too long", {"filename": "too_long"})
    return base


class AttachmentStore:
    def __init__(self, base_dir):
        self.base_dir = os.path.abspath(base_dir)

    def task_dir(self, task_id):
        return os.path.join(self.base_dir, f"task_{int(task_id)}")

    def path_for(self, task_id, filename):
        directory = self.task_dir(task_id)
        path = os.path.abspath(os.path.join(directory, safe_filename(filename)))
        if os.path.commonpath([path, directory]) != directory:
            raise ValidationError("invalid filename", {"filename": "invalid"})
        return path

    def save(self, task_id, filename, content):
        path = self.path_for(task_id, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return os.path.basename(path)

    def read(self, task_id, filename):
        path = self.path_for(task_id, filename)
        if not os.path.isfile(path):
            raise NotFoundError("attachment not found")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def list(self, task_id):
        directory = self.task_dir(task_id)
        if not os.path.isdir(directory):
            return []
        return sorted(name for name in os.listdir(directory) if not name.startswith("."))
