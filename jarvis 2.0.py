import os
import datetime
import webbrowser
import subprocess
import json
import requests
import pyttsx3
import speech_recognition as sr
import time
import psutil
import platform
import random
import tempfile
import urllib.parse
import re
import serial
import serial.tools.list_ports
import threading

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
    },
    "arduino": {
        "enabled": False,
        "port": "COM3",
        "baud_rate": 9600
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

class ArduinoController:
    """Handles communication with Arduino Uno"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.serial_connection = None
        self.is_connected = False
        self.setup_arduino()
    
    def setup_arduino(self):
        """Setup connection to Arduino"""
        try:
            if not self.config_manager.get('arduino.enabled', False):
                print("ℹ️ Arduino control is disabled in config")
                return
            
            port = self.config_manager.get('arduino.port', 'COM3')
            baud_rate = self.config_manager.get('arduino.baud_rate', 9600)
            
            print(f"🔌 Attempting to connect to Arduino on {port}...")
            self.serial_connection = serial.Serial(port, baud_rate, timeout=2)
            time.sleep(2)  # Wait for Arduino to reset
            self.is_connected = True
            print("✅ Arduino connected successfully!")
            
        except Exception as e:
            print(f"❌ Failed to connect to Arduino: {e}")
            self.is_connected = False
    
    def list_available_ports(self):
        """List all available serial ports"""
        ports = serial.tools.list_ports.comports()
        available_ports = []
        for port in ports:
            available_ports.append({
                'device': port.device,
                'description': port.description,
                'hwid': port.hwid
            })
        return available_ports
    
    def send_command(self, command):
        """Send command to Arduino"""
        if not self.is_connected or not self.serial_connection:
            return False, "Arduino not connected"
        
        try:
            # Ensure command ends with newline
            if not command.endswith('\n'):
                command += '\n'
            
            self.serial_connection.write(command.encode())
            time.sleep(0.5)  # Wait for Arduino to process
            
            # Read response if available
            response = ""
            while self.serial_connection.in_waiting > 0:
                response += self.serial_connection.readline().decode().strip()
            
            return True, response if response else "Command sent successfully"
            
        except Exception as e:
            return False, f"Error sending command: {str(e)}"
    
    def light_on(self):
        """Send command to turn light ON"""
        return self.send_command("LIGHT_ON")
    
    def light_off(self):
        """Send command to turn light OFF"""
        return self.send_command("LIGHT_OFF")
    
    def close(self):
        """Close serial connection"""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.is_connected = False

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
        
        # Initialize Arduino controller
        self.arduino = ArduinoController(self.config_manager)
        
        # Speech recognition
        self.recognizer = sr.Recognizer()
        self.microphone = None
        
        # Interruption handling
        self.is_speaking = False
        self.current_speech_engine = None
        self.interruption_detected = False
        self.listening_thread = None
        self.stop_listening = False
        
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

    def filter_emoji_text(self, text: str) -> str:
        """Remove emojis and special characters from text for speech"""
        if not text:
            return text
            
        # Remove common emojis and special characters
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE)
        
        # Remove specific emoji characters
        filtered_text = emoji_pattern.sub('', text)
        
        # Remove other special characters that might be spoken
        special_chars = ['🔊', '🔇', '🎤', '⌨️', '🤖', '👤', '💡', '🚀', '💻', '🌐', 
                        '📱', '🔧', '⚡', '🧠', '💾', '📝', '🔍', '🐛', '📚', '✅', 
                        '❌', '⚠️', '🤔', '⏰', '🌙', '🔌', '📁', '🎯']
        
        for char in special_chars:
            filtered_text = filtered_text.replace(char, '')
        
        # Clean up any extra spaces
        filtered_text = re.sub(r'\s+', ' ', filtered_text).strip()
        
        return filtered_text

    def speak(self, text: str):
        """Text-to-speech with interruption support and emoji filtering"""
        if not text or not self.speak_mode:
            return
            
        try:
            # Filter out emojis for speech
            speech_text = self.filter_emoji_text(text)
            if not speech_text:
                return
                
            # Set speaking flag
            self.is_speaking = True
            self.interruption_detected = False
            
            # Create fresh engine instance each time
            self.current_speech_engine = pyttsx3.init()
            
            # Set properties
            self.current_speech_engine.setProperty('rate', self.config_manager.get('assistant.voice_rate', 180))
            self.current_speech_engine.setProperty('volume', self.config_manager.get('assistant.voice_volume', 0.8))
            
            # Start interruption listening in a separate thread
            if self.speak_mode:
                self.start_interruption_listener()
            
            # Speak
            self.current_speech_engine.say(speech_text)
            self.current_speech_engine.runAndWait()
            
        except Exception as e:
            print(f"❌ TTS Error: {e}")
        finally:
            # Clean up
            self.is_speaking = False
            self.stop_interruption_listener()
            if self.current_speech_engine:
                try:
                    self.current_speech_engine.stop()
                    self.current_speech_engine = None
                except:
                    pass

    def start_interruption_listener(self):
        """Start listening for interruptions while speaking"""
        if self.listening_thread and self.listening_thread.is_alive():
            return
            
        self.stop_listening = False
        self.listening_thread = threading.Thread(target=self._interruption_listener)
        self.listening_thread.daemon = True
        self.listening_thread.start()

    def stop_interruption_listener(self):
        """Stop the interruption listener"""
        self.stop_listening = True
        if self.listening_thread and self.listening_thread.is_alive():
            self.listening_thread.join(timeout=1.0)

    def _interruption_listener(self):
        """Listen for 'jarvis' interruption while speaking"""
        if not self.setup_microphone():
            return
            
        while self.is_speaking and not self.stop_listening:
            try:
                with self.microphone as source:
                    # Quick listen for interruption
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=1)
                
                text = self.recognizer.recognize_google(audio).lower()
                
                # Check if user said "jarvis" to interrupt
                if self.call_name.lower() in text:
                    print(f"🎤 Interruption detected: {text}")
                    self.interrupt_speech()
                    break
                    
            except sr.WaitTimeoutError:
                # No speech detected, continue listening
                continue
            except (sr.UnknownValueError, sr.RequestError):
                # Could not understand audio or network error, continue
                continue
            except Exception:
                # Any other error, break the loop
                break

    def interrupt_speech(self):
        """Interrupt current speech"""
        self.interruption_detected = True
        if self.current_speech_engine:
            try:
                self.current_speech_engine.stop()
                self.current_speech_engine = None
            except:
                pass
        self.is_speaking = False
        print("⏸️ Speech interrupted - I'm listening...")

    def print_response(self, text: str, message_type: str = "info"):
        """Print and optionally speak response (without emojis in speech)"""
        icons = {
            "info": "🤖",
            "error": "❌",
            "success": "✅",
            "warning": "⚠️",
            "thinking": "🤔"
        }
        icon = icons.get(message_type, "🤖")
        
        print(f"\n{icon} {self.call_name.upper()}: {text}\n")
        
        # Speak the response (emoji filtering happens in speak method)
        if self.speak_mode and not self.interruption_detected:
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

    def get_running_apps(self):
        """Get list of running applications"""
        try:
            running_apps = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    # Filter common user applications
                    app_name = proc.info['name'].lower()
                    if any(keyword in app_name for keyword in [
                        'chrome', 'firefox', 'notepad', 'calculator', 'paint', 
                        'word', 'excel', 'powerpoint', 'code', 'spotify', 
                        'discord', 'whatsapp', 'telegram', 'vscode', 'pycharm'
                    ]):
                        memory_mb = proc.info['memory_info'].rss / 1024 / 1024
                        running_apps.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'memory_mb': round(memory_mb, 1)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return running_apps
        except Exception as e:
            print(f"❌ Error getting running apps: {e}")
            return []

    def close_application(self, app_name: str):
        """Close a running application"""
        try:
            app_name = app_name.lower()
            closed_count = 0
            
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if app_name in proc.info['name'].lower():
                        proc.terminate()
                        closed_count += 1
                        time.sleep(0.5)  # Small delay between terminations
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if closed_count > 0:
                return f"✅ Closed {closed_count} instance(s) of {app_name}"
            else:
                return f"❌ No running instances of {app_name} found"
                
        except Exception as e:
            return f"❌ Error closing {app_name}: {str(e)}"

    def close_all_apps(self):
        """Close all non-essential applications"""
        try:
            apps_to_close = [
                'notepad', 'calculator', 'paint', 'chrome', 'firefox', 
                'word', 'excel', 'powerpoint', 'spotify', 'discord'
            ]
            
            closed_apps = []
            for app in apps_to_close:
                result = self.close_application(app)
                if "✅" in result:
                    closed_apps.append(app)
                    time.sleep(0.5)
            
            if closed_apps:
                return f"✅ Closed applications: {', '.join(closed_apps)}"
            else:
                return "❌ No applications to close"
                
        except Exception as e:
            return f"❌ Error closing applications: {str(e)}"

    def detect_language_and_extension(self, code_content: str) -> tuple:
        """Detect programming language and appropriate file extension"""
        language_indicators = {
            'python': ['import ', 'def ', 'class ', 'print(', '#!/usr/bin/env python'],
            'javascript': ['function ', 'const ', 'let ', 'var ', 'document.', 'console.log'],
            'html': ['<!DOCTYPE', '<html', '<head>', '<body>', '<div'],
            'css': ['body {', '.class', '#id', '@media', 'font-size:'],
            'java': ['public class', 'import java.', 'System.out.println'],
            'cpp': ['#include <', 'using namespace', 'std::cout'],
            'c': ['#include <', 'printf(', 'scanf('],
            'php': ['<?php', '$_GET', '$_POST', 'echo '],
            'ruby': ['def ', 'class ', 'puts ', 'require '],
            'go': ['package main', 'import "', 'func main()'],
            'rust': ['fn main()', 'let mut ', 'println!'],
            'swift': ['import Foundation', 'func ', 'var ', 'let '],
            'sql': ['CREATE TABLE', 'SELECT ', 'INSERT INTO', 'UPDATE '],
            'bash': ['#!/bin/bash', 'echo ', 'mkdir ', 'cd ']
        }
        
        content_lower = code_content.lower()
        for lang, indicators in language_indicators.items():
            if any(indicator in content_lower for indicator in indicators):
                return lang, self.get_extension_for_language(lang)
        
        return 'text', '.txt'

    def get_extension_for_language(self, language: str) -> str:
        """Get file extension for programming language"""
        extensions = {
            'python': '.py',
            'javascript': '.js',
            'html': '.html',
            'css': '.css',
            'java': '.java',
            'cpp': '.cpp',
            'c': '.c',
            'php': '.php',
            'ruby': '.rb',
            'go': '.go',
            'rust': '.rs',
            'swift': '.swift',
            'sql': '.sql',
            'bash': '.sh',
            'text': '.txt'
        }
        return extensions.get(language, '.txt')

    def get_standard_filename(self, language: str, index: int = 1, project_name: str = "") -> str:
        """Get standard filenames for common file types"""
        standard_filenames = {
            'css': 'style.css',
            'javascript': 'script.js',
            'html': 'index.html' if index == 1 else f'page{index}.html',
            'python': 'main.py' if index == 1 else f'script{index}.py',
            'java': 'Main.java' if index == 1 else f'Class{index}.java',
        }
        
        # Use project name if available for main files
        if index == 1 and project_name and language in ['python', 'java']:
            if language == 'python':
                return f"{project_name}.py"
            elif language == 'java':
                return f"{project_name.capitalize()}.java"
        
        return standard_filenames.get(language, f"file{index}{self.get_extension_for_language(language)}")

    def generate_advanced_code(self, request: str) -> str:
        """Generate code with advanced prompting"""
        prompt = f"""
Generate complete, working code based on: {request}

REQUIREMENTS:
1. Provide COMPLETE, READY-TO-RUN code
2. Include proper error handling
3. Add necessary comments for clarity
4. Use best practices for the language
5. Include any required imports/dependencies
6. Make it production-ready when possible
7. Add usage examples if applicable

SPECIFIC INSTRUCTIONS:
- If it's a web project: include HTML, CSS, JS in separate code blocks
- For CSS files: use standard naming (style.css)
- For JavaScript files: use standard naming (script.js)
- For HTML files: use index.html for main page
- If it's Python: include shebang and virtual environment instructions if needed
- If it's a script: make it executable with proper error handling
- If it's an API: include example usage
- If it's a database: include schema and sample queries

Please format with clear code blocks showing file types.
"""
        return self.ask_openrouter(prompt, max_tokens=3000)

    def generate_code(self, request: str) -> str:
        """Generate code based on user request"""
        return self.generate_advanced_code(request)

    def create_project_structure(self, project_type: str, project_name: str) -> str:
        """Generate complete project structure"""
        project_prompts = {
            'web': f"Create a complete web application project structure for: {project_name}. Include HTML (index.html), CSS (style.css), JavaScript (script.js) files, package.json if needed, and a README with setup instructions.",
            'python': f"Create a complete Python project structure for: {project_name}. Include main script, requirements.txt, README.md, and any necessary modules.",
            'data-science': f"Create a complete data science project structure for: {project_name}. Include Jupyter notebooks, data processing scripts, model training code, and visualization.",
            'api': f"Create a complete REST API project structure for: {project_name}. Include main application file, routes, models, and testing.",
            'mobile': f"Create a complete mobile app project structure for: {project_name}. Include necessary files for React Native, Flutter, or native development.",
            'game': f"Create a complete game project structure for: {project_name}. Include game logic, assets organization, and main game loop.",
        }
        
        prompt = project_prompts.get(project_type.lower(), f"Create a complete project structure for {project_name}: {project_type}")
        return self.generate_advanced_code(prompt)

    def review_code(self, code: str, language: str) -> str:
        """Review and improve existing code"""
        prompt = f"""
Please review this {language} code and provide improvements:

CODE:
{code}

Please:
1. Identify bugs and issues
2. Suggest performance improvements
3. Recommend best practices
4. Provide security considerations
5. Show improved version if possible
6. Rate the code quality (1-10)
"""
        return self.ask_openrouter(prompt)

    def debug_code(self, error_message: str, code_snippet: str) -> str:
        """Debug code with error message"""
        prompt = f"""
Debug this code issue:

ERROR MESSAGE:
{error_message}

CODE:
{code_snippet}

Please:
1. Identify the root cause
2. Provide the fix
3. Explain why the error occurred
4. Suggest how to prevent similar issues
"""
        return self.ask_openrouter(prompt)

    def explain_code(self, code: str, language: str) -> str:
        """Explain what code does"""
        prompt = f"""
Explain this {language} code in detail:

CODE:
{code}

Please provide:
1. What the code does
2. How it works step by step
3. Key functions/variables explanation
4. Potential use cases
5. Any limitations or considerations
"""
        return self.ask_openrouter(prompt)

    def search_in_chrome(self, query: str):
        """Search directly in Chrome browser"""
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://www.google.com/search?q={encoded_query}"
            
            self.print_response(f"🔍 Searching in Chrome for: {query}")
            
            # Try to use Chrome specifically
            chrome_paths = [
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                "google-chrome",
                "chrome"
            ]
            
            chrome_found = False
            for chrome_path in chrome_paths:
                try:
                    subprocess.Popen([chrome_path, search_url])
                    chrome_found = True
                    break
                except:
                    continue
            
            # If Chrome not found, use default browser
            if not chrome_found:
                webbrowser.open(search_url)
                
            return True
            
        except Exception as e:
            self.print_response(f"❌ Failed to search in Chrome: {e}", "error")
            return False

    def save_and_open_code(self, code_content: str, filename: str = None):
        """Save generated code to a file and open it"""
        try:
            # Extract code from response and detect language
            detected_language, default_extension = self.detect_language_and_extension(code_content)
            
            if "```" in code_content:
                # Extract code from markdown code blocks USING re
                code_blocks = re.findall(r'```(?:\w+)?\n(.*?)\n```', code_content, re.DOTALL)
                if code_blocks:
                    code_content = '\n'.join(code_blocks)
            
            # Determine filename if not provided
            if not filename:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"generated_code_{timestamp}{default_extension}"
            elif not '.' in filename:
                filename += default_extension
            
            # Create file on desktop
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.exists(desktop_path):
                desktop_path = tempfile.gettempdir()
            
            file_path = os.path.join(desktop_path, filename)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code_content)
            
            # Open the file with appropriate application
            open_commands = {
                '.html': lambda: webbrowser.open(f'file://{file_path}'),
                '.py': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.js': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.java': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.cpp': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.c': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.php': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.rb': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.go': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.rs': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.swift': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.sql': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.sh': lambda: subprocess.Popen(['notepad.exe', file_path]),
                '.css': lambda: subprocess.Popen(['notepad.exe', file_path]),
            }
            
            for ext, open_func in open_commands.items():
                if filename.endswith(ext):
                    open_func()
                    break
            else:
                subprocess.Popen(['notepad.exe', file_path])
            
            self.print_response(f"✅ Code file created and opened: {filename} (Detected: {detected_language})")
            return file_path
            
        except Exception as e:
            self.print_response(f"❌ Error saving code: {e}", "error")
            return None

    def save_multiple_files(self, code_response: str, base_name: str = "project"):
        """Save multiple code files from a single response with standardized naming"""
        try:
            # Extract all code blocks with their languages USING re
            code_blocks = re.findall(r'```(\w+)?\n(.*?)\n```', code_response, re.DOTALL)
            
            if not code_blocks:
                # If no code blocks found, save as single file
                return self.save_and_open_code(code_response, f"{base_name}.txt")
            
            saved_files = []
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.exists(desktop_path):
                desktop_path = tempfile.gettempdir()
            
            project_folder = os.path.join(desktop_path, base_name)
            os.makedirs(project_folder, exist_ok=True)
            
            # Count files by type for proper naming
            file_counts = {}
            
            for i, (lang, code) in enumerate(code_blocks):
                if not lang:
                    lang = "text"
                else:
                    lang = lang.lower()
                
                # Count how many files of this type we've seen
                if lang not in file_counts:
                    file_counts[lang] = 1
                else:
                    file_counts[lang] += 1
                
                # Get standard filename
                filename = self.get_standard_filename(lang, file_counts[lang], base_name)
                file_path = os.path.join(project_folder, filename)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code.strip())
                
                saved_files.append(filename)
            
            # Create a README file with the original response
            readme_path = os.path.join(project_folder, "README.md")
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(f"# {base_name}\n\n")
                f.write("Generated by JARVIS AI Assistant\n\n")
                f.write("## Files Created:\n")
                for file in saved_files:
                    f.write(f"- `{file}`\n")
                f.write("\n## Project Structure:\n```\n")
                f.write(f"{base_name}/\n")
                for file in saved_files:
                    f.write(f"├── {file}\n")
                f.write("└── README.md\n```\n")
                f.write("\n## Original Response:\n```\n")
                f.write(code_response)
                f.write("\n```")
            
            # Open the main HTML file if it exists
            main_html_path = os.path.join(project_folder, "index.html")
            if os.path.exists(main_html_path):
                webbrowser.open(f'file://{main_html_path}')
            
            self.print_response(f"✅ Project created with {len(saved_files)} files in: {project_folder}")
            self.print_response(f"📁 Files: {', '.join(saved_files)}")
            return project_folder
            
        except Exception as e:
            self.print_response(f"❌ Error saving multiple files: {e}", "error")
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

💡 ARDUINO LIGHT CONTROL:
  light on - Turn light ON via Arduino
  light off - Turn light OFF via Arduino
  lights on - Turn light ON via Arduino
  lights off - Turn light OFF via Arduino
  turn on light - Turn light ON via Arduino
  turn off light - Turn light OFF via Arduino
  arduino status - Check Arduino connection

💻 ADVANCED CODE GENERATION:
  code [description] - Generate any code
  project [type] [name] - Create complete project
  review code [code] - Review and improve code
  debug [error] [code] - Debug code issues
  explain code [code] - Explain what code does
  
  Examples:
    code a neural network in Python
    project web ecommerce_app
    review code "def add(a,b): return a+b"
    debug "syntax error" "print('hello'"
    explain code "def factorial(n): return 1 if n==0 else n*factorial(n-1)"

🌐 SEARCH COMMANDS (NEW!):
  go in chrome and search [query] - Search directly in Chrome
  search chrome [query] - Search in Chrome
  search youtube [query] - Search YouTube
  search google [query] - Search Google
  open [website] - Open any website

🔄 APP MANAGEMENT:
  list apps - Show running applications
  close [app name] - Close specific application
  close all apps - Close all non-essential apps

📝 DOCUMENT COMMANDS:
  launch [app] - Launch applications
  write [document] - Create and write documents

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
  Arduino: {'✅ CONNECTED' if self.arduino.is_connected else '❌ DISCONNECTED'}
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

    def show_running_apps(self):
        """Show currently running applications"""
        running_apps = self.get_running_apps()
        if running_apps:
            app_list = "📱 Currently Running Applications:\n"
            for app in running_apps:
                app_list += f"  • {app['name']} (PID: {app['pid']}, Memory: {app['memory_mb']}MB)\n"
            self.print_response(app_list)
        else:
            self.print_response("No user applications currently running.")

    def execute_command(self, command: str):
        """Execute commands with better parsing"""
        cmd = command.strip().lower()
        
        # Add to command history
        self.command_history.append(cmd)
        if len(self.command_history) > 50:
            self.command_history.pop(0)

        if not cmd:
            return

        # Reset interruption flag at start of new command
        self.interruption_detected = False

        # 💡 ARDUINO LIGHT CONTROL COMMANDS
        if any(phrase in cmd for phrase in ["light on", "lights on", "turn on light", "switch on light"]):
            if self.arduino.is_connected:
                success, message = self.arduino.light_on()
                if success:
                    self.print_response(f"💡 Light turned ON! {message}")
                else:
                    self.print_response(f"❌ Failed to turn light on: {message}", "error")
            else:
                self.print_response("❌ Arduino not connected. Check connection and enable in config.", "error")
        
        elif any(phrase in cmd for phrase in ["light off", "lights off", "turn off light", "switch off light"]):
            if self.arduino.is_connected:
                success, message = self.arduino.light_off()
                if success:
                    self.print_response(f"💡 Light turned OFF! {message}")
                else:
                    self.print_response(f"❌ Failed to turn light off: {message}", "error")
            else:
                self.print_response("❌ Arduino not connected. Check connection and enable in config.", "error")
        
        elif "arduino status" in cmd:
            if self.arduino.is_connected:
                self.print_response("✅ Arduino is connected and ready!")
            else:
                self.print_response("❌ Arduino is not connected.", "error")
                # Show available ports
                ports = self.arduino.list_available_ports()
                if ports:
                    self.print_response("🔌 Available serial ports:")
                    for port in ports:
                        self.print_response(f"  - {port['device']}: {port['description']}")
                else:
                    self.print_response("❌ No serial ports found.")

        # 💻 ADVANCED CODE GENERATION
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
                print("\n💾 Would you like to save this code to a file? (yes/no/multiple)")
                save_choice = input("👤 You: ").strip().lower()
                
                if save_choice in ['yes', 'y', 'save']:
                    file_path = self.save_and_open_code(code_content)
                    if file_path:
                        self.speak(f"I've generated and saved your {code_request} code!")
                    else:
                        self.print_response("Failed to save the code file.", "error")
                elif save_choice in ['multiple', 'multi', 'm']:
                    project_name = input("Enter project name: ").strip() or "jarvis_project"
                    folder_path = self.save_multiple_files(code_content, project_name)
                    if folder_path:
                        self.speak(f"I've created a complete project for {code_request}!")
                    else:
                        self.print_response("Failed to create project files.", "error")
                else:
                    self.print_response("Code generated and displayed above!")
            else:
                self.print_response("Please specify what code you want me to generate.", "warning")
        
        elif cmd.startswith("project "):
            parts = cmd[8:].strip().split(' ', 1)
            if len(parts) >= 2:
                project_type, project_name = parts[0], parts[1]
                self.print_response(f"🚀 Creating {project_type} project: {project_name}")
                project_content = self.create_project_structure(project_type, project_name)
                
                print("\n" + "="*60)
                print(f"🚀 PROJECT STRUCTURE FOR: {project_name}")
                print("="*60)
                print(project_content)
                print("="*60)
                
                print("\n💾 Save as multiple files? (yes/no)")
                save_choice = input("👤 You: ").strip().lower()
                
                if save_choice in ['yes', 'y']:
                    folder_path = self.save_multiple_files(project_content, project_name)
                    if folder_path:
                        self.speak(f"I've created your {project_name} project!")
                    else:
                        self.print_response("Failed to create project files.", "error")
                else:
                    self.print_response("Project structure generated above!")
            else:
                self.print_response("Usage: project [type] [name] (e.g., 'project web my_website')", "warning")
        
        elif cmd.startswith("review code"):
            code_to_review = cmd[11:].strip()
            if code_to_review:
                language = input("Enter programming language: ").strip() or "python"
                self.print_response(f"🔍 Reviewing {language} code...")
                review = self.review_code(code_to_review, language)
                self.print_response(f"Code Review:\n{review}")
            else:
                self.print_response("Please provide the code to review.", "warning")
        
        elif cmd.startswith("debug "):
            parts = cmd[6:].strip().split(' ', 1)
            if len(parts) >= 2:
                error_msg, code_snippet = parts[0], parts[1]
                self.print_response("🐛 Debugging code...")
                debug_result = self.debug_code(error_msg, code_snippet)
                self.print_response(f"Debug Result:\n{debug_result}")
            else:
                self.print_response("Usage: debug [error_message] [code_snippet]", "warning")
        
        elif cmd.startswith("explain code"):
            code_to_explain = cmd[12:].strip()
            if code_to_explain:
                language = input("Enter programming language: ").strip() or "python"
                self.print_response(f"📚 Explaining {language} code...")
                explanation = self.explain_code(code_to_explain, language)
                self.print_response(f"Code Explanation:\n{explanation}")
            else:
                self.print_response("Please provide the code to explain.", "warning")

        # 🌐 CHROME SEARCH COMMANDS
        elif cmd.startswith("go in chrome and search "):
            search_query = cmd[23:].strip()
            if search_query:
                self.search_in_chrome(search_query)
            else:
                self.print_response("Please specify what you want to search in Chrome.", "warning")
        
        elif cmd.startswith("search chrome "):
            search_query = cmd[14:].strip()
            if search_query:
                self.search_in_chrome(search_query)
            else:
                self.print_response("Please specify what you want to search in Chrome.", "warning")

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
        
        # 🔄 APP MANAGEMENT
        elif cmd == "list apps":
            self.show_running_apps()
        
        elif cmd.startswith("close "):
            app_to_close = cmd[6:].strip()
            if app_to_close:
                if app_to_close == "all apps":
                    result = self.close_all_apps()
                    self.print_response(result)
                else:
                    result = self.close_application(app_to_close)
                    self.print_response(result)
            else:
                self.print_response("Please specify which app to close.", "warning")
        
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
            running_apps = self.get_running_apps()
            status_info = f"""
🔍 JARVIS STATUS:
🤖 Name: {self.call_name}
👤 User: {self.user_name}
🔊 Voice: {'ENABLED' if self.speak_mode else 'DISABLED'}
🎤 Input: {'SPEECH' if self.listen_mode else 'TEXT'}
🧠 Model: {self.model}
💾 Commands History: {len(self.command_history)}
📱 Running Apps: {len(running_apps)}
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
        print(f"💡 Arduino: {'✅ CONNECTED' if self.arduino.is_connected else '❌ DISCONNECTED'}")
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
💡 Arduino: {'✅ CONNECTED' if self.arduino.is_connected else '❌ DISCONNECTED'}

🎯 NEW FEATURES:
• 💡 Voice-controlled lights: "light on", "light off"
• Generate any code with 'code [description]'
• Create complete projects with 'project [type] [name]'
• 🆕 Chrome Search: 'go in chrome and search [query]'
• Review and debug existing code
• Standardized filenames: CSS → style.css, JS → script.js
• 🆕 INTERRUPTION: Say "{self.call_name}" while I'm speaking to interrupt me
• 🆕 NO EMOJI SPEECH: I won't speak emojis, only clean text
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
                    self.arduino.close()  # Close Arduino connection
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
        print("pip install pyttsx3 speechrecognition requests psutil pyserial")

if __name__ == "__main__":
    main()