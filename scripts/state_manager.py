"""Resumable pipeline state manager.
Tracks stages with input hash, parameter hash, and code hash.
Uses atomic writes (temporary file + rename).
"""
import hashlib, json, os, tempfile

class StateManager:
    def __init__(self, project_dir):
        self.project_dir = os.path.abspath(project_dir)
        self.state_dir = os.path.join(self.project_dir, ".state")
        os.makedirs(self.state_dir, exist_ok=True)

    def _hash_file(self, path):
        if not os.path.exists(path):
            return "missing"
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def compute_hash(self, input_files, params, code_files):
        h = hashlib.sha256()
        for p in sorted(input_files):
            abs_p = p if os.path.isabs(p) else os.path.join(self.project_dir, p)
            h.update(f"input:{p}:{self._hash_file(abs_p)}".encode())
        for p in sorted(code_files):
            h.update(f"code:{p}:{self._hash_file(p)}".encode())
        params_str = json.dumps(params, sort_keys=True)
        h.update(f"params:{params_str}".encode())
        return h.hexdigest()

    def is_current(self, stage_name, stage_hash):
        state_file = os.path.join(self.state_dir, f"{stage_name}.json")
        if not os.path.exists(state_file):
            return False
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("hash") == stage_hash
        except Exception:
            return False

    def save_state(self, stage_name, stage_hash, metadata=None):
        data = {
            "stage": stage_name,
            "hash": stage_hash,
            "metadata": metadata or {}
        }
        state_file = os.path.join(self.state_dir, f"{stage_name}.json")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.state_dir, prefix=f"{stage_name}_", suffix=".tmp")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, state_file)
