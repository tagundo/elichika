import os
import io
import platform
import sys
import shutil

encrypted_folder = "static/encrypted/"
modding_elichika_path = "assets/package/pkg/"

if not os.path.exists(encrypted_folder):
    os.makedirs(encrypted_folder)
    
if not os.path.exists(modding_elichika_path):
    os.makedirs(modding_elichika_path)
    
def clear_terminal():
    system = platform.system()
    if system == 'Windows':
        os.system('cls')
    elif system == 'Linux' or system == 'Darwin':
        os.system('clear')

def manipulate_file(data, keys_0, keys_1, keys_2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((keys_1 ^ keys_0 ^ keys_2) >> 24 & 0xFF)
        keys_0 = (0x343fd * keys_0 + 0x269ec3) & 0xFFFFFFFF
        keys_1 = (0x343fd * keys_1 + 0x269ec3) & 0xFFFFFFFF
        keys_2 = (0x343fd * keys_2 + 0x269ec3) & 0xFFFFFFFF

# explorer code
clear_terminal()

# List all files in the directory with a ".zip" extension
zip_files = []
for root, dirs, files in os.walk(modding_elichika_path):
    for file in files:
        zip_files.append(os.path.relpath(os.path.join(root, file), modding_elichika_path))

zip_files.sort()

# Display the available zip files with corresponding numbers
print("Available files:")
for i, zip_file in enumerate(zip_files, start=1):
    print(f"{i}. {zip_file}")

# User input to choose a zip file by entering a number
try:
    chosen_number = int(input("Enter the number corresponding to the file you want to choose: "))
    
    # Check if the chosen number is valid
    if 1 <= chosen_number <= len(zip_files):
        zip_file_path = os.path.join(modding_elichika_path, zip_files[chosen_number - 1])
        print(f"You chose: {zip_file_path}")
        # Now you can work with the chosen zip file as needed
    else:
        print("Invalid number. Please enter a valid number.")
        sys.exit(1)
except ValueError:
    print("Invalid input. Please enter a number.")
    sys.exit(1)
                        
costume_filename = os.path.splitext(zip_file_path.split("/")[-1])[0]
encrypted_costume = "static/encrypted/" + os.path.splitext(zip_file_path.split("/")[-1])[0]

with open(zip_file_path, "rb") as file:
    data = bytearray(file.read())
    try:
        resize_input = input("Enter the new size for the bytearray (leave blank to keep current size): ")

        if resize_input:
            resize_input = int(resize_input)

            if resize_input < len(data):
                print("New size is smaller than the current size. No resizing done.")
            elif resize_input > len(data):
                # Resize the bytearray if the new size is larger
                data.extend([0] * (resize_input - len(data)))
                print(f"Resized bytearray to {resize_input} bytes.")
        else:
            print("No input provided. Bytearray size remains unchanged.")
            
    except ValueError:
        print("Invalid input. Please enter a valid integer.")
        sys.exit(1)
        
    key_0 = 12345
    key_1_input = input("Enter key1: ")
    if key_1_input.strip() == "":
        key_1 = 0
    else:
        key_1 = int(key_1_input)
    key_2_input = input("Enter key2: ")
    if key_2_input.strip() == "":
        key_2 = 0
    else:
        key_2 = int(key_2_input)
    print("encrypting pkg")
    manipulate_file(data, key_0, key_1, key_2)

    with open(encrypted_costume, "wb") as file:
        file.write(data)
     
print("FINISHED")