import sqlite3
import os
import shutil

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

# Example usage:
source_sql_file_input = "assets/data/" + input("Enter SQL filename: ") + ".sql"
if source_sql_file_input == "assets/data/":
    print("No file selected")
    sys.exit(1)

target_dbs = [
    'assets/db/gl/masterdata.db',
    'assets/db/jp/masterdata.db'
]
import_to_multiple_dbs(source_sql_file_input, target_dbs)
