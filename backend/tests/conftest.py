import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="arena-test-")
os.environ["OFFLINE_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_TOKEN"] = "test-admin"
os.environ["YANDEX_API_KEY"] = ""
os.environ["UPLOADS_DIR"] = f"{_tmp}/uploads"
