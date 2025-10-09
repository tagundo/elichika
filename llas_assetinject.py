import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import sqlite3
import os
import io

DB_PATH = "assets/db/gl/asset_a_en.db"

class ArchiveApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Archive Injector")
        self.conn = None

        if not os.path.exists(DB_PATH):
            messagebox.showerror("Error", f"Database not found: {DB_PATH}")
            self.root.destroy()
            return

        self.conn = sqlite3.connect(DB_PATH)

        self.open_btn = tk.Button(root, text="Open Archive", command=self.open_archive)
        self.open_btn.pack(pady=5)

        self.tree = ttk.Treeview(
            root,
            columns=("table_name", "asset_path", "head", "size", "key1", "key2", "injected"),
            show="headings"
        )
        for col in ("table_name", "asset_path", "head", "size", "key1", "key2", "injected"):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=5)

        self.inject_btn = tk.Button(btn_frame, text="Inject", state=tk.DISABLED, command=self.inject_file)
        self.inject_btn.grid(row=0, column=0, padx=5)

        self.preview_btn = tk.Button(btn_frame, text="Preview", state=tk.DISABLED, command=self.preview_file)
        self.preview_btn.grid(row=0, column=1, padx=5)

        self.save_btn = tk.Button(btn_frame, text="Save", state=tk.DISABLED, command=self.save)
        self.save_btn.grid(row=0, column=2, padx=5)

        self.save_as_btn = tk.Button(btn_frame, text="Save As", state=tk.DISABLED, command=self.save_as)
        self.save_as_btn.grid(row=0, column=3, padx=5)

        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

        self.archive_path = None
        self.archive_data = None  # in-memory copy of archive

    def open_archive(self):
        filepath = filedialog.askopenfilename(title="Select Archive")
        if not filepath:
            return

        self.archive_path = filepath
        with open(filepath, "rb") as f:
            self.archive_data = bytearray(f.read())

        archive_name = os.path.basename(filepath)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT asset_path, head, size, key1, key2
            FROM texture
            WHERE pack_name = ?
        """, (archive_name,))

        rows = cursor.fetchall()
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", tk.END, values=("texture", *row, "No"))

        self.save_btn.config(state=tk.NORMAL)
        self.save_as_btn.config(state=tk.NORMAL)

    def on_row_select(self, event):
        selected = self.tree.selection()
        if selected:
            self.inject_btn.config(state=tk.NORMAL)
            self.preview_btn.config(state=tk.NORMAL)
        else:
            self.inject_btn.config(state=tk.DISABLED)
            self.preview_btn.config(state=tk.DISABLED)

    def manipulate_file(self, data, key0, key1, key2):
        for i in range(len(data)):
            data[i] = data[i] ^ ((key1 ^ key0 ^ key2) >> 24 & 0xFF)
            key0 = (0x343fd * key0 + 0x269ec3) & 0xFFFFFFFF
            key1 = (0x343fd * key1 + 0x269ec3) & 0xFFFFFFFF
            key2 = (0x343fd * key2 + 0x269ec3) & 0xFFFFFFFF
        return data

    def inject_file(self):
        if self.archive_data is None:
            messagebox.showerror("Error", "No archive opened")
            return

        selected_item = self.tree.selection()
        if not selected_item:
            return

        values = self.tree.item(selected_item, "values")
        table_name, asset_path, head, size, key1, key2, injected = values

        file_to_inject = filedialog.askopenfilename(title="Select File to Inject")
        if not file_to_inject:
            return

        try:
            img = Image.open(file_to_inject)
            self.open_image_settings(img, selected_item, int(head), int(size), int(key1), int(key2))
        except Exception:
            # Non-image fallback
            with open(file_to_inject, "rb") as f:
                data = bytearray(f.read())
            if len(data) > int(size):
                messagebox.showerror("Error", f"File too large! Max size: {size}")
                return
            self._finalize_injection(data, selected_item, int(head), int(size), int(key1), int(key2))

    def open_image_settings(self, img, selected_item, head, size, key1, key2):
        win = tk.Toplevel(self.root)
        win.title("Image Settings")

        tk.Label(win, text="Mode:").grid(row=0, column=0, padx=5, pady=5)
        mode_var = tk.StringVar(value="RGB")
        mode_dropdown = ttk.Combobox(win, textvariable=mode_var, values=["RGB", "P"])
        mode_dropdown.grid(row=0, column=1, padx=5, pady=5)

        def on_ok():
            try:
                buf = io.BytesIO()
                save_kwargs = {}
                save_kwargs["compress_level"] = 9

                img.convert(mode_var.get()).save(buf, format="PNG", **save_kwargs)
                data = bytearray(buf.getvalue())

                if len(data) > size:
                    messagebox.showerror("Error", f"File too large! Max size: {size}")
                    return

                self._finalize_injection(data, selected_item, head, size, key1, key2)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Image processing failed: {e}")

        tk.Button(win, text="Cancel", command=win.destroy).grid(row=2, column=0, padx=5, pady=5)
        tk.Button(win, text="OK", command=on_ok).grid(row=2, column=1, padx=5, pady=5)

    def _finalize_injection(self, data, selected_item, head, size, key1, key2):
        key0 = 12345
        data = self.manipulate_file(data, key0, key1, key2)
        data += b"\x00" * (size - len(data))

        try:
            self.archive_data[head:head+size] = data
            self.tree.set(selected_item, column="injected", value="Yes")
            messagebox.showinfo("Success", "File injected (not saved yet)")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to inject: {e}")				  																																									 

    def preview_file(self):
        if self.archive_data is None:
            messagebox.showerror("Error", "No archive opened")
            return

        selected_item = self.tree.selection()
        if not selected_item:
            return

        values = self.tree.item(selected_item, "values")
        table_name, asset_path, head, size, key1, key2, injected = values

        head = int(head)
        size = int(size)
        key0 = 12345
        key1 = int(key1)
        key2 = int(key2)

        raw_data = bytearray(self.archive_data[head:head+size])
        raw_data = self.manipulate_file(raw_data, key0, key1, key2)

        try:
            img = Image.open(io.BytesIO(raw_data))
            preview_win = tk.Toplevel(self.root)
            preview_win.title(f"Preview - {asset_path}")
            tk_img = ImageTk.PhotoImage(img)
            lbl = tk.Label(preview_win, image=tk_img)
            lbl.image = tk_img
            lbl.pack()
        except Exception as e:
            messagebox.showerror("Preview Error", f"Could not preview as image: {e}")

    def save(self):
        if not self.archive_path or self.archive_data is None:
            return
        try:
            with open(self.archive_path, "wb") as f:
                f.write(self.archive_data)
            messagebox.showinfo("Saved", f"Archive saved: {self.archive_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def save_as(self):
        if self.archive_data is None:
            return
        filepath = filedialog.asksaveasfilename(title="Save Archive As")
        if not filepath:
            return
        try:
            with open(filepath, "wb") as f:
                f.write(self.archive_data)
            messagebox.showinfo("Saved", f"Archive saved as: {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save as: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ArchiveApp(root)
    root.mainloop()
