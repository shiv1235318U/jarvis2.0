import os
import datetime
import webbrowser
import subprocess
import json
import requests
import pyttsx3
import speech_recognition as sr
import threading
import time
import psutil
import platform
import random
import tempfile
import urllib.parse

# ====== CONFIGURATION ======
OPENROUTER_API_KEY = "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"
CONFIG_FILE = "jarvis_config.json"

DEFAULT_CONFIG = {
    "version": "2.0",
    "assistant": {
        "call_name": "jarvis",
        "speak_mode": True,
        "listen_mode": False,
        "voice_rate": 180,
        "voice_volume": 0.8
    },
    "user": {
        "name": "User"
    },
    "ai": {
        "model": "deepseek/deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 2000
    }
}
# ===========================

class ConfigManager:
    """Handles configuration loading and saving"""
    
    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.config = None
        self.load_config()
    
    def load_config(self):
        """Load configuration from file or create default"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                print(f"✅ Config loaded from {self.config_file}")
            else:
                self.create_default_config()
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default configuration file"""
        try:
            self.config = DEFAULT_CONFIG.copy()
            self.save_config()
            print(f"✅ Default config created at {self.config_file}")
        except Exception as e:
            print(f"❌ Error creating default config: {e}")
            self.config = DEFAULT_CONFIG
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            return False
    
    def get(self, key_path, default=None):
        """Get configuration value using dot notation"""
        try:
            keys = key_path.split('.')
            value = self.config
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key_path, value):
        """Set configuration value using dot notation"""
        try:
            keys = key_path.split('.')
            config_ptr = self.config
            
            for key in keys[:-1]:
                if key not in config_ptr:
                    config_ptr[key] = {}
                config_ptr = config_ptr[key]
            
            config_ptr[keys[-1]] = value
            return True
        except Exception as e:
            print(f"❌ Error setting config value: {e}")
            return False

class JARVIS:
    def __init__(self):
        # Verify API key first
        if not self.verify_api_key():
            raise Exception("API key verification failed")
        
        # Initialize config manager
        self.config_manager = ConfigManager()
        
        # Initialize components using config
        self.call_name = self.config_manager.get('assistant.call_name', 'jarvis')
        self.speak_mode = self.config_manager.get('assistant.speak_mode', True)
        self.listen_mode = False  # Start with text mode to avoid microphone issues
        self.user_name = self.config_manager.get('user.name', 'User')
        self.model = self.config_manager.get('ai.model', 'deepseek/deepseek-chat')
        
        # Speech recognition
        self.recognizer = sr.Recognizer()
        self.microphone = None
        
        self.command_history = []
        self.is_running = True
        
        # Greeting messages
        self.greetings = [
            "Hello! I'm ready to assist you.",
            "Hi there! How can I help you today?",
            "Greetings! I'm here and listening.",
            "Hello! What can I do for you?",
            "Hi! Ready to help with your tasks."
        ]
        
        print("🚀 JARVIS initialized successfully!")
        print("💡 TTS will be initialized when needed")

    def verify_api_key(self):
        """Verify the API key is valid"""
        if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your-api-key-here":
            print("❌ API Key not configured!")
            return False
        
        if not OPENROUTER_API_KEY.startswith("sk-or-v1-"):
            print("❌ Invalid API Key format!")
            return False
        
        print("✅ API Key verified successfully!")
        return True

    def speak(self, text: str):
        """Text-to-speech with fresh engine each time to avoid errors"""
        if not text or not self.speak_mode:
            return
            
        try:
            # Create fresh engine instance each time
            engine = pyttsx3.init()
            
            # Set properties
            engine.setProperty('rate', self.config_manager.get('assistant.voice_rate', 180))
            engine.setProperty('volume', self.config_manager.get('assistant.voice_volume', 0.8))
            
            # Speak
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            
        except Exception as e:
            print(f"❌ TTS Error: {e}")

    def print_response(self, text: str, message_type: str = "info"):
        """Print and optionally speak response"""
        icons = {
            "info": "🤖",
            "error": "❌",
            "success": "✅",
            "warning": "⚠️",
            "thinking": "🤔"
        }
        icon = icons.get(message_type, "🤖")
        
        print(f"\n{icon} {self.call_name.upper()}: {text}\n")
        self.speak(text)

    def ask_openrouter(self, prompt: str, max_tokens: int = 500) -> str:
        """Make API call to OpenRouter"""
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jarvis-ai",
            "X-Title": "JARVIS AI Assistant"
        }
        
        system_message = f"""You are JARVIS, an advanced AI assistant. 
Current User: {self.user_name}
Current Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Assistant Name: {self.call_name}
Be helpful, concise, and slightly witty when appropriate."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": self.config_manager.get('ai.temperature', 0.7)
        }

        try:
            self.print_response("Thinking...", "thinking")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                return f"API Error: {data['error'].get('message', 'Unknown error')}"
            
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"].strip()
            else:
                return "I couldn't generate a response. Please try again."
                
        except requests.exceptions.Timeout:
            return "Request timeout. Please try again."
        except requests.exceptions.RequestException as e:
            return f"Connection error: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    def generate_code(self, request: str) -> str:
        """Generate code based on user request"""
        prompt = f"""Please generate complete, working code based on this request: {request}

