
import os
import shutil
from datetime import datetime

def backup_database_files():
    """
    Standalone script for backup functionality only.
    Backs up specified database files into a date/time–named folder.
    """
    
    # List of files to back up
    backup_files = [
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
        "userdata.db"
    ]
    
    try:
        # Generate backup folder name (current date/time)
        backup_folder = f"backup_db/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        
        # Create backup folder
        os.makedirs(backup_folder, exist_ok=True)
        print(f"Backup folder created: {backup_folder}")
        
        # Copy each file into the backup folder
        backed_up_files = []
        missing_files = []
        
        for file_path in backup_files:
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
    
    # Confirm backup
    confirm = input("Would you like to start the backup? (y/n): ").strip().lower()
    
    if confirm in ['y', 'yes', '예']:
        if backup_database_files():
            print("\nBackup completed successfully!")
        else:
            print("\nAn error occurred during backup.")
    else:
        print("Backup cancelled.")

if __name__ == "__main__":
    main()

