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
    """현재 환경에서 새 백업을 만들 루트 폴더."""
    return TERMUX_BACKUP_ROOT if is_termux() else LOCAL_BACKUP_ROOT


# List of files to back up
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

        # Copy each file into the backup folder
        backed_up_files = []
        missing_files = []

        for file_path in BACKUP_FILES:
            if os.path.exists(file_path):
                # Preserve relative directory structure
                rel_path = os.path.relpath(file_path, start=".")
                dest_path = os.path.join(backup_folder, rel_path)

                # Create directories as needed
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                # Copy file
                shutil.copy2(file_path, dest_path)
                backed_up_files.append(file_path)
                print(f"✓ Backed up: {file_path}")
            else:
                missing_files.append(file_path)
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
