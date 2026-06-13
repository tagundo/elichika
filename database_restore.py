import os
import shutil
import hashlib
from datetime import datetime


# ============================================================
# 백업 위치 설정 (database_backup.py 와 동일하게 유지)
# ============================================================
def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "")


# Termux: 공유 저장소(다운로드)의 새 백업 위치
TERMUX_BACKUP_ROOT = os.path.expanduser("~/storage/downloads/sukusta/backup")
# 비-Termux(PC 등) 및 예전 Termux 내부 백업 위치
LOCAL_BACKUP_ROOT = "backup_db"


def get_backup_root():
    """새 백업(복원 전 백업 포함)을 만들 루트 폴더."""
    return TERMUX_BACKUP_ROOT if is_termux() else LOCAL_BACKUP_ROOT


def get_all_backup_roots():
    """복원 시 조사할 모든 백업 위치 (새 위치 + 기존 위치).
    예전에 Termux 내부 backup_db 에 만든 백업을 놓치지 않도록 둘 다 본다."""
    roots = []
    if is_termux():
        roots.append(TERMUX_BACKUP_ROOT)   # 새 위치 (공유 저장소)
    roots.append(LOCAL_BACKUP_ROOT)        # 기존 위치 (항상 포함)

    # 절대경로 기준 중복 제거 (순서 유지)
    seen, unique = set(), []
    for r in roots:
        ap = os.path.abspath(os.path.expanduser(r))
        if ap not in seen:
            seen.add(ap)
            unique.append(ap)
    return unique


def backup_location_label(backup_path):
    """백업이 어느 위치에 있는지 보기 좋은 라벨로 돌려준다."""
    ap = os.path.abspath(backup_path)
    termux_root = os.path.abspath(os.path.expanduser(TERMUX_BACKUP_ROOT))
    local_root = os.path.abspath(LOCAL_BACKUP_ROOT)
    if ap.startswith(termux_root):
        return "shared storage (new)"
    if ap.startswith(local_root):
        return "termux internal / local (old)"
    return os.path.dirname(ap)


def list_backup_folders():
    """모든 백업 위치에서 백업 폴더를 모아 최신순(이름 기준)으로 반환."""
    backups = []
    seen = set()
    for root_abs in get_all_backup_roots():
        if not os.path.isdir(root_abs):
            continue
        for item in os.listdir(root_abs):
            backup_path = os.path.join(root_abs, item)
            if os.path.isdir(backup_path) and backup_path not in seen:
                seen.add(backup_path)
                backups.append(backup_path)

    # 폴더 이름(타임스탬프) 기준 최신순 정렬 (위치가 달라도 시간순으로 섞어 보여줌)
    backups.sort(key=lambda p: os.path.basename(p), reverse=True)
    return backups


def verify_file_integrity(file1, file2):
    """Verify integrity by comparing hash values of two files."""
    def get_file_hash(filepath):
        hash_sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    try:
        return get_file_hash(file1) == get_file_hash(file2)
    except Exception:
        return False


def create_pre_restore_backup():
    """Back up the current state before restoration (새 백업 위치에 저장)."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pre_backup_folder = os.path.join(get_backup_root(), f"{timestamp}_pre_restore")

    # List of files backed up by database_backup.py
    current_files = [
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

    backed_up_files = []
    for file_path in current_files:
        if os.path.exists(file_path):
            rel_path = os.path.relpath(file_path, start=".")
            dest_path = os.path.join(pre_backup_folder, rel_path)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(file_path, dest_path)
            backed_up_files.append(file_path)

    return pre_backup_folder, backed_up_files


def restore_from_backup(backup_path):
    """Restore files from the selected backup to their original locations."""
    print(f"\nStarting restoration from backup '{backup_path}'...")

    # Backup current state before restore
    pre_backup_path, pre_backed_files = create_pre_restore_backup()
    print(f"Current state backed up to: {pre_backup_path} ({len(pre_backed_files)} files)")

    restored_files = []
    skipped_files = []
    failed_files = []

    # Traverse all files in the backup folder
    for root, dirs, files in os.walk(backup_path):
        for file in files:
            backup_file_path = os.path.join(root, file)
            # Calculate relative path within backup
            rel_path = os.path.relpath(backup_file_path, backup_path)
            # Determine target path for restoration
            target_path = os.path.join(".", rel_path)

            try:
                # If target exists and is identical, skip
                if os.path.exists(target_path):
                    if verify_file_integrity(backup_file_path, target_path):
                        skipped_files.append(rel_path)
                        continue

                # Create directory if needed
                os.makedirs(os.path.dirname(target_path), exist_ok=True)

                # Copy file
                shutil.copy2(backup_file_path, target_path)

                # Verify copy integrity
                if verify_file_integrity(backup_file_path, target_path):
                    restored_files.append(rel_path)
                    print(f"✓ Restored: {rel_path}")
                else:
                    failed_files.append(f"{rel_path} (verification failed)")
                    print(f"❌ Verification failed: {rel_path}")

            except Exception as e:
                failed_files.append(f"{rel_path} ({str(e)})")
                print(f"❌ Restoration failed: {rel_path} - {e}")

    return {
        "pre_backup_path": pre_backup_path,
        "restored": restored_files,
        "skipped": skipped_files,
        "failed": failed_files,
    }


def select_backup(backups):
    """Let the user select which backup to restore."""
    print("\n=== Available Backups ===")
    for i, backup in enumerate(backups, 1):
        backup_name = os.path.basename(backup)
        label = backup_location_label(backup)
        print(f"[{i}] {backup_name}   ({label})")

    while True:
        try:
            choice = input("\nEnter the number of the backup to restore: ").strip()
            index = int(choice) - 1
            if 0 <= index < len(backups):
                return backups[index]
            else:
                print("❌ Invalid number, please try again.")
        except ValueError:
            print("❌ Please enter a numeric value.")


def main():
    print("=== Database Restore Tool ===")
    print("This will restore backed-up database files to their original locations.\n")
    print("Searching backups in:")
    for r in get_all_backup_roots():
        print(f"  - {r}")
    print()

    # List available backups (across all locations)
    backups = list_backup_folders()
    if not backups:
        print("❌ No backup folders found.")
        print("Please run database_backup.py first to create a backup.")
        return

    # Select backup
    selected_backup = select_backup(backups)
    print(f"\nSelected backup: {os.path.basename(selected_backup)}")
    print(f"Location: {selected_backup}")

    # Final confirmation
    print("\n⚠ WARNING: This will overwrite existing database files.")
    print("Your current state will be backed up automatically.")
    confirm = input("\nDo you want to proceed with restoration? (y/N): ").strip().lower()

    if confirm not in ["y", "yes", "예"]:
        print("Restoration cancelled.")
        return

    # Execute restore
    result = restore_from_backup(selected_backup)

    # Report results
    print("\n=== Restoration Complete ===")
    print(f"Pre-restore backup location: {result['pre_backup_path']}")
    print(f"Files restored: {len(result['restored'])}")
    print(f"Files skipped (identical): {len(result['skipped'])}")
    print(f"Files failed: {len(result['failed'])}")

    if result["failed"]:
        print("\nFailed files list:")
        for failed in result["failed"]:
            print(f"  - {failed}")

    print("\nRestore process finished!")
    if result["failed"]:
        print("Some files failed to restore. Please check the logs.")


if __name__ == "__main__":
    main()