Requirements:
1. Provide the complete code without placeholders
2. Include proper file extension in code blocks
3. Make sure the code is functional and well-commented
4. If it's a web project, include HTML, CSS, and JavaScript as needed
5. If it's a Python script, make it executable
6. Include any necessary setup instructions

Please format your response with clear code blocks showing the file type."""

        return self.ask_openrouter(prompt, max_tokens=2000)

    def save_and_open_code(self, code_content: str, filename: str = None):
        """Save generated code to a file and open it"""
        try:
            # Extract code from response and determine file type
            if "```" in code_content:
                # Extract code from markdown code blocks
                lines = code_content.split('\n')
                code_lines = []
                in_code_block = False
                
                for line in lines:
                    if line.strip().startswith('```'):
                        if in_code_block:
                            break
                        in_code_block = True
                        # Check for language specification
                        if '```' in line and len(line.strip()) > 3:
                            lang = line.strip()[3:].strip()
                            if lang and not filename:
                                if lang == 'python':
                                    filename = 'generated_code.py'
                                elif lang == 'html':
                                    filename = 'generated_code.html'
                                elif lang == 'javascript':
                                    filename = 'generated_code.js'
                                elif lang == 'css':
                                    filename = 'generated_code.css'
                        continue
                    if in_code_block:
                        code_lines.append(line)
                
                if code_lines:
                    code_content = '\n'.join(code_lines)
            
            # Determine filename if not provided
            if not filename:
                if '<html' in code_content.lower() or '<!doctype' in code_content.lower():
                    filename = 'generated_webpage.html'
                elif 'def ' in code_content or 'import ' in code_content:
                    filename = 'generated_script.py'
                elif 'function' in code_content or 'const ' in code_content or 'let ' in code_content:
                    filename = 'generated_script.js'
                else:
                    filename = 'generated_code.txt'
            
            # Create file on desktop
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.exists(desktop_path):
                desktop_path = tempfile.gettempdir()
            
            file_path = os.path.join(desktop_path, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code_content)
            
            # Open the file with appropriate application
            if filename.endswith('.html'):
                webbrowser.open(f'file://{file_path}')
                self.print_response(f"✅ HTML file created and opened in browser: {filename}")
            elif filename.endswith('.py'):
                subprocess.Popen(['notepad.exe', file_path])
                self.print_response(f"✅ Python script created and opened: {filename}")
            elif filename.endswith('.js'):
                subprocess.Popen(['notepad.exe', file_path])
                self.print_response(f"✅ JavaScript file created and opened: {filename}")
            else:
                subprocess.Popen(['notepad.exe', file_path])
                self.print_response(f"✅ Code file created and opened: {filename}")
            
            return file_path
            
        except Exception as e:
            self.print_response(f"❌ Error saving code: {e}", "error")
            return None

    def search_youtube(self, query: str):
        """Search YouTube for a query"""
        try:
            encoded_query = urllib.parse.quote_plus(query)
            youtube_url = f"https://www.youtube.com/results?search_query={encoded_query}"
            
            self.print_response(f"Searching YouTube for: {query}")
            webbrowser.open(youtube_url)
            return True
        except Exception as e:
            self.print_response(f"Failed to search YouTube: {e}", "error")
            return False

    def search_google(self, query: str):
        """Search Google for a query"""
        try:
            encoded_query = urllib.parse.quote_plus(query)
            google_url = f"https://www.google.com/search?q={encoded_query}"
            
            self.print_response(f"Searching Google for: {query}")
            webbrowser.open(google_url)
            return True
        except Exception as e:
            self.print_response(f"Failed to search Google: {e}", "error")
            return False

    def create_file_with_content(self, filename: str, content: str):
        """Create a file with given content and open it"""
        try:
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if os.path.exists(desktop_path):
                file_path = os.path.join(desktop_path, filename)
            else:
                temp_dir = tempfile.gettempdir()
                file_path = os.path.join(temp_dir, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            if filename.endswith('.txt'):
                subprocess.Popen(['notepad.exe', file_path])
            elif filename.endswith('.docx'):
                try:
                    subprocess.Popen(['winword.exe', file_path])
                except:
                    subprocess.Popen(['notepad.exe', file_path])
            else:
                subprocess.Popen(['notepad.exe', file_path])
            
            return file_path
        except Exception as e:
            print(f"❌ File creation error: {e}")
            return None

    def get_system_info(self) -> str:
        """Get comprehensive system information"""
        try:
            system = platform.system()
            processor = platform.processor()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            
            info = [
                f"💻 System: {system} {platform.release()}",
                f"⚡ Processor: {processor}",
                f"🧠 Memory: {memory.percent}% used ({memory.used//(1024**3)}GB/{memory.total//(1024**3)}GB)",
                f"💾 Disk: {disk.percent}% used ({disk.used//(1024**3)}GB/{disk.total//(1024**3)}GB)",
                f"🔧 CPU Usage: {psutil.cpu_percent()}%",
                f"⏰ System Uptime: {datetime.datetime.now() - boot_time}",
                f"👤 User: {self.user_name}",
                f"🤖 Assistant: {self.call_name}",
                f"🧠 AI Model: {self.model}"
            ]
            return "\n".join(info)
        except Exception as e:
            return f"Could not retrieve system info: {e}"

    def find_application(self, app_name: str) -> str:
        """Find application executable"""
        app_mappings = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "paint": "mspaint.exe",
            "chrome": "chrome.exe",
            "word": "winword.exe",
            "excel": "excel.exe"
        }
        
        if app_name in app_mappings:
            return app_mappings[app_name]
        
        return ""

    def setup_microphone(self):
        """Setup microphone only when needed for speech mode"""
        try:
            if self.microphone is None:
                self.microphone = sr.Microphone()
            
            print("🔧 Quick microphone setup...")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            return True
        except Exception as e:
            print(f"❌ Microphone setup failed: {e}")
            return False

    def listen_for_speech(self) -> str:
        """Listen for speech input"""
        if not self.setup_microphone():
            self.print_response("Microphone not available. Switching to text mode.", "warning")
            self.listen_mode = False
            return ""
            
        try:
            print("🎤 Listening... (Speak now)")
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
            
            text = self.recognizer.recognize_google(audio)
            print(f"🗣️  You said: {text}")
            return text.lower()
            
        except sr.WaitTimeoutError:
            print("⏰ No speech detected")
            return ""
        except sr.UnknownValueError:
            print("❌ Could not understand audio")
            return ""
        except sr.RequestError as e:
            print(f"🌐 Speech recognition error: {e}")
            return ""
        except Exception as e:
            print(f"❌ Microphone error: {e}")
            self.listen_mode = False
            return ""

    def get_user_input(self) -> str:
        """Get input from user via speech or text"""
        if self.listen_mode:
            speech_input = self.listen_for_speech()
            if speech_input:
                return speech_input
            else:
                print("🔄 Switching to text input...")
                self.listen_mode = False
        
        try:
            return input("👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def show_help(self):
        """Show comprehensive help message"""
        help_text = f"""
