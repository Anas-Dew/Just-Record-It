import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
import numpy as np
import threading
import time
import os
import subprocess
import sys
from datetime import datetime
import mss
import pyautogui
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import pyaudio
import wave
from moviepy.editor import VideoFileClip, AudioFileClip
import math

class SelfViewWindow:
    def __init__(self, parent):
        self.window = None
        self.cap = None
        self.is_running = False
        self.canvas = None
        self.parent = parent  # Reference to main app for getting selected camera
        
    def create_window(self):
        if self.window:
            return
            
        self.window = tk.Toplevel()
        self.window.title("Self View")
        self.window.geometry("200x200")  # Make it square for perfect circle
        self.window.attributes('-topmost', True)
        self.window.attributes('-transparentcolor', 'black')  # Make black transparent
        self.window.overrideredirect(True)  # Remove window decorations
        
        # Make window draggable
        self.window.bind('<Button-1>', self.start_drag)
        self.window.bind('<B1-Motion>', self.on_drag)
        
        # Create canvas for video with transparent background
        self.canvas = tk.Canvas(self.window, width=200, height=200, bg='black', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind('<Button-1>', self.start_drag)
        self.canvas.bind('<B1-Motion>', self.on_drag)
        
        # Create circular mask
        self.circle_mask = None
        
        # Initialize camera with selected device
        camera_index = self.parent.get_selected_camera_index()
        self.cap = cv2.VideoCapture(camera_index)
        if self.cap.isOpened():
            self.is_running = True
            self.update_video()
        else:
            messagebox.showerror("Error", f"Could not access camera at index {camera_index}")
    
    def start_drag(self, event):
        self.x = event.x
        self.y = event.y
    
    def on_drag(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.window.winfo_x() + deltax
        y = self.window.winfo_y() + deltay
        self.window.geometry(f"+{x}+{y}")
    
    def update_video(self):
        if self.is_running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                # Flip frame horizontally for mirror effect
                frame = cv2.flip(frame, 1)
                
                # Apply bilateral filter to reduce noise while preserving edges
                frame = cv2.bilateralFilter(frame, 9, 75, 75)
                
                # Additional noise reduction for dark areas
                # Convert to grayscale temporarily to identify dark areas
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Create mask for dark areas (where noise is most visible)
                dark_mask = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)[1]
                
                # Apply stronger blur only to dark areas
                blurred_frame = cv2.GaussianBlur(frame, (5, 5), 0)
                
                # Use numpy to blend original and blurred frame based on dark mask
                dark_mask_3ch = cv2.cvtColor(dark_mask, cv2.COLOR_GRAY2BGR) / 255.0
                frame = frame * (1 - dark_mask_3ch * 0.7) + blurred_frame * (dark_mask_3ch * 0.7)
                frame = frame.astype(np.uint8)
                
                # Get original dimensions
                height, width = frame.shape[:2]
                
                # Calculate square crop dimensions (center crop)
                if width > height:
                    # Wider than tall - crop sides
                    crop_size = height
                    start_x = (width - crop_size) // 2
                    start_y = 0
                    frame = frame[start_y:start_y + crop_size, start_x:start_x + crop_size]
                elif height > width:
                    # Taller than wide - crop top/bottom
                    crop_size = width
                    start_x = 0
                    start_y = (height - crop_size) // 2
                    frame = frame[start_y:start_y + crop_size, start_x:start_x + crop_size]
                # If already square, no cropping needed
                
                # Use better interpolation for resizing to reduce artifacts
                frame = cv2.resize(frame, (200, 200), interpolation=cv2.INTER_AREA)
                
                # Convert BGR to RGB first
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Convert to PIL Image
                img = Image.fromarray(frame_rgb)
                
                # Create a circular image with transparent background
                img = img.convert("RGBA")
                
                # Create circular mask with anti-aliasing
                size = img.size
                mask = Image.new('L', size, 0)
                draw = ImageDraw.Draw(mask)
                
                # Draw circle with slight inset to avoid edge artifacts
                margin = 1
                draw.ellipse([margin, margin, size[0]-margin, size[1]-margin], fill=255)
                
                # Apply the mask to create transparency outside the circle
                img.putalpha(mask)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Update canvas with better background handling
                if self.canvas:
                    self.canvas.delete("all")
                    self.canvas.create_image(100, 100, image=photo)
                    self.canvas.image = photo
            
            if self.window:
                self.window.after(30, self.update_video)
    
    def close_window(self):
        self.is_running = False
        if self.cap:
            self.cap.release()
        if self.window:
            self.window.destroy()
            self.window = None

class ScreenRecorder:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Just Record It")
        self.root.geometry("450x800")  # Increased height for better spacing
        self.root.resizable(False, False)
        
        # Recording variables
        self.is_recording = False
        self.output_folder = os.path.join(os.path.expanduser("~"), "Desktop", "recordings")
        self.current_filename = None
        self.audio_filename = None
        
        # Audio recording settings
        self.audio_format = pyaudio.paInt16
        self.audio_channels = 2
        self.audio_rate = 44100
        self.audio_chunk = 1024
        self.audio_frames = []
        self.audio_thread = None
        
        # Audio monitoring
        self.audio_monitor_active = False
        self.audio_monitor_thread = None
        self.current_audio_level = 0
        self.max_audio_level = 0
        
        # Camera preview
        self.preview_cap = None
        self.preview_active = False
        self.preview_canvas = None
        
        # Device lists
        self.audio_devices = []
        self.camera_devices = []
        
        # Self view window
        self.self_view = SelfViewWindow(self)
        
        # Load cursor image
        self.cursor_image = None
        self.load_cursor_image()
        
        # Create output folder
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)
        
        # Enumerate devices
        self.enumerate_devices()
        
        self.setup_ui()
        
        # Start audio monitoring and camera preview
        self.start_audio_monitoring()
        self.start_camera_preview()
    
    def load_cursor_image(self):
        """Load the cursor PNG image for overlay"""
        try:
            cursor_path = "cursor.png"
            if os.path.exists(cursor_path):
                # Load image with PIL to handle transparency
                pil_image = Image.open(cursor_path).convert("RGBA")
                
                # Resize cursor to appropriate size (24x24 pixels - typical cursor size)
                cursor_size = (40, 40)
                pil_image = pil_image.resize(cursor_size, Image.Resampling.LANCZOS)
                
                # Convert PIL image to OpenCV format
                self.cursor_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGBA2BGRA)
                print("Cursor image loaded successfully")
            else:
                print("Cursor image not found, will use default drawing")
                self.cursor_image = None
        except Exception as e:
            print(f"Error loading cursor image: {e}")
            self.cursor_image = None
    
    def overlay_cursor(self, frame, cursor_x, cursor_y):
        """Overlay cursor PNG image on the frame"""
        if self.cursor_image is None:
            # Fallback to drawing circles
            cv2.circle(frame, (cursor_x, cursor_y), 8, (255, 255, 255), 2)  # White circle
            cv2.circle(frame, (cursor_x, cursor_y), 6, (0, 0, 0), 2)        # Black inner circle
            cv2.circle(frame, (cursor_x, cursor_y), 2, (255, 255, 255), -1) # White center dot
            return
        
        cursor_h, cursor_w = self.cursor_image.shape[:2]
        
        # Calculate position to center cursor on click point (adjust for cursor hotspot)
        # Most cursors have their hotspot at the top-left, so we don't offset
        start_x = cursor_x
        start_y = cursor_y
        
        # Make sure cursor doesn't go out of bounds
        frame_h, frame_w = frame.shape[:2]
        
        # Calculate the region where cursor will be placed
        end_x = min(start_x + cursor_w, frame_w)
        end_y = min(start_y + cursor_h, frame_h)
        
        # Skip if cursor is completely outside frame
        if start_x >= frame_w or start_y >= frame_h or start_x < 0 or start_y < 0:
            return
        
        # Calculate how much of the cursor image to use
        cursor_end_x = cursor_w - max(0, (start_x + cursor_w) - frame_w)
        cursor_end_y = cursor_h - max(0, (start_y + cursor_h) - frame_h)
        cursor_start_x = max(0, -start_x)
        cursor_start_y = max(0, -start_y)
        
        # Adjust frame coordinates if cursor starts outside
        start_x = max(0, start_x)
        start_y = max(0, start_y)
        
        # Get the region of the frame where cursor will be placed
        frame_region = frame[start_y:end_y, start_x:end_x]
        cursor_region = self.cursor_image[cursor_start_y:cursor_end_y, cursor_start_x:cursor_end_x]
        
        if frame_region.shape[0] > 0 and frame_region.shape[1] > 0 and cursor_region.shape[0] > 0 and cursor_region.shape[1] > 0:
            # Extract alpha channel for blending
            alpha = cursor_region[:, :, 3] / 255.0
            alpha = np.expand_dims(alpha, axis=2)
            
            # Blend the cursor with the frame using alpha channel
            cursor_rgb = cursor_region[:, :, :3]  # BGR channels
            blended = frame_region * (1 - alpha) + cursor_rgb * alpha
            
            # Update the frame
            frame[start_y:end_y, start_x:end_x] = blended.astype(np.uint8)
    
    def enumerate_devices(self):
        """Enumerate available audio and video devices"""
        # Enumerate audio devices
        try:
            audio = pyaudio.PyAudio()
            self.audio_devices = []
            
            # Add system default first
            self.audio_devices.append({"name": "System Default", "index": None})
            
            for i in range(audio.get_device_count()):
                device_info = audio.get_device_info_by_index(i)
                # Filter for input devices using primary host API only to avoid duplicates
                if device_info['maxInputChannels'] > 0 and device_info['hostApi'] == 0:
                    self.audio_devices.append({
                        "name": device_info['name'],
                        "index": i
                    })
            audio.terminate()
        except Exception as e:
            print(f"Error enumerating audio devices: {e}")
            self.audio_devices = [{"name": "System Default", "index": None}]
        
        # Enumerate camera devices
        self.camera_devices = []
        self.camera_devices.append({"name": "System Default", "index": 0})
        
        # Test camera indices (usually 0-10 is enough)
        for i in range(1, 11):
            try:
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    # Try to read a frame to confirm it's working
                    ret, frame = cap.read()
                    if ret:
                        self.camera_devices.append({
                            "name": f"Camera {i}",
                            "index": i
                        })
                cap.release()
            except:
                continue
    
    def get_selected_audio_device_index(self):
        """Get the index of the selected audio device"""
        try:
            selection = self.audio_var.get()
            for device in self.audio_devices:
                if device["name"] == selection:
                    return device["index"]
        except:
            pass
        return None  # System default
    
    def get_selected_camera_index(self):
        """Get the index of the selected camera device"""
        try:
            selection = self.camera_var.get()
            for device in self.camera_devices:
                if device["name"] == selection:
                    return device["index"]
        except:
            pass
        return 0  # Default camera
    
    def on_camera_change(self, event=None):
        """Handle camera selection change"""
        # Only restart camera preview if self-view is not active
        if not self.self_view_var.get():
            self.restart_camera_preview()
        
        if self.self_view.window and self.self_view.is_running:
            # Restart self view with new camera
            self.self_view.close_window()
            time.sleep(0.1)  # Small delay
            self.self_view.create_window()
    
    def on_audio_change(self, event=None):
        """Handle audio device selection change"""
        # Restart audio monitoring with new device
        self.restart_audio_monitoring()
    
    def start_camera_preview(self):
        """Start camera preview"""
        if not self.preview_active and not self.self_view_var.get():  # Don't start if self-view is active
            self.preview_active = True
            camera_index = self.get_selected_camera_index()
            self.preview_cap = cv2.VideoCapture(camera_index)
            if self.preview_cap.isOpened():
                self.update_camera_preview()
    
    def stop_camera_preview(self):
        """Stop camera preview"""
        self.preview_active = False
        if self.preview_cap:
            self.preview_cap.release()
            self.preview_cap = None
        # Clear the preview canvas
        if self.preview_canvas:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(160, 120, text="Camera Preview Disabled\n(Self View Active)", 
                                          fill="white", font=("Arial", 12), justify=tk.CENTER)
    
    def restart_camera_preview(self):
        """Restart camera preview with new device"""
        self.stop_camera_preview()
        time.sleep(0.1)
        self.start_camera_preview()
    
    def update_camera_preview(self):
        """Update camera preview display"""
        if self.preview_active and self.preview_cap and self.preview_cap.isOpened() and self.preview_canvas:
            ret, frame = self.preview_cap.read()
            if ret:
                # Flip frame horizontally for mirror effect
                frame = cv2.flip(frame, 1)
                
                # Resize frame to fit preview (320x240)
                frame = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
                
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Convert to PIL Image
                img = Image.fromarray(frame_rgb)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Update canvas
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(160, 120, image=photo)
                self.preview_canvas.image = photo
            
            # Schedule next update
            if self.preview_active:
                self.root.after(30, self.update_camera_preview)
    
    def calculate_audio_level(self, audio_data):
        """Calculate audio level in decibels"""
        try:
            # Convert bytes to numpy array
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Calculate RMS (root mean square)
            if len(audio_array) > 0:
                rms = np.sqrt(np.mean(audio_array.astype(np.float64)**2))
                
                # Convert to decibels (with reference and minimum threshold)
                if rms > 0:
                    # Reference value for 16-bit audio
                    reference = 32767.0
                    db = 20 * math.log10(rms / reference)
                    # Clamp to reasonable range (-60 to 0 dB)
                    db = max(-60, min(0, db))
                    return db
            return -60  # Silence
        except Exception as e:
            print(f"Error calculating audio level: {e}")
            return -60
    
    def audio_monitor_worker(self):
        """Worker thread for monitoring audio levels"""
        audio = None
        stream = None
        
        try:
            audio = pyaudio.PyAudio()
            
            while self.audio_monitor_active:
                try:
                    # Get selected audio device
                    audio_device_index = self.get_selected_audio_device_index()
                    
                    # Setup stream parameters
                    stream_kwargs = {
                        'format': self.audio_format,
                        'channels': 1,  # Use mono for monitoring
                        'rate': self.audio_rate,
                        'input': True,
                        'frames_per_buffer': self.audio_chunk
                    }
                    
                    if audio_device_index is not None:
                        stream_kwargs['input_device_index'] = audio_device_index
                    
                    # Open stream
                    stream = audio.open(**stream_kwargs)
                    
                    # Monitor audio levels
                    while self.audio_monitor_active:
                        try:
                            data = stream.read(self.audio_chunk, exception_on_overflow=False)
                            level_db = self.calculate_audio_level(data)
                            
                            # Update current level
                            self.current_audio_level = level_db
                            
                            # Update max level (decays over time)
                            if level_db > self.max_audio_level:
                                self.max_audio_level = level_db
                            else:
                                # Decay max level slowly
                                self.max_audio_level = max(level_db, self.max_audio_level - 0.5)
                            
                            # Update UI on main thread
                            self.root.after_idle(self.update_audio_level_display)
                            
                        except Exception as e:
                            print(f"Audio monitoring error: {e}")
                            time.sleep(0.1)
                    
                    # Close stream
                    if stream:
                        stream.stop_stream()
                        stream.close()
                        stream = None
                        
                except Exception as e:
                    print(f"Audio stream error: {e}")
                    time.sleep(1)  # Wait before retry
                    
        except Exception as e:
            print(f"Audio monitoring initialization error: {e}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            if audio:
                try:
                    audio.terminate()
                except:
                    pass
    
    def start_audio_monitoring(self):
        """Start audio level monitoring"""
        if not self.audio_monitor_active:
            self.audio_monitor_active = True
            self.audio_monitor_thread = threading.Thread(target=self.audio_monitor_worker)
            self.audio_monitor_thread.daemon = True
            self.audio_monitor_thread.start()
    
    def stop_audio_monitoring(self):
        """Stop audio level monitoring"""
        self.audio_monitor_active = False
        if self.audio_monitor_thread:
            self.audio_monitor_thread.join(timeout=1)
    
    def restart_audio_monitoring(self):
        """Restart audio monitoring with new device"""
        self.stop_audio_monitoring()
        time.sleep(0.1)
        self.start_audio_monitoring()
    
    def update_audio_level_display(self):
        """Update the audio level display in the UI"""
        try:
            # Convert dB to percentage for progress bar (0% = -60dB, 100% = 0dB)
            percentage = max(0, min(100, (self.current_audio_level + 60) / 60 * 100))
            
            # Update progress bar (no color coding)
            self.audio_level_bar['value'] = percentage
            
            # Update label with current dB value
            self.audio_level_label.config(text=f"Audio Level: {self.current_audio_level:.1f} dB")
            
        except Exception as e:
            print(f"Error updating audio level display: {e}")
    
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Just Record It", 
                               font=("Arial", 18, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Device selection frame
        device_frame = ttk.LabelFrame(main_frame, text="Device Selection", padding="10")
        device_frame.grid(row=1, column=0, columnspan=2, pady=(0, 10), sticky=tk.EW)
        
        # Audio device selection
        ttk.Label(device_frame, text="Microphone:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.audio_var = tk.StringVar(value="System Default")
        self.audio_dropdown = ttk.Combobox(device_frame, textvariable=self.audio_var, 
                                     values=[device["name"] for device in self.audio_devices],
                                     state="readonly", width=30)
        self.audio_dropdown.grid(row=0, column=1, padx=(10, 0), pady=5, sticky=tk.EW)
        self.audio_dropdown.bind('<<ComboboxSelected>>', self.on_audio_change)
        
        # Camera device selection
        ttk.Label(device_frame, text="Camera:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.camera_var = tk.StringVar(value="System Default")
        self.camera_dropdown = ttk.Combobox(device_frame, textvariable=self.camera_var,
                                      values=[device["name"] for device in self.camera_devices],
                                      state="readonly", width=30)
        self.camera_dropdown.grid(row=1, column=1, padx=(10, 0), pady=5, sticky=tk.EW)
        self.camera_dropdown.bind('<<ComboboxSelected>>', self.on_camera_change)
        
        # Configure device frame grid
        device_frame.columnconfigure(1, weight=1)
        
        # Camera preview frame
        preview_frame = ttk.LabelFrame(main_frame, text="Camera Preview", padding="10")
        preview_frame.grid(row=2, column=0, columnspan=2, pady=(0, 10), sticky=tk.EW)
        
        # Camera preview canvas
        self.preview_canvas = tk.Canvas(preview_frame, width=320, height=240, bg='black')
        self.preview_canvas.grid(row=0, column=0, pady=5)
        
        # Configure preview frame grid
        preview_frame.columnconfigure(0, weight=1)
        
        # Audio level monitoring frame
        audio_frame = ttk.LabelFrame(main_frame, text="Audio Monitoring", padding="10")
        audio_frame.grid(row=3, column=0, columnspan=2, pady=(0, 10), sticky=tk.EW)
        
        # Audio level label
        self.audio_level_label = ttk.Label(audio_frame, text="Audio Level: -60.0 dB")
        self.audio_level_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        # Audio level progress bar (no color styles)
        self.audio_level_bar = ttk.Progressbar(audio_frame, length=300, mode='determinate')
        self.audio_level_bar.grid(row=1, column=0, sticky=tk.EW, pady=(0, 5))
        
        # dB scale labels
        scale_frame = ttk.Frame(audio_frame)
        scale_frame.grid(row=2, column=0, sticky=tk.EW)
        
        ttk.Label(scale_frame, text="-60dB", font=("Arial", 8)).pack(side=tk.LEFT)
        ttk.Label(scale_frame, text="-30dB", font=("Arial", 8)).pack(side=tk.LEFT, expand=True)
        ttk.Label(scale_frame, text="0dB", font=("Arial", 8)).pack(side=tk.RIGHT)
        
        # Configure audio frame grid
        audio_frame.columnconfigure(0, weight=1)
        
        # Record button
        self.record_btn = ttk.Button(main_frame, text="Start Recording", 
                                   command=self.toggle_recording,
                                   style="Accent.TButton")
        self.record_btn.grid(row=4, column=0, columnspan=2, pady=10, sticky=tk.EW)
        
        # See recordings button
        self.recordings_btn = ttk.Button(main_frame, text="See Recordings", 
                                  command=self.open_recordings_folder)
        self.recordings_btn.grid(row=5, column=0, columnspan=2, pady=5, sticky=tk.EW)
        
        # Self view toggle
        self.self_view_var = tk.BooleanVar()
        self.self_view_check = ttk.Checkbutton(main_frame, text="Self View", 
                                        variable=self.self_view_var,
                                        command=self.toggle_self_view)
        self.self_view_check.grid(row=6, column=0, columnspan=2, pady=10)
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Ready to record", 
                                    font=("Arial", 10))
        self.status_label.grid(row=7, column=0, columnspan=2, pady=20)
        
        # Recording info
        self.info_label = ttk.Label(main_frame, text="", 
                                   font=("Arial", 8), foreground="gray")
        self.info_label.grid(row=8, column=0, columnspan=2, pady=5)
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
    
    def set_ui_controls_enabled(self, enabled):
        """Enable or disable all UI controls"""
        state = "normal" if enabled else "disabled"
        readonly_state = "readonly" if enabled else "disabled"
        
        # Disable/enable buttons
        self.record_btn.config(state=state)
        self.recordings_btn.config(state=state)
        self.self_view_check.config(state=state)
        
        # Disable/enable dropdowns
        self.audio_dropdown.config(state=readonly_state)
        self.camera_dropdown.config(state=readonly_state)
    
    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        try:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_filename = os.path.join(self.output_folder, f"recording_{timestamp}.mp4")
            self.audio_filename = os.path.join(self.output_folder, f"audio_{timestamp}.wav")
            
            # Get screen dimensions
            screen_width, screen_height = pyautogui.size()
            
            # Clear previous audio frames
            self.audio_frames = []
            
            # Update UI
            self.is_recording = True
            self.record_btn.config(text="Stop Recording")
            self.status_label.config(text="Recording...")
            self.info_label.config(text=f"Output: {self.current_filename}")
            
            # Start audio recording in separate thread
            self.audio_thread = threading.Thread(target=self.record_audio)
            self.audio_thread.daemon = True
            self.audio_thread.start()
            
            # Start video recording in separate thread
            self.recording_thread = threading.Thread(target=self.record_screen)
            self.recording_thread.daemon = True
            self.recording_thread.start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start recording: {str(e)}")
            self.is_recording = False
    
    def record_screen(self):
        try:
            # Get screen dimensions
            screen_width, screen_height = pyautogui.size()
            
            # Define codec and create VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = 15.0  # Reduced FPS for more stable recording
            
            out = cv2.VideoWriter(self.current_filename, fourcc, fps, 
                                (screen_width, screen_height))
            
            # Create MSS instance for faster screen capture
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                
                # Track timing for consistent frame rate
                frame_time = 1.0 / fps
                last_time = time.time()
                
                while self.is_recording:
                    current_time = time.time()
                    
                    # Only capture if enough time has passed
                    if current_time - last_time >= frame_time:
                        # Capture screen
                        screenshot = sct.grab(monitor)
                        
                        # Convert to numpy array
                        frame = np.array(screenshot)
                        
                        # Convert BGRA to BGR
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                        
                        # Get cursor position and draw it on the frame
                        try:
                            cursor_x, cursor_y = pyautogui.position()
                            self.overlay_cursor(frame, cursor_x, cursor_y)
                        except:
                            pass  # Skip if cursor position can't be obtained
                        
                        # Write frame
                        out.write(frame)
                        
                        last_time = current_time
                    else:
                        # Small sleep to prevent excessive CPU usage
                        time.sleep(0.001)
            
            # Release video writer
            out.release()
            
            # Update UI on main thread
            self.root.after(0, self.recording_finished)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", 
                                                           f"Recording failed: {str(e)}"))
            self.root.after(0, self.recording_finished)
    
    def record_audio(self):
        try:
            # Initialize PyAudio
            audio = pyaudio.PyAudio()
            
            # Get selected audio device index
            audio_device_index = self.get_selected_audio_device_index()
            
            # Open audio stream with selected device
            stream_kwargs = {
                'format': self.audio_format,
                'channels': self.audio_channels,
                'rate': self.audio_rate,
                'input': True,
                'frames_per_buffer': self.audio_chunk
            }
            
            # Add input_device_index only if not None (system default)
            if audio_device_index is not None:
                stream_kwargs['input_device_index'] = audio_device_index
            
            stream = audio.open(**stream_kwargs)
            
            # Record audio frames
            while self.is_recording:
                data = stream.read(self.audio_chunk)
                self.audio_frames.append(data)
            
            # Stop and close stream
            stream.stop_stream()
            stream.close()
            audio.terminate()
            
            # Save audio to file
            with wave.open(self.audio_filename, 'wb') as wf:
                wf.setnchannels(self.audio_channels)
                wf.setsampwidth(audio.get_sample_size(self.audio_format))
                wf.setframerate(self.audio_rate)
                wf.writeframes(b''.join(self.audio_frames))
                
        except Exception as e:
            print(f"Audio recording error: {e}")
    
    def stop_recording(self):
        self.is_recording = False
    
    def recording_finished(self):
        self.record_btn.config(text="Start Recording")
        self.status_label.config(text="Processing...")
        
        # Disable all UI controls during processing
        self.set_ui_controls_enabled(False)
        
        # Combine audio and video in a separate thread
        combine_thread = threading.Thread(target=self.combine_audio_video)
        combine_thread.daemon = True
        combine_thread.start()
    
    def combine_audio_video(self):
        try:
            # Wait a moment for audio file to be fully written
            time.sleep(1)
            
            # Check if both files exist
            if os.path.exists(self.current_filename) and os.path.exists(self.audio_filename):
                # Load video and audio
                video_clip = VideoFileClip(self.current_filename)
                audio_clip = AudioFileClip(self.audio_filename)
                
                # Combine video with audio
                final_clip = video_clip.set_audio(audio_clip)
                
                # Generate final filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                final_filename = os.path.join(self.output_folder, f"final_recording_{timestamp}.mp4")
                
                # Write final video with audio
                final_clip.write_videofile(final_filename, codec='libx264', audio_codec='aac')
                
                # Clean up clips
                video_clip.close()
                audio_clip.close()
                final_clip.close()
                
                # Remove temporary files
                try:
                    os.remove(self.current_filename)  # Remove video-only file
                    os.remove(self.audio_filename)    # Remove audio-only file
                except:
                    pass
                
                # Update filename reference
                self.current_filename = final_filename
                
            # Update UI on main thread
            self.root.after(0, self.processing_finished)
            
        except Exception as e:
            print(f"Error combining audio and video: {e}")
            # Update UI even if combining failed
            self.root.after(0, self.processing_finished)
    
    def processing_finished(self):
        # Re-enable all UI controls after processing
        self.set_ui_controls_enabled(True)
        
        self.status_label.config(text="Recording saved!")
        
        # Show success message with option to open file
        result = messagebox.askyesno("Recording Complete", 
                                   f"Recording saved as:\n{self.current_filename}\n\nOpen recordings folder?")
        if result:
            self.open_recordings_folder()
        
        # Reset info label after 3 seconds
        self.root.after(3000, lambda: self.info_label.config(text=""))
        self.root.after(3000, lambda: self.status_label.config(text="Ready to record"))
    
    def open_recordings_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(self.output_folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", self.output_folder])
            else:
                subprocess.run(["xdg-open", self.output_folder])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {str(e)}")
    
    def toggle_self_view(self):
        if self.self_view_var.get():
            # Turn on self-view: stop camera preview
            self.stop_camera_preview()
            self.self_view.create_window()
        else:
            # Turn off self-view: restart camera preview
            self.self_view.close_window()
            self.start_camera_preview()
    
    def on_closing(self):
        # Clean up
        self.is_recording = False
        self.stop_audio_monitoring()  # Stop audio monitoring
        self.stop_camera_preview()    # Stop camera preview
        self.self_view.close_window()
        self.root.destroy()
    
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = ScreenRecorder()
        app.run()
    except Exception as e:
        print(f"Error starting application: {e}")
        messagebox.showerror("Error", f"Failed to start application: {str(e)}")
