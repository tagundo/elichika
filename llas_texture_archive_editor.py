import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image
import os
import io
import json

def manipulate_file(data, key0, key1, key2):
    for i in range(len(data)):
        data[i] = data[i] ^ ((key1 ^ key0 ^ key2) >> 24 & 0xFF)
        key0 = (0x343fd * key0 + 0x269ec3) & 0xFFFFFFFF
        key1 = (0x343fd * key1 + 0x269ec3) & 0xFFFFFFFF
        key2 = (0x343fd * key2 + 0x269ec3) & 0xFFFFFFFF
    return data

class ArchiveEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Archive Editor")

        self.archive_path = None
        self.meta_path = None
        self.archive_data = None
        self.metadata = {"entries": []}

        self._build_ui()

    def _build_ui(self):
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill=tk.X, padx=6, pady=6)

        tk.Button(top_frame, text="Create Archive", command=self.create_archive).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="Open Archive", command=self.open_archive).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="Extract", command=self.extract_selected).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="Add", command=self.add_files).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="Replace", command=self.replace_file).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=4)

        cols = ("name", "head", "size")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=150, anchor='center')
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.tree.bind("<Double-1>", lambda e: self.preview_selected())

    def _meta_path_for_archive(self, archive_path):
        return archive_path + ".meta.json"

    def _load_metadata(self):
        if not self.meta_path or not os.path.exists(self.meta_path):
            self.metadata = {"entries": []}
            return
        with open(self.meta_path, 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)
            if "entries" not in self.metadata:
                self.metadata = {"entries": []}

    def _save_metadata(self):
        if not self.meta_path:
            return
        with open(self.meta_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for entry in self.metadata.get('entries', []):
            self.tree.insert('', tk.END, values=(entry['name'], entry['head'], entry['size']))

    def create_archive(self):
        path = filedialog.asksaveasfilename(title="Create Archive", defaultextension=".bin", filetypes=[("Binary", "*.bin"), ("All files", "*")])
        if not path:
            return
        open(path, 'wb').close()
        self.archive_path = path
        self.meta_path = self._meta_path_for_archive(path)
        self.archive_data = bytearray()
        self.metadata = {"entries": []}
        self._save_metadata()
        self._refresh_tree()
        messagebox.showinfo("Created", f"Archive created: {path}")

    def open_archive(self):
        path = filedialog.askopenfilename(title="Open Archive", filetypes=[("Binary", "*.bin"), ("All files", "*")])
        if not path:
            return
        self.archive_path = path
        self.meta_path = self._meta_path_for_archive(path)
        with open(path, 'rb') as f:
            self.archive_data = bytearray(f.read())
        self._load_metadata()
        self._refresh_tree()
        messagebox.showinfo("Opened", f"Archive opened: {path}")

    def extract_selected(self):
        if not self.archive_data:
            messagebox.showerror("Error", "No archive opened")
            return
        sel = self.tree.selection()
        if not sel:
            return
        folder = filedialog.askdirectory(title="Select folder to extract to")
        if not folder:
            return
        count = 0
        for item in sel:
            vals = self.tree.item(item, 'values')
            name = vals[0]
            head = int(vals[1])
            size = int(vals[2])
            raw = bytearray(self.archive_data[head:head+size])
            raw = manipulate_file(raw, 12345, 0, 0)

            ext = 'bin'
            try:
                img = Image.open(io.BytesIO(raw))
                ext = (img.format or 'png').lower()
            except Exception:
                ext = 'bin'

            out_name = f"{os.path.basename(self.archive_path)}_{head}.{ext}"
            out_path = os.path.join(folder, out_name)
            with open(out_path, 'wb') as out_f:
                out_f.write(raw)
            count += 1
        messagebox.showinfo("Extracted", f"Extracted {count} items to {folder}")

    def add_files(self):
        if self.archive_data is None:
            messagebox.showerror("Error", "Open or create an archive first")
            return
        files = filedialog.askopenfilenames(title="Select files to add")
        if not files:
            return
        for fp in files:
            name = os.path.basename(fp)
            try:
                img = Image.open(fp)
                buf = io.BytesIO()
                img.convert('RGBA').save(buf, format='PNG', compress_level=9)
                data = bytearray(buf.getvalue())
            except Exception:
                with open(fp, 'rb') as f:
                    data = bytearray(f.read())

            data = manipulate_file(data, 12345, 0, 0)
            head = len(self.archive_data)
            size = len(data)
            entry = {'name': name, 'head': head, 'size': size}
            self.archive_data += data
            self.metadata['entries'].append(entry)

        with open(self.archive_path, 'wb') as f:
            f.write(self.archive_data)
        self._save_metadata()
        self._refresh_tree()
        messagebox.showinfo("Added", f"Added {len(files)} file(s) to archive")

    def replace_file(self):
        if self.archive_data is None:
            messagebox.showerror("Error", "Open or create an archive first")
            return
        sel = self.tree.selection()
        if not sel or len(sel) != 1:
            messagebox.showerror("Error", "Select a single entry to replace")
            return
        item = sel[0]
        vals = self.tree.item(item, 'values')
        name = vals[0]
        head = int(vals[1])
        old_size = int(vals[2])

        fp = filedialog.askopenfilename(title=f"Select replacement for {name}")
        if not fp:
            return

        try:
            img = Image.open(fp)
            buf = io.BytesIO()
            img.convert('RGBA').save(buf, format='PNG', compress_level=9)
            newdata = bytearray(buf.getvalue())
        except Exception:
            with open(fp, 'rb') as f:
                newdata = bytearray(f.read())

        newdata = manipulate_file(newdata, 12345, 0, 0)

        if len(newdata) <= old_size:
            self.archive_data[head:head+old_size] = newdata + b'\x00' * (old_size - len(newdata))
            for e in self.metadata['entries']:
                if e['head'] == head and e['name'] == name:
                    e['size'] = old_size
                    break
            messagebox.showinfo("Replaced", "Replaced in-place (size fits)")
        else:
            new_head = len(self.archive_data)
            new_size = len(newdata)
            self.archive_data += newdata
            for e in self.metadata['entries']:
                if e['head'] == head and e['name'] == name:
                    e['head'] = new_head
                    e['size'] = new_size
                    break
            messagebox.showinfo("Replaced", "Appended replacement (old data kept)")

        with open(self.archive_path, 'wb') as f:
            f.write(self.archive_data)
        self._save_metadata()
        self._refresh_tree()

    def delete_selected(self):
        if self.archive_data is None:
            messagebox.showerror("Error", "Open or create an archive first")
            return
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("Delete", f"Delete {len(sel)} entries (remove from archive)?"):
            return

        new_entries = []
        new_archive = bytearray()
        current_head = 0

        remove_heads = set(int(self.tree.item(i, 'values')[1]) for i in sel)

        for entry in self.metadata['entries']:
            if entry['head'] in remove_heads:
                continue
            data = self.archive_data[entry['head']:entry['head'] + entry['size']]
            entry['head'] = current_head
            current_head += len(data)
            new_archive += data
            new_entries.append(entry)

        self.metadata['entries'] = new_entries
        self.archive_data = new_archive

        with open(self.archive_path, 'wb') as f:
            f.write(self.archive_data)
        self._save_metadata()
        self._refresh_tree()
        messagebox.showinfo("Deleted", "Selected files removed and archive compacted.")

    def preview_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], 'values')
        head = int(vals[1])
        size = int(vals[2])
        raw = bytearray(self.archive_data[head:head+size])
        raw = manipulate_file(raw, 12345, 0, 0)
        try:
            img = Image.open(io.BytesIO(raw))
            img.show()
        except Exception as e:
            messagebox.showerror("Preview", f"Not an image or failed to open: {e}")

if __name__ == '__main__':
    root = tk.Tk()
    root.geometry('800x450')
    app = ArchiveEditor(root)
    root.mainloop()