🤖 JARVIS AI ASSISTANT - COMMAND HELP

👋 BASIC COMMANDS:
  hello, hi, hey - Greet JARVIS
  time - Current time
  date - Current date
  system info - System information
  who are you - About JARVIS
  status - Show current status

💻 CODE GENERATION (NEW!):
  code [description] - Generate any code
  Examples:
    code a calculator in HTML
    code a python script to download videos
    code a weather app in javascript
    code a todo list web app

🌐 WEB & SEARCH COMMANDS:
  open youtube - Open YouTube homepage
  open google - Open Google homepage
  open instagram - Open Instagram
  search youtube [query] - Search YouTube
  search google [query] - Search Google
  open [website] - Open any website

📝 DOCUMENT COMMANDS:
  launch [app] - Launch applications
  write [document] - Create and write documents
  Examples: 
    launch notepad
    write a sick leave letter
    write a resume

⚙️ VOICE COMMANDS:
  speak on - Enable text-to-speech
  speak off - Disable text-to-speech
  test voice - Test speech system
  switch to speech mode - Use voice input
  switch to text mode - Use typing input

🔧 SYSTEM:
  exit, quit, bye - Close JARVIS

💬 AI CHAT:
  Ask anything else!

📝 Current Settings:
  Name: {self.call_name}
  Voice: {'🔊 ON' if self.speak_mode else '🔇 OFF'}
  Input: {'🎤 SPEECH' if self.listen_mode else '⌨️ TEXT'}
  User: {self.user_name}
  Model: {self.model}
