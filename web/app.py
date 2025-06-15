# web/app.py
# Author: Makari Green
# Flask API for Watch Recovery Dashboard + Chatbot with AI Integration

import os
import sys
import json
import threading
import re
import base64
from io import BytesIO
from PIL import Image
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template_string, render_template, redirect, send_file, abort
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import mimetypes
import openai

# Add parent directory to path to import run_all
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from run_all import WatchFinderConfig, WatchFinderOrchestrator
except ImportError as e:
    print(f"Error importing run_all: {e}")
    print("Make sure you're running this from the Lost_Watch directory")
    sys.exit(1)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Config
UPLOAD_FOLDER = "lost_watch_images"
LATEST_SESSION_FILE = "web/latest_session.txt"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size

# OpenAI Configuration
openai.api_key = os.getenv('OPENAI_API_KEY', 'REPLACE_WITH_YOUR_KEY')

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("web", exist_ok=True)
os.makedirs("web/templates", exist_ok=True)

# Global matches storage for simple interface
matches = []

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Free AI alternatives - no API key needed!
import requests

class WatchChatbot:
    def __init__(self):
        self.conversation_history = {}
        self.active_searches = {}
        self.ai_mode = "huggingface"  # Can be "huggingface", "ollama", or "fallback"
    
    def query_huggingface_free(self, text):
        """Use Hugging Face's free inference API"""
        try:
            # Using a free conversational model
            API_URL = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
            
            response = requests.post(
                API_URL,
                json={"inputs": text},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get('generated_text', '').replace(text, '').strip()
            
            return None
            
        except Exception as e:
            print(f"Hugging Face API error: {e}")
            return None
    
    def query_ollama_local(self, text):
        """Use local Ollama if installed (completely free)"""
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama2",  # or "mistral", "codellama"
                    "prompt": f"You are a helpful watch finder assistant. User says: {text}. Respond helpfully:",
                    "stream": False
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
            
            return None
            
        except Exception as e:
            print(f"Ollama not available: {e}")
            return None
    
    def extract_watch_info_free_ai(self, message):
        """Extract watch info using free AI"""
        prompt = f"""Extract watch information from this message as JSON:
        Message: "{message}"
        
        Return only JSON like: {{"brand": "rolex", "material": "gold", "color": "blue", "search_query": "rolex gold blue", "confidence": 0.8}}
        """
        
        # Try Hugging Face first
        response = self.query_huggingface_free(prompt)
        if response:
            try:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
        
        # Try Ollama if available
        response = self.query_ollama_local(prompt)
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass
        
        # Fall back to keyword extraction
        return self.extract_watch_info_fallback(message)
    
    def generate_response_free_ai(self, message, user_id):
        """Generate response using free AI"""
        prompt = f"""You are a helpful assistant for a lost watch finder service. 
        
        User message: "{message}"
        
        Respond helpfully and conversationally. Keep it under 100 words. Help them describe their watch or upload photos to start a search across eBay, Reddit, and Facebook."""
        
        # Try Hugging Face
        response = self.query_huggingface_free(prompt)
        if response and len(response) > 10:
            return response
        
        # Try Ollama
        response = self.query_ollama_local(prompt)
        if response and len(response) > 10:
            return response
        
        # Fall back to keyword responses
        return self.generate_response_fallback(message, user_id)
    
    def extract_watch_info_fallback(self, message):
        """Fallback watch info extraction without AI - now with serial numbers"""
        message_lower = message.lower()
        
        # Common watch brands
        brands = ['rolex', 'omega', 'patek philippe', 'audemars piguet', 'cartier', 
                 'breitling', 'tag heuer', 'seiko', 'citizen', 'tissot', 'casio']
        
        # Common materials and colors
        materials = ['gold', 'silver', 'steel', 'platinum', 'rose gold', 'titanium']
        colors = ['blue', 'black', 'white', 'green', 'red', 'brown', 'silver']
        
        # Extract serial numbers and model numbers
        import re
        
        # Model numbers (like 5167/1A-001, 116610LN, etc.)
        model_patterns = [
            r'\b\d{4}[/-]\d+[A-Z]*[-]?\d*\b',  # 5167/1A-001, 5167-1A-001
            r'\b\d{6}[A-Z]+\b',  # 116610LN
            r'\b[A-Z]{2,3}[\d]{3,6}\b'  # IW371446, etc.
        ]
        
        # Case/Movement numbers (like 5820396, 6015653)
        serial_patterns = [
            r'\b\d{7}\b',  # 7-digit numbers
            r'\b\d{8}\b',  # 8-digit numbers
            r'\b[A-Z]\d{6,7}\b'  # Letter + 6-7 digits
        ]
        
        # Extract information
        found_brand = None
        found_materials = []
        found_colors = []
        found_models = []
        found_serials = []
        
        for brand in brands:
            if brand in message_lower:
                found_brand = brand
                break
        
        for material in materials:
            if material in message_lower:
                found_materials.append(material)
        
        for color in colors:
            if color in message_lower:
                found_colors.append(color)
        
        # Extract model numbers
        for pattern in model_patterns:
            matches = re.findall(pattern, message)
            found_models.extend(matches)
        
        # Extract serial numbers  
        for pattern in serial_patterns:
            matches = re.findall(pattern, message)
            found_serials.extend(matches)
        
        # Generate search query
        search_parts = []
        if found_brand:
            search_parts.append(found_brand)
        search_parts.extend(found_materials)
        search_parts.extend(found_colors)
        search_parts.extend(found_models)
        
        if search_parts or found_models or found_serials:
            search_query = ' '.join(search_parts)
            # Higher confidence if we have model/serial numbers
            confidence = 0.9 if (found_models or found_serials) else (0.7 if found_brand else 0.5)
            
            return {
                "brand": found_brand,
                "materials": found_materials,
                "colors": found_colors,
                "models": found_models,
                "serials": found_serials,
                "search_query": search_query,
                "confidence": confidence
            }
        else:
            return {"needs_clarification": True}
    
    def extract_watch_info(self, message):
        """Extract watch information from user message"""
        return self.extract_watch_info_free_ai(message)
    
    def generate_response_fallback(self, message, user_id):
        """Generate response without AI"""
        message_lower = message.lower()
        
        # Response templates
        if any(word in message_lower for word in ['hello', 'hi', 'hey']):
            return "Hello! I'm here to help you find your lost watch. Can you describe it to me or upload some reference photos?"
        
        elif any(word in message_lower for word in ['help', 'start', 'find']):
            return "I can help you search for your lost watch across eBay, Reddit, and Facebook! To get started, please tell me about your watch:\n\n• Brand and model\n• Serial numbers (model, case, movement)\n• Color and material\n• Or upload reference photos using the camera button 📷\n\nFor example: 'Patek Philippe 5167/1A-001 case 5820396 movement 6015653'"
        
        elif any(word in message_lower for word in ['rolex', 'omega', 'patek', 'cartier']):
            brands = ['rolex', 'omega', 'patek philippe', 'cartier', 'breitling']
            found_brand = next((brand for brand in brands if brand.split()[0] in message_lower), None)
            if found_brand:
                return f"Great! I can see you're looking for a {found_brand.title()} watch. Can you tell me more details like the color, material, or model? Or upload reference photos if you have them."
        
        elif any(word in message_lower for word in ['gold', 'silver', 'steel']):
            return "I can see you mentioned the material of your watch. That's helpful! What brand is it? And do you remember any other details like the color or model?"
        
        elif any(word in message_lower for word in ['blue', 'black', 'white', 'green']):
            return "The color details will help a lot in the search! What brand is your watch? And do you have any reference photos you could upload?"
        
        else:
            return "I understand you're looking for your lost watch. To help you search effectively, could you tell me:\n• The brand (Rolex, Omega, etc.)\n• The color or material\n• Or upload reference photos using the camera button 📷"
    
    def generate_response(self, message, user_id, search_results=None):
        """Generate conversational response"""
        # Update conversation history
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        
        self.conversation_history[user_id].append({"role": "user", "content": message})
        
        # Generate response using free AI
        response = self.generate_response_free_ai(message, user_id)
        
        self.conversation_history[user_id].append({"role": "assistant", "content": response})
        
        # Keep only last 10 messages
        if len(self.conversation_history[user_id]) > 10:
            self.conversation_history[user_id] = self.conversation_history[user_id][-10:]
        
        return response

# Initialize chatbot
chatbot = WatchChatbot()

# Chat HTML Template
CHAT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lost Watch Finder - AI Chat</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.6.2/socket.io.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; }
        
        .chat-container { 
            max-width: 800px; 
            margin: 0 auto; 
            height: 100vh; 
            display: flex; 
            flex-direction: column;
            background: white;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }
        
        .chat-header { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: white; 
            padding: 15px 20px; 
            text-align: center;
            position: relative;
        }
        
        .chat-header h1 { 
            font-size: 1.1em; 
            margin-bottom: 4px; 
            font-weight: 600;
        }
        .chat-header p { 
            opacity: 0.9; 
            font-size: 0.85em; 
            margin: 0;
        }
        
        .chat-messages { 
            flex: 1; 
            overflow-y: auto; 
            padding: 20px; 
            background: #f8f9fa;
        }
        
        .message { 
            margin-bottom: 15px; 
            display: flex; 
            align-items: flex-start;
        }
        
        .message.user { justify-content: flex-end; }
        
        .message-content { 
            max-width: 70%; 
            padding: 12px 16px; 
            border-radius: 18px; 
            word-wrap: break-word;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .message.bot .message-content { 
            background: white; 
            color: #333;
            border-bottom-left-radius: 4px;
        }
        
        .message.user .message-content { 
            background: #667eea; 
            color: white;
            border-bottom-right-radius: 4px;
        }
        
        .message-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            margin: 0 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 14px;
        }
        
        .bot-avatar { background: #667eea; color: white; }
        .user-avatar { background: #28a745; color: white; }
        
        .chat-input-container { 
            padding: 20px; 
            background: white; 
            border-top: 1px solid #eee;
        }
        
        .chat-input-row {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }
        
        .chat-input { 
            flex: 1;
            padding: 12px 16px; 
            border: 2px solid #e9ecef; 
            border-radius: 25px; 
            font-size: 14px;
            outline: none;
            resize: none;
            min-height: 20px;
            max-height: 100px;
        }
        
        .chat-input:focus { border-color: #667eea; }
        
        .send-btn, .upload-btn { 
            background: #667eea; 
            color: white; 
            border: none; 
            padding: 12px 20px; 
            border-radius: 25px; 
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        
        .send-btn:hover, .upload-btn:hover { background: #5a67d8; }
        
        .upload-btn { background: #28a745; }
        .upload-btn:hover { background: #218838; }
        
        .file-input { display: none; }
        
        .typing-indicator {
            display: none;
            padding: 10px 16px;
            background: white;
            border-radius: 18px;
            border-bottom-left-radius: 4px;
            color: #666;
            font-style: italic;
            max-width: 70%;
            margin-bottom: 15px;
        }
        
        .typing-indicator.show { display: block; }
        
        .search-status {
            background: #e3f2fd;
            border: 1px solid #2196f3;
            border-radius: 8px;
            padding: 12px;
            margin: 10px 0;
            color: #1976d2;
        }
        
        .match-result {
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .match-result img {
            max-width: 150px;
            height: auto;
            border-radius: 4px;
            margin-bottom: 8px;
        }
        
        .confidence-badge {
            background: #17a2b8;
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: bold;
        }
        
        .nav-links {
            position: absolute;
            top: 12px;
            right: 20px;
            display: flex;
            gap: 8px;
        }
        
        .nav-links a {
            color: rgba(255,255,255,0.9);
            text-decoration: none;
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 0.8em;
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.2);
            transition: all 0.3s ease;
        }
        
        .nav-links a:hover {
            color: white;
            background: rgba(255,255,255,0.2);
            transform: translateY(-1px);
        }
        
        .nav-links a.active {
            background: rgba(255,255,255,0.25);
            color: white;
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="nav-links">
                <a href="/api">API</a>
                <a href="/simple">Form</a>
                <a href="/chat" class="active">Chat</a>
            </div>
            <h1>Lost Watch Finder AI</h1>
            <p>I'll help you find your lost watch across eBay, Reddit, and Facebook</p>
        </div>
        
        <div class="chat-messages" id="chatMessages">
            <div class="message bot">
                <div class="message-avatar bot-avatar">🤖</div>
                <div class="message-content">
                    Hi! I'm here to help you find your lost watch. I can search across eBay, Reddit, and Facebook for potential matches.
                    <br><br>
                    To get started, you can:
                    <br>• Upload reference photos of your watch
                    <br>• Describe your watch to me
                    <br>• Tell me the brand, model, or any details you remember
                    <br><br>
                    What would you like to do first?
                </div>
            </div>
            <div class="typing-indicator" id="typingIndicator">AI is thinking...</div>
        </div>
        
        <div class="chat-input-container">
            <div class="chat-input-row">
                <textarea 
                    id="chatInput" 
                    class="chat-input" 
                    placeholder="Describe your watch or ask me anything..."
                    rows="1"
                ></textarea>
                <input type="file" id="fileInput" class="file-input" multiple accept="image/*">
                <button class="upload-btn" onclick="document.getElementById('fileInput').click()">
                    📷
                </button>
                <button class="send-btn" onclick="sendMessage()">Send</button>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        const chatMessages = document.getElementById('chatMessages');
        const chatInput = document.getElementById('chatInput');
        const typingIndicator = document.getElementById('typingIndicator');
        const fileInput = document.getElementById('fileInput');
        
        let userId = 'user_' + Math.random().toString(36).substr(2, 9);
        
        // Auto-resize textarea
        chatInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
        
        // Send message on Enter (but not Shift+Enter)
        chatInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        function sendMessage() {
            const message = chatInput.value.trim();
            if (!message) return;
            
            addMessage(message, 'user');
            chatInput.value = '';
            chatInput.style.height = 'auto';
            
            showTyping();
            socket.emit('chat_message', {
                message: message,
                user_id: userId
            });
        }
        
        function addMessage(content, sender, isHTML = false) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${sender}`;
            
            const avatar = document.createElement('div');
            avatar.className = `message-avatar ${sender}-avatar`;
            avatar.textContent = sender === 'bot' ? '🤖' : '👤';
            
            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            
            if (isHTML) {
                contentDiv.innerHTML = content;
            } else {
                contentDiv.textContent = content;
            }
            
            if (sender === 'user') {
                messageDiv.appendChild(contentDiv);
                messageDiv.appendChild(avatar);
            } else {
                messageDiv.appendChild(avatar);
                messageDiv.appendChild(contentDiv);
            }
            
            chatMessages.appendChild(messageDiv);
            scrollToBottom();
        }
        
        function showTyping() {
            typingIndicator.classList.add('show');
            scrollToBottom();
        }
        
        function hideTyping() {
            typingIndicator.classList.remove('show');
        }
        
        function scrollToBottom() {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        
        // File upload handling
        fileInput.addEventListener('change', function() {
            const files = this.files;
            if (files.length === 0) return;
            
            addMessage(`📷 Uploading ${files.length} image(s)...`, 'user');
            
            const formData = new FormData();
            for (let file of files) {
                formData.append('images', file);
            }
            
            showTyping();
            
            fetch('/upload_reference', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                hideTyping();
                if (data.error) {
                    addMessage(`❌ Upload failed: ${data.error}`, 'bot');
                } else {
                    socket.emit('images_uploaded', {
                        files: data.files,
                        user_id: userId
                    });
                }
            })
            .catch(error => {
                hideTyping();
                addMessage(`❌ Upload error: ${error.message}`, 'bot');
            });
            
            // Clear file input
            this.value = '';
        });
        
        // Socket event handlers
        socket.on('bot_response', function(data) {
            hideTyping();
            addMessage(data.message, 'bot', data.is_html || false);
        });
        
        socket.on('search_started', function(data) {
            const statusHTML = `
                <div class="search-status">
                    🔍 <strong>Search Started!</strong><br>
                    Session ID: ${data.session_id}<br>
                    Searching across eBay, Reddit, Poshmark, Craigslist, and Facebook Marketplace...<br>
                    I'll update you when I find matches!
                </div>
            `;
            addMessage(statusHTML, 'bot', true);
        });
        
        socket.on('search_results', function(data) {
            let resultsHTML = `
                <div class="search-status">
                    ✅ <strong>Search Complete!</strong><br>
                    Found ${data.matches.length} potential matches
                </div>
            `;
            
            // Sort matches by confidence (highest first)
            data.matches.sort((a, b) => b.confidence - a.confidence);
            
            data.matches.forEach((match, index) => {
                const serialBadge = match.serial_match ? '<span style="background: #ff6b35; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; margin-left: 4px;">SERIAL MATCH</span>' : '';
                
                resultsHTML += `
                    <div class="match-result" style="border-left: ${match.serial_match ? '4px solid #ff6b35' : '4px solid transparent'};">
                        <div style="display: flex; align-items: flex-start; gap: 12px;">
                            ${match.image ? `<img src="${match.image}" alt="Match ${index + 1}" style="width: 100px; height: 100px; object-fit: cover; border-radius: 8px; flex-shrink: 0; cursor: pointer;" onclick="window.open('${match.image}', '_blank')">` : ''}
                            <div style="flex: 1;">
                                <div style="margin-bottom: 8px;">
                                    <strong>Match ${index + 1}</strong>
                                    <span class="confidence-badge">${(match.confidence * 100).toFixed(1)}%</span>
                                    <span style="background: #6c757d; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; margin-left: 8px;">${match.platform}</span>
                                    ${serialBadge}
                                </div>
                                <div style="font-weight: 500; margin-bottom: 6px; color: #333; line-height: 1.3;">
                                    ${match.title}
                                </div>
                                <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 8px; font-size: 0.9em; color: #666;">
                                    ${match.price ? `<span style="color: #28a745; font-weight: bold; font-size: 1em;">${match.price}</span>` : ''}
                                    ${match.date_posted ? `<span>📅 Posted: ${match.date_posted}</span>` : ''}
                                </div>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    ${match.url ? `<a href="${match.url}" target="_blank" style="background: #007bff; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; font-size: 0.85em; display: inline-block;">🔗 View Original Listing</a>` : '<span style="color: #666; font-style: italic;">No direct link available</span>'}
                                    ${match.image ? `<button onclick="window.open('${match.image}', '_blank')" style="background: #6c757d; color: white; padding: 8px 12px; border: none; border-radius: 4px; font-size: 0.85em; cursor: pointer;">🖼️ Full Image</button>` : ''}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            });
            
            addMessage(resultsHTML, 'bot', true);
        });
        
        // Connect to socket
        socket.on('connect', function() {
            console.log('Connected to chat server');
        });
        
        socket.on('disconnect', function() {
            console.log('Disconnected from chat server');
        });
    </script>
</body>
</html>
"""

# Socket.IO Events
@socketio.on('chat_message')
def handle_chat_message(data):
    message = data['message']
    user_id = data['user_id']
    
    print(f"[CHAT] User {user_id}: {message}")
    
    # Extract watch information and generate response
    watch_info = chatbot.extract_watch_info(message)
    
    # Check if we should start a search
    if 'search_query' in watch_info and watch_info.get('confidence', 0) > 0.6:
        # Start search automatically
        query = watch_info['search_query']
        threshold = 0.60
        
        # Check if reference images exist
        reference_files = []
        try:
            reference_files = [f for f in os.listdir(UPLOAD_FOLDER) 
                             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        except:
            pass
        
        if reference_files:
            # Start the search
            config = WatchFinderConfig()
            config.reference_folder = UPLOAD_FOLDER
            config.match_threshold = threshold
            config.enabled_platforms["facebook"] = True
            config.enabled_platforms["reddit"] = True
            
            try:
                orchestrator = WatchFinderOrchestrator(config, query)
                
                # Emit search started
                emit('search_started', {
                    'session_id': config.session_id,
                    'query': query
                })
                
                def run_search():
                    try:
                        orchestrator.run_all_scrapers()
                        if orchestrator.matcher:
                            orchestrator.run_matching_analysis()
                        
                        # Extract matches for chat
                        matches = []
                        for platform, result in orchestrator.match_results.items():
                            if 'match_details' in result:
                                for match in result['match_details']:
                                    if match.get('is_likely_match', False):
                                        # Get the original image filename to find corresponding listing data
                                        image_filename = os.path.basename(match.get('test_image', ''))
                                        
                                        # Try to find the URL from the scraped results
                                        listing_url = None
                                        listing_price = None
                                        listing_title = f"Watch on {platform}"  # Default title
                                        listing_image = None
                                        
                                        # Look through the orchestrator's scraped files for URL data
                                        for result_file in orchestrator.all_scraped_files:
                                            if platform.lower() in result_file.lower():
                                                try:
                                                    with open(result_file, 'r', encoding='utf-8') as f:
                                                        platform_data = json.load(f)
                                                    
                                                    # Search through platform data for matching image
                                                    for item in platform_data:
                                                        # Handle both eBay format (image_path) and Reddit format (image_paths)
                                                        item_images = []
                                                        
                                                        # eBay uses 'image_path' (singular)
                                                        if 'image_path' in item:
                                                            item_images = [item['image_path']]
                                                        
                                                        # Reddit/other platforms use 'image_paths' (plural)
                                                        elif 'image_paths' in item:
                                                            item_images = item['image_paths']
                                                        
                                                        # Check if our image filename matches any of this item's images
                                                        if any(image_filename in img_path for img_path in item_images):
                                                            listing_url = item.get('url', item.get('listing_url'))
                                                            listing_price = item.get('price')
                                                            listing_title = item.get('title', listing_title)
                                                            listing_image = f"/results/image/{config.session_id}/{platform}/{image_filename}"
                                                            listing_date = item.get('date_posted', item.get('posted_date', 'Date not available'))
                                                            
                                                            # Check for serial number matches in the listing
                                                            listing_text = f"{item.get('title', '')} {item.get('description', '')}".lower()
                                                            serial_match_score = 0
                                                            
                                                            # Look for model numbers and serials in the listing
                                                            search_terms = [
                                                                '5167/1a-001', '5167-1a-001', '5167/1a', 
                                                                '5820396', '6015653', 'aquanaut'
                                                            ]
                                                            
                                                            for term in search_terms:
                                                                if term in listing_text:
                                                                    serial_match_score += 0.1
                                                            
                                                            break
                                                    
                                                    if listing_url:  # Found it, no need to check other files
                                                        break
                                                        
                                                except Exception as e:
                                                    print(f"Debug: Error reading {result_file}: {e}")
                                                    continue
                                        
                                        matches.append({
                                            'title': listing_title,
                                            'platform': platform,
                                            'confidence': match.get('best_score', 0) + serial_match_score,
                                            'url': listing_url,
                                            'price': listing_price,
                                            'image': listing_image,
                                            'date_posted': listing_date,
                                            'session_id': config.session_id,
                                            'serial_match': serial_match_score > 0
                                        })
                        
                        # Emit results with enhanced data
                        socketio.emit('search_results', {
                            'matches': matches[:5],  # Top 5 matches
                            'session_id': config.session_id
                        })
                        
                    except Exception as e:
                        print(f"Search error: {e}")
                        socketio.emit('bot_response', {
                            'message': f"Sorry, the search encountered an error: {str(e)}"
                        })
                
                # Run in thread
                thread = threading.Thread(target=run_search, daemon=True)
                thread.start()
                
                response = f"Perfect! I found a {watch_info.get('brand', 'watch')} {watch_info.get('model', '')} in your description. I'm starting a search now using your uploaded reference images."
                
            except Exception as e:
                response = f"I understand you're looking for a {watch_info.get('brand', 'watch')}, but I had trouble starting the search. Can you try uploading some reference images first?"
        else:
            response = "I understand you're looking for a watch! To get the best results, could you upload some reference photos first? Then I can search for matches across all platforms."
    else:
        # Generate conversational response
        response = chatbot.generate_response(message, user_id)
    
    emit('bot_response', {'message': response})

@socketio.on('images_uploaded')
def handle_images_uploaded(data):
    files = data['files']
    user_id = data['user_id']
    
    response = f"Great! I've received {len(files)} reference image(s). Now you can describe your watch or I can help you start a search. What details do you remember about your watch?"
    
    emit('bot_response', {'message': response})

# Routes (keeping all your existing routes)
@app.route("/")
def home():
    return redirect("/chat")

@app.route("/chat")
def chat_interface():
    return render_template_string(CHAT_TEMPLATE)

@app.route("/api")
def api_interface():
    return render_template_string(HTML_TEMPLATE)

@app.route("/simple", methods=["GET", "POST"])
def simple_interface():
    global matches
    
    if request.method == "POST":
        query = request.form.get("query")
        threshold = float(request.form.get("threshold", 0.60))
        
        if not query:
            return render_template_string(SIMPLE_FORM_TEMPLATE, 
                                        matches=[], query=None, 
                                        error="Please enter a search query")
        
        # Configure and run search
        config = WatchFinderConfig()
        config.reference_folder = UPLOAD_FOLDER
        config.match_threshold = threshold
        config.enabled_platforms["facebook"] = True
        config.enabled_platforms["reddit"] = True
        
        try:
            orchestrator = WatchFinderOrchestrator(config, query)
            
            # Run synchronously for simple interface
            orchestrator.run_all_scrapers()
            if orchestrator.matcher:
                orchestrator.run_matching_analysis()
            summary = orchestrator.generate_session_summary()
            
            # Extract matches with URLs and metadata from results
            matches = []
            for platform, result in orchestrator.match_results.items():
                if 'match_details' in result:
                    for match in result['match_details']:
                        if match.get('is_likely_match', False):
                            # Get the original image filename to find corresponding listing data
                            image_filename = os.path.basename(match.get('test_image', ''))
                            
                            # Try to find the URL from the scraped results
                            listing_url = None
                            listing_price = None
                            listing_title = image_filename.replace('.jpg', '').replace('_', ' ')  # Default title
                            
                            # Look through the orchestrator's scraped files for URL data
                            for result_file in orchestrator.all_scraped_files:
                                if platform.lower() in result_file.lower():
                                    try:
                                        with open(result_file, 'r', encoding='utf-8') as f:
                                            platform_data = json.load(f)
                                        
                                        # Search through platform data for matching image
                                        for item in platform_data:
                                            # Handle both eBay format (image_path) and Reddit format (image_paths)
                                            item_images = []
                                            
                                            # eBay uses 'image_path' (singular)
                                            if 'image_path' in item:
                                                item_images = [item['image_path']]
                                            
                                            # Reddit/other platforms use 'image_paths' (plural)
                                            elif 'image_paths' in item:
                                                item_images = item['image_paths']
                                            
                                            # Check if our image filename matches any of this item's images
                                            if any(image_filename in img_path for img_path in item_images):
                                                listing_url = item.get('url', item.get('listing_url'))
                                                listing_price = item.get('price')
                                                listing_title = item.get('title', listing_title)
                                                break
                                        
                                        if listing_url:  # Found it, no need to check other files
                                            break
                                            
                                    except Exception as e:
                                        print(f"Debug: Error reading {result_file}: {e}")
                                        continue
                            
                            matches.append({
                                'title': listing_title,
                                'platform': platform,
                                'confidence': match.get('best_score', 0),
                                'image_path': match.get('test_image', ''),
                                'session_id': config.session_id,
                                'url': listing_url,
                                'price': listing_price
                            })
            
            return render_template_string(SIMPLE_FORM_TEMPLATE, 
                                        matches=matches, query=query, 
                                        session_id=config.session_id)
                                        
        except Exception as e:
            return render_template_string(SIMPLE_FORM_TEMPLATE, 
                                        matches=[], query=query, 
                                        error=f"Search failed: {str(e)}")
    
    return render_template_string(SIMPLE_FORM_TEMPLATE, matches=[], query=None)

# Keep all your existing API routes
@app.route("/upload_reference", methods=["POST"])
def upload_reference():
    files = request.files.getlist("images")
    if not files or all(f.filename == '' for f in files):
        return jsonify({"error": "No files provided"}), 400
    
    # Clear old reference images
    try:
        for f in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, f)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        print(f"Warning: Could not clear old files: {e}")
    
    saved_files = []
    for file in files:
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            try:
                file.save(filepath)
                saved_files.append(filename)
            except Exception as e:
                print(f"Error saving file {filename}: {e}")
    
    if not saved_files:
        return jsonify({"error": "No valid image files uploaded"}), 400
    
    return jsonify({"message": "Files uploaded successfully", "files": saved_files})

@app.route("/start_search", methods=["POST"])
def start_search():
    data = request.json
    query = data.get("search_query")
    threshold = float(data.get("threshold", 0.80))
    
    if not query:
        return jsonify({"error": "Missing search_query"}), 400
    
    # Check if reference images exist
    reference_files = [f for f in os.listdir(UPLOAD_FOLDER) 
                      if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not reference_files:
        return jsonify({"error": "No reference images uploaded"}), 400
    
    # Start orchestrator
    config = WatchFinderConfig()
    config.reference_folder = UPLOAD_FOLDER
    config.match_threshold = threshold
    config.enabled_platforms["facebook"] = True
    config.enabled_platforms["reddit"] = True
    
    try:
        orchestrator = WatchFinderOrchestrator(config, query)
    except Exception as e:
        return jsonify({"error": f"Failed to initialize orchestrator: {str(e)}"}), 500
    
    def run_workflow():
        try:
            print(f"[WEB] Starting search workflow for: {query}")
            orchestrator.run_all_scrapers()
            if orchestrator.matcher:
                orchestrator.run_matching_analysis()
            orchestrator.generate_session_summary()
            orchestrator.print_final_report()
            
            # Save latest session ID for access
            with open(LATEST_SESSION_FILE, "w") as f:
                f.write(config.session_id)
            print(f"[WEB] Workflow completed for session: {config.session_id}")
        except Exception as e:
            print(f"[WEB] Workflow error: {e}")
    
    # Run it in a thread so the API responds immediately
    thread = threading.Thread(target=run_workflow, daemon=True)
    thread.start()
    
    return jsonify({
        "message": "Search started successfully", 
        "session_id": config.session_id,
        "reference_images": len(reference_files)
    })

@app.route("/results/latest", methods=["GET"])
def get_latest_results():
    try:
        with open(LATEST_SESSION_FILE, "r") as f:
            session_id = f.read().strip()
    except FileNotFoundError:
        return jsonify({"error": "No session run yet"}), 404
    
    summary_path = f"sessions/session_{session_id}/results/session_summary.json"
    if not os.path.exists(summary_path):
        return jsonify({"error": "Summary not found - search may still be running"}), 404
    
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        return jsonify(summary)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON in summary file: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error reading summary: {str(e)}"}), 500

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@app.route("/results/image/<session_id>/<platform>/<filename>")
def serve_session_image(session_id, platform, filename):
    """Serve images from session folders with /results/image/ prefix"""
    image_path = os.path.join(
        BASE_DIR,
        "sessions",
        f"session_{session_id}",
        "scraped_images",
        platform,
        filename
    )

    if not os.path.exists(image_path):
        return abort(404)

    mimetype, _ = mimetypes.guess_type(image_path)
    return send_file(image_path, mimetype=mimetype or "application/octet-stream")

@app.route("/image/<session_id>/<platform>/<filename>")
def serve_image(session_id, platform, filename):
    """Legacy route for serving images"""
    return serve_session_image(session_id, platform, filename)

@app.route("/static/matched/<filename>")
def serve_matched_image(filename):
    """Serve matched images from web/static/matched/ directory"""
    matched_dir = os.path.join("web", "static", "matched")
    image_path = os.path.join(matched_dir, filename)
    
    if not os.path.exists(image_path):
        return abort(404)
    
    mimetype, _ = mimetypes.guess_type(image_path)
    return send_file(image_path, mimetype=mimetype or "application/octet-stream")

@app.route("/api/status")
def get_status():
    """Simple status endpoint"""
    return jsonify({
        "status": "running",
        "message": "Lost Watch Finder API is operational"
    })

# Keep your existing HTML templates (add them here)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lost Watch Finder</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .upload-area { border: 2px dashed #ccc; padding: 20px; text-align: center; margin: 20px 0; }
        .btn { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
        .btn:hover { background: #0056b3; }
        .results { margin-top: 20px; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
        .status.success { background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
        .status.error { background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
        .status.info { background: #d1ecf1; border: 1px solid #bee5eb; color: #0c5460; }
        .nav { 
            margin-bottom: 20px; 
            padding: 15px 0;
            border-bottom: 1px solid #e9ecef;
        }
        .nav a { 
            margin-right: 12px; 
            color: #007bff; 
            text-decoration: none; 
            padding: 8px 16px;
            border-radius: 20px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            font-size: 0.9em;
            transition: all 0.3s ease;
        }
        .nav a:hover { 
            background: #007bff;
            color: white;
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,123,255,0.3);
        }
        .nav a.active {
            background: #007bff;
            color: white;
        }
    </style>
</head>
<body>
    <div class="nav">
        <a href="/api">API Interface</a>
        <a href="/simple">Simple Form</a>
        <a href="/chat">AI Chat</a>
    </div>
    
    <h1> Lost Watch Finder - API Interface</h1>
    
    <div class="upload-area">
        <h3>Upload Reference Images</h3>
        <input type="file" id="referenceImages" multiple accept="image/*">
        <button class="btn" onclick="uploadImages()">Upload Images</button>
    </div>
    
    <div>
        <h3>Start Search</h3>
        <input type="text" id="searchQuery" placeholder="Enter search query (e.g., 'patek philippe')" style="width: 300px; padding: 8px;">
        <input type="number" id="threshold" placeholder="Threshold" value="0.60" step="0.01" min="0" max="1" style="width: 100px; padding: 8px;">
        <button class="btn" onclick="startSearch()">Start Search</button>
    </div>
    
    <div id="status"></div>
    <div id="results"></div>
    
    <script>
        function showStatus(message, type = 'info') {
            const statusDiv = document.getElementById('status');
            statusDiv.innerHTML = `<div class="status ${type}">${message}</div>`;
        }
        
        async function uploadImages() {
            const fileInput = document.getElementById('referenceImages');
            const files = fileInput.files;
            
            if (files.length === 0) {
                showStatus('Please select images to upload', 'error');
                return;
            }
            
            const formData = new FormData();
            for (let file of files) {
                formData.append('images', file);
            }
            
            try {
                showStatus('Uploading images...', 'info');
                const response = await fetch('/upload_reference', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                if (response.ok) {
                    showStatus(` Uploaded ${result.files.length} images successfully`, 'success');
                } else {
                    showStatus(' Upload failed: ' + result.error, 'error');
                }
            } catch (error) {
                showStatus(' Upload error: ' + error.message, 'error');
            }
        }
        
        async function startSearch() {
            const query = document.getElementById('searchQuery').value;
            const threshold = document.getElementById('threshold').value;
            
            if (!query.trim()) {
                showStatus('Please enter a search query', 'error');
                return;
            }
            
            try {
                showStatus('🔍 Starting search...', 'info');
                const response = await fetch('/start_search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        search_query: query,
                        threshold: parseFloat(threshold)
                    })
                });
                
                const result = await response.json();
                if (response.ok) {
                    showStatus(` Search started! Session ID: ${result.session_id}`, 'success');
                    checkResults(result.session_id);
                } else {
                    showStatus(' Search failed: ' + result.error, 'error');
                }
            } catch (error) {
                showStatus(' Search error: ' + error.message, 'error');
            }
        }
        
        async function checkResults(sessionId) {
            const interval = setInterval(async () => {
                try {
                    const response = await fetch('/results/latest');
                    if (response.ok) {
                        const results = await response.json();
                        displayResults(results);
                        clearInterval(interval);
                    }
                } catch (error) {
                    // Still processing, continue polling
                }
            }, 5000);
            
            setTimeout(() => clearInterval(interval), 300000);
        }
        
        function displayResults(results) {
            const resultsDiv = document.getElementById('results');
            const matching = results.matching_summary || {};
            
            resultsDiv.innerHTML = `
                <div class="results">
                    <h3>🎯 Search Results</h3>
                    <p><strong>Total Matches:</strong> ${matching.total_likely_matches || 0}</p>
                    <p><strong>Images Analyzed:</strong> ${matching.total_images_analyzed || 0}</p>
                    <p><strong>Match Rate:</strong> ${matching.match_rate || '0%'}</p>
                    <p><strong>Session:</strong> ${results.session_info?.session_id || 'Unknown'}</p>
                    
                    <h4>Platform Breakdown:</h4>
                    <pre>${JSON.stringify(matching.platform_breakdown || {}, null, 2)}</pre>
                </div>
            `;
            
            showStatus('Search completed!', 'success');
        }
    </script>
</body>
</html>
"""

SIMPLE_FORM_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lost Watch Finder - Simple Form</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .form-group { margin: 15px 0; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
        .form-group input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .btn { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
        .btn:hover { background: #0056b3; }
        .match-card { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; background: #f9f9f9; }
        .match-card img { max-width: 200px; height: auto; border-radius: 4px; }
        .match-card h3 { margin-top: 0; color: #333; }
        .nav { margin-bottom: 20px; }
        .nav a { margin-right: 15px; color: #007bff; text-decoration: none; }
        .nav a:hover { text-decoration: underline; }
        .listing-link { 
            display: inline-block; 
            background: #28a745; 
            color: white; 
            padding: 8px 16px; 
            text-decoration: none; 
            border-radius: 4px; 
            margin-top: 10px;
            font-weight: bold;
        }
        .listing-link:hover { 
            background: #218838; 
            color: white; 
            text-decoration: none; 
        }
        .confidence-badge {
            background: #17a2b8;
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.9em;
            font-weight: bold;
        }
        .platform-badge {
            background: #6c757d;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="nav">
        <a href="/api">API Interface</a>
        <a href="/simple" class="active">Simple Form</a>
        <a href="/chat">AI Chat</a>
    </div>

    <h1>🔍 Lost Watch Finder - Simple Form</h1>
    
    <form method="POST">
        <div class="form-group">
            <label for="query">Search Query:</label>
            <input type="text" id="query" name="query" placeholder="Enter watch brand/model (e.g., 'patek philippe')" 
                   value="{{ query or '' }}" required>
        </div>
        
        <div class="form-group">
            <label for="threshold">Match Threshold:</label>
            <input type="number" id="threshold" name="threshold" step="0.01" min="0" max="1" 
                   value="0.60" placeholder="0.60">
        </div>
        
        <button type="submit" class="btn">🔍 Start Search</button>
    </form>
    
    {% if query %}
    <div style="margin-top: 30px;">
        <h2>Search Results for: "{{ query }}"</h2>
        
        {% if matches %}
            <p><strong>Found {{ matches|length }} matches!</strong></p>
            
            {% for match in matches %}
            <div class="match-card">
                <h3>
                    {{ match.get('title', 'Unknown') }}
                    <span class="confidence-badge">{{ "%.1f"|format(match.get('confidence', 0) * 100) }}%</span>
                    <span class="platform-badge">{{ match.get('platform', 'Unknown') }}</span>
                </h3>
                
                {% if match.get('image_path') %}
                <img src="/results/image/{{ session_id }}/{{ match.get('platform') }}/{{ match.get('image_path').split('/')[-1] }}" 
                     alt="Match Image" style="max-width: 200px;">
                {% endif %}
                
                <div style="margin-top: 10px;">
                    {% if match.get('price') %}
                    <p><strong>Price:</strong> {{ match.get('price') }}</p>
                    {% endif %}
                    
                    {% if match.get('url') %}
                    <a href="{{ match.get('url') }}" target="_blank" class="listing-link">
                        🔗 View Original Listing
                    </a>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        {% else %}
            <p>No matches found. Try adjusting your search query or lowering the threshold.</p>
        {% endif %}
    </div>
    {% endif %}
</body>
</html>
"""

if __name__ == "__main__":
    print(" Starting Lost Watch Finder Web Interface with AI Chat...")
    print(" API Interface: http://localhost:5050/api")
    print(" Simple Form: http://localhost:5050/simple")
    print(" AI Chat Interface: http://localhost:5050/chat")
    print(" AI-powered conversational search now available!")
    socketio.run(app, debug=True, host='0.0.0.0', port=5050)