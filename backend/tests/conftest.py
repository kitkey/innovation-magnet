import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="arena-test-")
os.environ["OFFLINE_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_TOKEN"] = "test-admin"