"""
        print(help_text)

    def show_app_list(self):
        """Show available applications"""
        common_apps = [
            "notepad - Notepad",
            "calculator - Calculator",
            "paint - Microsoft Paint",
            "chrome - Google Chrome",
            "word - Microsoft Word",
            "excel - Microsoft Excel"
        ]
        
        app_list = "Available applications:\n" + "\n".join(f"  • {app}" for app in common_apps)
        self.print_response(app_list)

    def execute_command(self, command: str):
        """Execute commands with better parsing"""
        cmd = command.strip().lower()
        
        # Add to command history
        self.command_history.append(cmd)
        if len(self.command_history) > 50:
            self.command_history.pop(0)

        if not cmd:
            return

        # 💻 CODE GENERATION (NEW FEATURE)
        elif cmd.startswith("code "):
            code_request = cmd[5:].strip()
            if code_request:
                self.print_response(f"🖥️ Generating code for: {code_request}")
                code_content = self.generate_code(code_request)
                
                # Display the code first
                print("\n" + "="*60)
                print("🖥️ GENERATED CODE:")
                print("="*60)
                print(code_content)
                print("="*60)
                
                # Ask if user wants to save the code
                print("\n💾 Would you like to save this code to a file? (yes/no)")
                save_choice = input("👤 You: ").strip().lower()
                
                if save_choice in ['yes', 'y', 'save']:
                    file_path = self.save_and_open_code(code_content)
                    if file_path:
                        self.speak(f"I've generated and saved your {code_request} code!")
                    else:
                        self.print_response("Failed to save the code file.", "error")
                else:
                    self.print_response("Code generated and displayed above!")
            else:
                self.print_response("Please specify what code you want me to generate.", "warning")
        
        # 🔊 SPEECH CONTROL
        elif any(phrase in cmd for phrase in ["speak on", "start speaking", "speak up"]):
            self.speak_mode = True
            self.config_manager.set('assistant.speak_mode', True)
            self.print_response("🔊 Speech enabled! I will now speak responses.")
            self.speak("Voice activated! I can now speak to you.")
        
        elif any(phrase in cmd for phrase in ["speak off", "stop speaking", "be quiet", "shut up"]):
            self.speak_mode = False
            self.config_manager.set('assistant.speak_mode', False)
            self.print_response("🔇 Speech disabled. I will only show text responses.")
        
        elif "test voice" in cmd:
            self.print_response("Testing voice system...")
            self.speak("Hello! This is a voice test. My speech system is working perfectly!")
        
        # 🎤 INPUT MODE CONTROL
        elif any(phrase in cmd for phrase in ["switch to speech mode", "voice mode", "speech mode"]):
            self.listen_mode = True
            self.config_manager.set('assistant.listen_mode', True)
            self.print_response("🎤 Speech mode activated! I'm listening...")
        
        elif any(phrase in cmd for phrase in ["switch to text mode", "text mode"]):
            self.listen_mode = False
            self.config_manager.set('assistant.listen_mode', False)
            self.print_response("⌨️ Text mode activated! You can type now.")
        
        # 🔍 YOUTUBE SEARCH
        elif cmd.startswith("search youtube "):
            search_query = cmd[15:].strip()
            if search_query:
                self.search_youtube(search_query)
            else:
                self.print_response("Please specify what you want to search on YouTube.", "warning")
        
        elif cmd.startswith("youtube search "):
            search_query = cmd[15:].strip()
            if search_query:
                self.search_youtube(search_query)
            else:
                self.print_response("Please specify what you want to search on YouTube.", "warning")
        
        # 🔍 GOOGLE SEARCH
        elif cmd.startswith("search google "):
            search_query = cmd[14:].strip()
            if search_query:
                self.search_google(search_query)
            else:
                self.print_response("Please specify what you want to search on Google.", "warning")
        
        elif cmd.startswith("google search "):
            search_query = cmd[14:].strip()
            if search_query:
                self.search_google(search_query)
            else:
                self.print_response("Please specify what you want to search on Google.", "warning")
        
        # 📝 WRITE DOCUMENTS
        elif cmd.startswith("write "):
            document_request = cmd[6:].strip()
            self.print_response(f"Creating document: {document_request}")
            
            prompt = f"Please write a {document_request}. Make it professional and ready to use."
            content = self.ask_openrouter(prompt)
            
            filename = f"{document_request.replace(' ', '_')}.txt"
            file_path = self.create_file_with_content(filename, content)
            
            if file_path:
                self.print_response(f"✅ Document created and opened: {filename}")
                self.speak(f"I've created your {document_request} and opened it in notepad.")
            else:
                self.print_response("❌ Failed to create document", "error")
        
        # 💻 LAUNCH APPLICATIONS
        elif cmd.startswith("launch "):
            app_part = cmd[7:].strip()
            if " and " in app_part:
                app_name = app_part.split(" and ")[0].strip()
            else:
                app_name = app_part
            
            path = self.find_application(app_name)
            if path:
                try:
                    subprocess.Popen(path)
                    self.print_response(f"🚀 Launching {app_name}")
                    
                    if " and " in app_part:
                        additional_request = app_part.split(" and ")[1].strip()
                        self.print_response(f"Now handling: {additional_request}")
                        
                except Exception as e:
                    self.print_response(f"Failed to launch {app_name}: {e}", "error")
            else:
                self.print_response(f"Could not find {app_name}. Try 'list apps' to see available applications.", "warning")
        
        # 👋 GREETINGS
        elif any(word in cmd for word in ["hello", "hi", "hey"]):
            greeting = random.choice(self.greetings)
            self.print_response(greeting)
        
        # 🕒 TIME AND DATE
        elif "time" in cmd and "youtube" not in cmd:
            current_time = datetime.datetime.now().strftime("%I:%M %p")
            self.print_response(f"The current time is {current_time}")
        
        elif "date" in cmd:
            current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
            self.print_response(f"Today is {current_date}")
        
        # 💻 SYSTEM INFORMATION
        elif "system info" in cmd or "system information" in cmd:
            info = self.get_system_info()
            self.print_response(f"System Information:\n{info}")
        
        elif "who are you" in cmd:
            self.print_response(f"I am {self.call_name}, your AI assistant using {self.model}! I can help you with tasks, information, and controlling your computer.")

        elif "status" in cmd:
            status_info = f"""
