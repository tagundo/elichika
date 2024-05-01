import sqlite3
import os
import shutil
import sys
import platform

folder_path = "assets/data/sql"
if not os.path.exists(folder_path):
    os.makedirs(folder_path)
    
def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear') 
    
def import_to_multiple_dbs(source_sql_file, target_db_list):
    # Split SQL statements into individual queries
    with open(source_sql_file, 'r') as sql_file:
        sql_statements = sql_file.read()
    queries = sql_statements.split(';')

    for target_db in target_db_list:
        target_conn = sqlite3.connect(target_db)
        target_cursor = target_conn.cursor()

        try:
            # Execute each query in the target database
            for query in queries:
                if query.strip():  # Skip empty queries
                    try:
                        target_cursor.execute(query)
                    except sqlite3.OperationalError as e:
                        if "no such table" not in str(e):
                            raise
                        #print(f"Skipping query in {target_db}: {e}")

            target_conn.commit()
            print(f"Data successfully imported to {target_db}.")

        except sqlite3.Error as e:
            print(f"SQLite error in {target_db}: {e}")

        finally:
            # Close the target database connection
            target_conn.close()

# List all files in the directory and its subdirectories with a ".zip" extension
zip_files = []
for root, dirs, files in os.walk(folder_path):
    for file in files:
        if file.endswith(".sql"):
            zip_files.append(os.path.relpath(os.path.join(root, file), folder_path))

clear_terminal()
print("Available .sql files:")
for i, zip_file in enumerate(zip_files, start=1):
    print(f"{i}. {zip_file}")

# User input to choose a zip file by entering a number
try:
    chosen_number = int(input("Enter the number corresponding to the .sql file you want to choose: "))
    
    # Check if the chosen number is valid
    if 1 <= chosen_number <= len(zip_files):
        chosen_zip_file = os.path.join(folder_path, zip_files[chosen_number - 1])
        print(f"You chose: {chosen_zip_file}")
        # Now you can work with the chosen zip file as needed
    else:
        print("Invalid number. Please enter a valid number.")
        sys.exit(1)
except ValueError:
    print("Invalid input. Please enter a number.")
    sys.exit(1)

target_dbs = [
    'assets/db/gl/masterdata.db',
    'assets/db/jp/masterdata.db'
]
import_to_multiple_dbs(chosen_zip_file, target_dbs)
