import glob
import os
import shutil
from datetime import datetime


# ============================================================
# 백업 위치 설정
# ============================================================
def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


# Termux: 공유 저장소(다운로드)의 영구 백업 위치.
# 경로를 바꾸고 싶으면 이 한 줄만 수정하면 된다.
TERMUX_BACKUP_ROOT = os.path.expanduser("~/storage/downloads/sukusta/backup")

# 비-Termux(PC 등): 기존과 동일하게 작업 폴더의 backup_db 를 사용.
# (Termux 내부에 만들어 둔 예전 백업도 여기에 있다 -> restore 가 이 위치도 함께 조사한다)
LOCAL_BACKUP_ROOT = "backup_db"


def get_backup_root():
    """현재 환경에서 새 백업을 만들 루트 폴더.

    SUKUSTA_BACKUP_ROOT 환경변수가 있으면 그 위치를 사용한다(안드로이드 APK 가
    공유 Download/sukusta/backup 로 지정). Termux/PC 동작은 그대로 유지."""
    env = os.environ.get("SUKUSTA_BACKUP_ROOT")
    if env:
        return os.path.expanduser(env)
    return TERMUX_BACKUP_ROOT if is_termux() else LOCAL_BACKUP_ROOT


# Asset-DB masters live under these two folders; we glob every *.db so that new
# dictionaries / languages (e.g. dictionary_th_k.db) are captured automatically
# instead of drifting out of a hand-maintained list. serverdata.db is derived
# from the asset DBs and userdata.db holds player state — all three must move as
# one coupled set so a restore stays internally consistent (a costume added to
# both the asset DB and userdata must be restored together).
ASSET_DB_GLOBS = ("assets/db/gl/*.db", "assets/db/jp/*.db")
EXTRA_BACKUP_FILES = ("serverdata.db", "userdata.db")

# Kept for backwards compatibility / documentation of the previous fixed set.
BACKUP_FILES = [
    "assets/db/gl/asset_a_en.db",
    "assets/db/gl/asset_i_en.db",
    "assets/db/gl/asset_a_ko.db",
    "assets/db/gl/asset_i_ko.db",
    "assets/db/gl/asset_a_zh.db",
    "assets/db/gl/asset_i_zh.db",
    "assets/db/gl/dictionary_en_k.db",
    "assets/db/gl/dictionary_ko_k.db",
    "assets/db/gl/dictionary_zh_k.db",
    "assets/db/gl/masterdata.db",
    "assets/db/jp/asset_a_ja.db",
    "assets/db/jp/asset_i_ja.db",
    "assets/db/jp/dictionary_ja_k.db",
    "assets/db/jp/masterdata.db",
    "serverdata.db",
    "userdata.db",
]


def backup_targets():
    """The full set of files a backup copies: every asset-DB master (globbed) plus
    the derived server DB and the user DB. Non-existent entries are filtered by the
    caller. Order is stable (sorted globs, then the extras)."""
    targets = []
    for pattern in ASSET_DB_GLOBS:
        targets.extend(sorted(glob.glob(pattern)))
    for extra in EXTRA_BACKUP_FILES:
        if extra not in targets:
            targets.append(extra)
    return targets


def _lz4():
    """Return the lz4.frame module when available, else None.

    lz4 is bundled with the Android app, so backups there are compressed
    transparently; on Termux/PC without lz4 we fall back to plain copies. Restore
    handles both, so old (uncompressed) backups keep working either way."""
    try:
        import lz4.frame as frame
        return frame
    except Exception:
        return None


def backup_files_to(folder, files=None, log=print):
    """Copy each existing path in *files* into *folder*, preserving its relative
    layout. When lz4 is available every file is written frame-compressed as
    "<rel>.lz4"; otherwise it is copied verbatim as "<rel>". Returns
    (backed_up, missing)."""
    if files is None:
        files = backup_targets()
    frame = _lz4()
    os.makedirs(folder, exist_ok=True)
    backed_up, missing = [], []
    for file_path in files:
        if not os.path.exists(file_path):
            missing.append(file_path)
            continue
        rel_path = os.path.relpath(file_path, start=".")
        dest_path = os.path.join(folder, rel_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        try:
            if frame is not None:
                with open(file_path, "rb") as src, \
                        frame.open(dest_path + ".lz4", "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            else:
                shutil.copy2(file_path, dest_path)
            backed_up.append(file_path)
        except Exception as exc:
            missing.append(file_path)
            if log:
                log(f"⚠ Failed to back up {file_path}: {exc}")
    return backed_up, missing


def backup_database_files():
    """
    Standalone script for backup functionality only.
    Backs up specified database files into a date/time–named folder.
    """
    try:
        # Termux 저장소 권한 확인
        if is_termux() and not os.path.exists(os.path.expanduser("~/storage")):
            print("Termux 저장소 접근이 없습니다. 먼저 실행하세요:")
            print("  termux-setup-storage   (그리고 권한 허용)")
            return False

        # Generate backup folder name (current date/time) under the chosen root
        backup_root = get_backup_root()
        backup_folder = os.path.join(
            backup_root, datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))

        # Create backup folder
        os.makedirs(backup_folder, exist_ok=True)
        print(f"Backup folder created: {backup_folder}")
        print(f"Compression: {'lz4' if _lz4() is not None else 'off (stored)'}")

        # Copy the whole coupled DB set (compressed when lz4 is available)
        backed_up_files, missing_files = backup_files_to(backup_folder)
        for file_path in backed_up_files:
            print(f"✓ Backed up: {file_path}")
        for file_path in missing_files:
            print(f"⚠ Missing file: {file_path}")

        # 백업 결과 보고
        print(f"\n=== Backup Complete ===")
        print(f"Files backed up: {len(backed_up_files)}개")
        print(f"Files missing: {len(missing_files)}개")
        print(f"Backup location: {backup_folder}")

        if missing_files:
            print(f"\nMissing files list:")
            for file in missing_files:
                print(f"  - {file}")

        return True

    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False


def main():
    """Main execution function"""
    print("=== Database Backup Tool ===")
    print("Backing up SIFAS game database files.\n")
    print(f"Backup location: {get_backup_root()}\n")

    # Confirm backup
    confirm = input("Would you like to start the backup? (y/n): ").strip().lower()

    if confirm in ["y", "yes", "예"]:
        if backup_database_files():
            print("\nBackup completed successfully!")
        else:
            print("\nAn error occurred during backup.")
    else:
        print("Backup cancelled.")


if __name__ == "__main__":
    main()