🔍 JARVIS STATUS:
🤖 Name: {self.call_name}
👤 User: {self.user_name}
🔊 Voice: {'ENABLED' if self.speak_mode else 'DISABLED'}
🎤 Input: {'SPEECH' if self.listen_mode else 'TEXT'}
🧠 Model: {self.model}
💾 Commands History: {len(self.command_history)}
⏰ Uptime: {datetime.datetime.now().strftime('%H:%M:%S')}
"""
            self.print_response(status_info)

        # 🌐 WEB BROWSING
        elif "open youtube" in cmd:
            if "open youtube and search" in cmd:
                search_query = cmd.split("search")[1].strip()
                if search_query:
                    self.search_youtube(search_query)
                else:
                    self.print_response("Opening YouTube homepage")
                    webbrowser.open("https://www.youtube.com")
            else:
                self.print_response("Opening YouTube homepage")
                webbrowser.open("https://www.youtube.com")
        
        elif "open google" in cmd:
            if "open google and search" in cmd:
                search_query = cmd.split("search")[1].strip()
                if search_query:
                    self.search_google(search_query)
                else:
                    self.print_response("Opening Google homepage")
                    webbrowser.open("https://www.google.com")
            else:
                self.print_response("Opening Google homepage")
                webbrowser.open("https://www.google.com")
        
        elif "open instagram" in cmd:
            self.print_response("Opening Instagram")
            webbrowser.open("https://www.instagram.com")
        
        elif cmd.startswith("open "):
            site = cmd[5:].strip()
            if "." in site:
                url = f"https://{site}" if not site.startswith(("http://", "https://")) else site
                self.print_response(f"Opening {site}")
                webbrowser.open(url)
            else:
                self.print_response("Please specify a valid website (e.g., 'open github.com')")

        elif "list apps" in cmd:
            self.show_app_list()

        elif "help" in cmd:
            self.show_help()

        # 💬 AI CHAT (fallback)
        else:
            response = self.ask_openrouter(cmd)
            self.print_response(response)

        # Auto-save config
        if self.config_manager.get('system.auto_save', True):
            self.config_manager.save_config()

    def quick_setup(self):
        """Quick setup"""
        print("\n" + "="*50)
        print("🤖 JARVIS QUICK START")
        print("="*50)
        
        print(f"👤 User: {self.user_name}")
        print(f"🤖 Assistant: {self.call_name}")
        print(f"🔊 Voice: {'ENABLED' if self.speak_mode else 'DISABLED'}")
        print(f"🧠 AI Model: {self.model}")
        print("\n✅ Ready! Type 'help' for commands.")

    def run(self):
        """Main application loop"""
        self.quick_setup()
        
        welcome_msg = f"""
