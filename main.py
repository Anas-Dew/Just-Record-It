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

class SelfViewWindow:
    def __init__(self):
        self.window = None
        self.cap = None
        self.is_running = False
        self.canvas = None
        
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
        
        # Initialize camera
        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            self.is_running = True
            self.update_video()
        else:
            messagebox.showerror("Error", "Could not access camera")
    
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
        self.root.title("Screen Recorder")
        self.root.geometry("400x300")
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
        
        # Self view window
        self.self_view = SelfViewWindow()
        
        # Create output folder
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Screen Recorder", 
                               font=("Arial", 18, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Record button
        self.record_btn = ttk.Button(main_frame, text="Start Recording", 
                                   command=self.toggle_recording,
                                   style="Accent.TButton")
        self.record_btn.grid(row=1, column=0, columnspan=2, pady=10, sticky=tk.EW)
        
        # See recordings button
        recordings_btn = ttk.Button(main_frame, text="See Recordings", 
                                  command=self.open_recordings_folder)
        recordings_btn.grid(row=2, column=0, columnspan=2, pady=5, sticky=tk.EW)
        
        # Self view toggle
        self.self_view_var = tk.BooleanVar()
        self_view_check = ttk.Checkbutton(main_frame, text="Self View", 
                                        variable=self.self_view_var,
                                        command=self.toggle_self_view)
        self_view_check.grid(row=3, column=0, columnspan=2, pady=10)
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Ready to record", 
                                    font=("Arial", 10))
        self.status_label.grid(row=4, column=0, columnspan=2, pady=20)
        
        # Recording info
        self.info_label = ttk.Label(main_frame, text="", 
                                   font=("Arial", 8), foreground="gray")
        self.info_label.grid(row=5, column=0, columnspan=2, pady=5)
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
    
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
                            # Draw cursor as a small circle
                            cv2.circle(frame, (cursor_x, cursor_y), 8, (255, 255, 255), 2)  # White circle
                            cv2.circle(frame, (cursor_x, cursor_y), 6, (0, 0, 0), 2)        # Black inner circle
                            cv2.circle(frame, (cursor_x, cursor_y), 2, (255, 255, 255), -1) # White center dot
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
            
            # Open audio stream
            stream = audio.open(format=self.audio_format,
                              channels=self.audio_channels,
                              rate=self.audio_rate,
                              input=True,
                              frames_per_buffer=self.audio_chunk)
            
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
            self.self_view.create_window()
        else:
            self.self_view.close_window()
    
    def on_closing(self):
        # Clean up
        self.is_recording = False
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
