"""
server.core.backup 单元测试
BackupManager 占位实现与单例 get_backup_manager
"""
from server.core import backup as backup_mod
from server.core.backup import BackupManager, BackupType, get_backup_manager


class TestBackupType:
    def test_values(self):
        assert BackupType.FULL.value == "full"
        assert BackupType.INCREMENTAL.value == "incremental"
        assert BackupType.DIFFERENTIAL.value == "differential"


class TestBackupManager:
    def test_list_empty(self):
        assert BackupManager().list_backups() == []

    def test_create_stub(self):
        bm = BackupManager()
        r = bm.create_backup(BackupType.INCREMENTAL, description="desc")
        assert r["backup_type"] == "incremental"
        assert r["status"] == "not_implemented"
        assert r["description"] == "desc"
        assert r["total_size"] == 0

    def test_create_default_full(self):
        r = BackupManager().create_backup()
        assert r["backup_type"] == "full"

    def test_get_status(self):
        assert BackupManager().get_status() == {"total_backups": 0}

    def test_get_backup_none(self):
        assert BackupManager().get_backup("x") is None

    def test_delete_false(self):
        assert BackupManager().delete_backup("x") is False

    def test_restore_stub(self):
        assert BackupManager().restore_backup("x") == {"status": "not_implemented"}

    def test_import_stub(self):
        assert BackupManager().import_backup("/tmp/x.zip") == {"status": "not_implemented"}


class TestGetBackupManager:
    def test_singleton(self, monkeypatch):
        monkeypatch.setattr(backup_mod, "_manager", None)
        a = get_backup_manager()
        b = get_backup_manager()
        assert a is b
        assert isinstance(a, BackupManager)

    def test_reuse_existing(self, monkeypatch):
        sentinel = BackupManager()
        monkeypatch.setattr(backup_mod, "_manager", sentinel)
        assert get_backup_manager() is sentinel