🚀 JARVIS ACTIVATED!
👋 Hello {self.user_name}! I'm {self.call_name}, your AI assistant.
💡 Type 'help' to see all available commands.
🔊 Voice: {'ENABLED' if self.speak_mode else 'DISABLED'}
🎤 Speech Input: {'ENABLED (say switch to text mode)' if self.listen_mode else 'DISABLED (type switch to speech mode)'}
🧠 AI Model: {self.model} (DeepSeek)
"""
        print(welcome_msg)
        self.print_response("Systems online and ready! How can I assist you today?")

        while self.is_running:
            try:
                user_input = self.get_user_input()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ["exit", "quit", "bye", "goodbye"]:
                    self.print_response(f"Goodbye {self.user_name}! It was a pleasure assisting you.")
                    self.config_manager.save_config()
                    break
                
                self.execute_command(user_input)
                
            except KeyboardInterrupt:
                self.print_response("Interrupted. Type 'exit' to quit properly.")
            except Exception as e:
                self.print_response(f"An error occurred: {e}", "error")

def main():
    """Initialize and run JARVIS"""
    print("🚀 Initializing JARVIS AI Assistant...")
    
    try:
        jarvis = JARVIS()
        jarvis.run()
    except Exception as e:
        print(f"❌ Failed to initialize JARVIS: {e}")
        print("\n💡 Make sure you have installed:")
        print("pip install pyttsx3 speechrecognition requests psutil")

if __name__ == "__main__":
    main()