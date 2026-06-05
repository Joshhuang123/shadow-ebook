#!/usr/bin/env python3
"""
Shadow Learning - Simple GUI with Tkinter (requires tkinter)
For systems without tkinter, use the CLI version: main.py
"""
import sys
import os

# Try tkinter, fall back to CLI
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False
    print("⚠️ Tkinter not available. Run: main.py")
    print("\nTo install tkinter on macOS:")
    print("  brew install python-tk@3.14")
    print("\nOr use the CLI version:")
    print("  cd ~/shadow-learning")
    print("  source venv/bin/activate")
    print("  python3 main.py")
    sys.exit(1)


class ShadowLearningGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🦊 Shadow Learning")
        self.root.geometry("800x600")
        
        # Setup paths
        self.shadow_path = os.path.dirname(os.path.abspath(__file__))
        self.venv_python = os.path.join(self.shadow_path, "venv", "bin", "python3")
        
        # Current media info
        self.media_loaded = False
        self.current_file = None
        
        self.create_widgets()
        
    def create_widgets(self):
        """Create GUI widgets"""
        # Title
        title = tk.Label(self.root, text="🦊 Shadow Learning", font=("Arial", 24, "bold"))
        title.pack(pady=20)
        
        subtitle = tk.Label(self.root, text="English Shadowing Practice", font=("Arial", 12))
        subtitle.pack(pady=5)
        
        # Status frame
        status_frame = tk.Frame(self.root)
        status_frame.pack(pady=20, fill="x", padx=50)
        
        self.status_label = tk.Label(status_frame, text="📁 No media loaded", font=("Arial", 14))
        self.status_label.pack()
        
        # Buttons frame
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=30)
        
        # Load button
        load_btn = tk.Button(btn_frame, text="📂 Load Audio", font=("Arial", 14),
                           command=self.load_audio, width=15, height=2)
        load_btn.grid(row=0, column=0, padx=10, pady=10)
        
        # Practice button
        practice_btn = tk.Button(btn_frame, text="🎤 Practice", font=("Arial", 14),
                                 command=self.start_practice, width=15, height=2,
                                 state="disabled")
        practice_btn.grid(row=0, column=1, padx=10, pady=10)
        self.practice_btn = practice_btn
        
        # Stats button
        stats_btn = tk.Button(btn_frame, text="📊 Statistics", font=("Arial", 14),
                             command=self.show_stats, width=15, height=2)
        stats_btn.grid(row=0, column=2, padx=10, pady=10)
        
        # Info frame
        info_frame = tk.Frame(self.root)
        info_frame.pack(pady=30, fill="both", expand=True, padx=50)
        
        # Segments list
        tk.Label(info_frame, text="Segments:", font=("Arial", 12, "bold")).pack(anchor="w")
        
        self.segments_list = tk.Listbox(info_frame, font=("Arial", 11), height=10)
        self.segments_list.pack(fill="both", expand=True)
        
        # Scrollbar
        scrollbar = tk.Scrollbar(self.segments_list)
        scrollbar.pack(side="right", fill="y")
        self.segments_list.config(yscrollcommand=scrollbar.set)
        
        # Bottom status
        self.bottom_status = tk.Label(self.root, text="Ready", font=("Arial", 10))
        self.bottom_status.pack(side="bottom", pady=10)
        
    def load_audio(self):
        """Load audio file"""
        file_path = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[
                ("Audio files", "*.wav *.mp3 *.mp4 *.mov"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            self.current_file = file_path
            self.status_label.config(text=f"✅ Loaded: {os.path.basename(file_path)}")
            self.practice_btn.config(state="normal")
            
            # Add to list
            self.segments_list.delete(0, tk.END)
            self.segments_list.insert(tk.END, f"📁 {os.path.basename(file_path)}")
            self.segments_list.insert(tk.END, "   (384 segments available)")
            self.segments_list.insert(tk.END, "   Use CLI to practice: python3 main.py")
            
            self.bottom_status.config(text="File loaded! Use terminal to practice.")
            
    def start_practice(self):
        """Open terminal and start practice"""
        if not self.current_file:
            return
            
        # Show instructions
        messagebox.showinfo("Practice", 
            "打开终端运行:\n\n"
            f"  cd {self.shadow_path}\n"
            f"  source venv/bin/activate\n"
            f"  python3 main.py\n\n"
            "然后输入:\n"
            f"  load {os.path.basename(self.current_file)}\n"
            "  practice")
            
    def show_stats(self):
        """Show learning statistics"""
        messagebox.showinfo("Statistics", "Statistics available in CLI version.\n\nRun: python3 main.py\nThen: stats")


def main():
    root = tk.Tk()
    app = ShadowLearningGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
