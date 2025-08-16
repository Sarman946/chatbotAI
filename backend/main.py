from fastapi import FastAPI, HTTPException,BackgroundTasks,UploadFile,File,Form
from pydantic import BaseModel,Field
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import logging
from sklearn.metrics.pairwise import cosine_similarity
from dotenv import load_dotenv
from groq import Groq
from groq.types.chat import ChatCompletionMessageParam
from fastapi.middleware.cors import CORSMiddleware
import uuid
import shortuuid
from datetime import datetime, timedelta

# LangChain message types
from langchain.schema import HumanMessage, AIMessage, SystemMessage
from fastapi.responses import JSONResponse,StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import httpx
import logging
import tempfile
from TTS.api import TTS
from transformers import pipeline




logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)









# Load environment variables
load_dotenv()


# Initialize FastAPI app
app = FastAPI(title="Food Studio Menu AI Assistant",
              description="API for food recommendations and answering menu queries using LLM")

# Groq API client setup
GROQ_API_KEY = os.getenv("GROQ_API_KEY")






class TokenRequest(BaseModel):
    session_id: str


class TTSRequest(BaseModel):
    text: str
    session_id: str


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    min_similarity: float = 0.3
    session_id: str



# Dummy storage and retrieval logic
async def get_conversation_history(session_id: str):
    return []  # Replace with DB logic


async def store_conversation(session_id: str, query: str, answer: str):
    pass  # Replace with DB storage logic


async def get_recommendations(query: str, top_k: int, min_similarity: float):
    return []  # Replace with actual recommendation logic






# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize models
try:
    # STT model (Whisper Tiny)
    stt_pipe = pipeline("automatic-speech-recognition", model="openai/whisper-tiny")
    
    # TTS model (Coqui TTS)
    tts_model = TTS(model_name="tts_models/en/ljspeech/fast_pitch")
    
    logger.info("Successfully initialized STT/TTS models")
except Exception as e:
    logger.error(f"Error initializing models: {e}")
    raise RuntimeError("Failed to initialize AI models")

# Initialize Groq client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    logger.warning("API key for Groq is missing. Please set the GROQ_API_KEY in the .env file.")
    groq_client = None
else:
    groq_client = Groq(api_key=GROQ_API_KEY)
    logger.info("Successfully initialized Groq client")

# Load menu data
try:
    menu_df = pd.read_csv("Food_Studio_Menu.csv")
    logger.info(f"Successfully loaded menu data with {len(menu_df)} items")
except Exception as e:
    logger.error(f"Error loading menu data: {e}")
    menu_df = None
import pickle

# Initialize sentence transformer for embeddings
try:
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("Successfully loaded sentence transformer model")
except Exception as e:
    logger.error(f"Error loading sentence transformer: {e}")
    embedding_model = None

# Precompute menu item embeddings
item_embeddings = None
if embedding_model is not None and menu_df is not None:
    try:
        menu_df['rich_text'] = menu_df.apply(
            lambda row: f"Category: {row['Category']} - {row['Name']} - {row['Description'] if isinstance(row['Description'], str) else ''} - Price: {row['Price']} - Tags: {row['Tags'] if isinstance(row['Tags'], str) else ''}",
            axis=1
        )
        texts = menu_df['rich_text'].tolist()
        item_embeddings = embedding_model.encode(texts)
        logger.info(f"Successfully created embeddings for {len(texts)} menu items")
    except Exception as e:
        logger.error(f"Error creating menu embeddings: {e}")


# === MODELS ===
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=8)

class STTRequest(BaseModel):
    audio_data: str = Field(..., min_length=100)

class TokenRequest(BaseModel):
    session_id: str = Field(..., min_length=8, example=shortuuid.uuid())



class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    min_similarity: float = 0.3
    session_id: str

class MenuItemResponse(BaseModel):
    item_name: str
    category: str
    description: Optional[str]
    price: float
    tags: Optional[str]
    similarity_score: float

class AIResponse(BaseModel):
    answer: str
    recommendations: List[MenuItemResponse]
    processed_query: str
    session_id: str

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    min_similarity: Optional[float] = 0.3
    chat_history: Optional[List[Any]] = []
    session_id: Optional[str] = None

class SessionResponse(BaseModel):
    session_id: str
    created_at: str
    message_count: int

# === CHAT MEMORY SYSTEM ===
class ChatMemoryManager:
    def __init__(self, expire_after_hours=24):
        self.sessions = {}  # {session_id: {"messages": [], "created_at": datetime, "preferences": {}}}
        self.expire_after = timedelta(hours=expire_after_hours)
        
    def create_session(self) -> str:
        """Create a new chat session and return its ID"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "messages": [
                {"role": "system", "content": "You are an AI assistant for Food Studio restaurant. Your job is to help customers with menu queries and provide helpful, friendly responses. IMPORTANT: Always remember the user's preferences mentioned in previous messages like vegetarian/non-vegetarian diet, spice level preferences, allergies, etc. and tailor your recommendations accordingly."}
            ],
            "created_at": datetime.now(),
            "preferences": {}  # Store user preferences here
        }
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """Add a message to the specified session"""
        if session_id not in self.sessions:
            return False
        
        self.sessions[session_id]["messages"].append({
            "role": role,
            "content": content
        })
        return True
    
    def update_preferences(self, session_id: str, preferences: Dict) -> bool:
        """Update preferences for a session"""
        if session_id not in self.sessions:
            return False
        
        if "preferences" not in self.sessions[session_id]:
            self.sessions[session_id]["preferences"] = {}
            
        self.sessions[session_id]["preferences"].update(preferences)
        return True
    
    def get_preferences(self, session_id: str) -> Dict:
        """Get preferences for a session"""
        if session_id not in self.sessions:
            return {}
        
        return self.sessions[session_id].get("preferences", {})
    
    def get_messages(self, session_id: str) -> List[Dict[str, str]]:
        """Get all messages for a session"""
        if session_id not in self.sessions:
            return []
        
        return self.sessions[session_id]["messages"]
    
    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a session"""
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        return {
            "session_id": session_id,
            "created_at": session["created_at"].isoformat(),
            "message_count": len(session["messages"]),
            "preferences": session.get("preferences", {})
        }
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active sessions"""
        return [
            {
                "session_id": sid,
                "created_at": info["created_at"].isoformat(),
                "message_count": len(info["messages"]),
                "preferences": info.get("preferences", {})
            }
            for sid, info in self.sessions.items()
        ]
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        now = datetime.now()
        expired_sessions = [
            sid for sid, info in self.sessions.items()
            if now - info["created_at"] > self.expire_after
        ]
        
        for sid in expired_sessions:
            del self.sessions[sid]
        
        return len(expired_sessions)

# Initialize the chat memory manager
chat_memory = ChatMemoryManager(expire_after_hours=24)

# === HELPERS ===

def convert_langchain_messages_to_chat_history(messages: List[Any]) -> List[Dict[str, str]]:
    """Convert LangChain message objects to dict format expected by Groq"""
    converted = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, dict) and "role" in msg and "content" in msg:
            # Already a dict
            converted.append(msg)
            continue
        else:
            continue

        converted.append({"role": role, "content": msg.content})
    return converted


def extract_preferences(query: str) -> Dict[str, str]:
    """Extract user preferences from the query"""
    preferences = {}
    
    # Check for dietary preferences
    if any(term in query.lower() for term in ["vegetarian", "veg", "no meat", "no non-veg", "only veg"]):
        preferences["diet"] = "vegetarian"
    elif any(term in query.lower() for term in ["non-veg", "non veg", "meat", "chicken", "fish"]):
        preferences["diet"] = "non-vegetarian"
    
    # Check for spice preferences
    if any(term in query.lower() for term in ["spicy", "hot", "extra spice"]):
        preferences["spice_level"] = "high"
    elif any(term in query.lower() for term in ["mild", "not spicy", "less spicy"]):
        preferences["spice_level"] = "low"
    
    return preferences


def get_menu_recommendations(query: str, top_k: int = 5, min_similarity: float = 0.3, preferences: Dict = None):
    if embedding_model is None or item_embeddings is None:
        raise HTTPException(status_code=500, detail="Embedding model not initialized")

    query_embedding = embedding_model.encode([query])[0]
    similarities = cosine_similarity([query_embedding], item_embeddings)[0]
    top_indices = np.argsort(similarities)[::-1][:top_k*2]  # Get more items to filter from

    recommendations = []
    for idx in top_indices:
        score = similarities[idx]
        if score >= min_similarity:
            item = menu_df.iloc[idx]
            recommendations.append(
                MenuItemResponse(
                    item_name=item['Name'],
                    category=item['Category'],
                    description=item['Description'] if isinstance(item['Description'], str) else None,
                    price=float(item['Price']),
                    tags=item['Tags'] if isinstance(item['Tags'], str) else None,
                    similarity_score=float(score)
                )
            )
    
    # Filter recommendations based on preferences
    if preferences and "diet" in preferences:
        if preferences["diet"] == "vegetarian":
            non_veg_keywords = ["chicken", "fish", "mutton", "prawns", "egg", "meat", "murgh", "mahi", "non-veg"]
            filtered_recs = [
                item for item in recommendations 
                if not any(keyword in item.item_name.lower() for keyword in non_veg_keywords) and
                not any(keyword in (item.tags or "").lower() for keyword in non_veg_keywords) and
                not any(keyword in (item.description or "").lower() for keyword in non_veg_keywords)
            ]
            if filtered_recs:
                recommendations = filtered_recs
    
    return recommendations[:top_k]

# Professional Waiter Prompt System

def get_professional_waiter_prompt(customer_query: str, recommendations: List[MenuItemResponse], user_preferences: Dict = None) -> str:
    """Formats the professional waiter prompt for the Groq API"""
    
    # Format menu recommendations for the prompt
    menu_recommendations = []
    for r in recommendations[:4]:  # Limit to 4 recommendations
        menu_recommendations.append(
            f"- {r.item_name} (₹{r.price}): {r.description if r.description else 'No description'} | " +
            f"Tags: {r.tags if r.tags else 'N/A'} | Category: {r.category}"
        )
    
    recommendations_text = "\n".join(menu_recommendations)
    
    # Format user preferences
    preferences_text = []
    if user_preferences:
        if "diet" in user_preferences:
            preferences_text.append(f"Dietary preference: {user_preferences['diet']}")
        if "spice_level" in user_preferences:
            preferences_text.append(f"Spice preference: {user_preferences['spice_level']}")
    
    # Determine dining context (can be expanded later)
    dining_context = "casual"  # Default context
    if "anniversary" in customer_query.lower() or "romantic" in customer_query.lower() or "special" in customer_query.lower():
        dining_context = "romantic"
    elif "family" in customer_query.lower() or "kids" in customer_query.lower():
        dining_context = "family"
    elif "business" in customer_query.lower() or "meeting" in customer_query.lower():
        dining_context = "business"
    
    # Build the system prompt
    system_prompt = """
You are Restaurassist, a friendly and professional waiter with 15+ years of experience at upscale restaurants. You provide helpful, concise dining guidance to customers.

## Core Behaviors
- Keep responses compact and brief while remaining polite
- Maintain professional courtesy without unnecessary elaboration
- Provide detailed descriptions only when specifically asked about food items
- DO NOT present recommendations in text format - the system will handle that separately
- When multiple preferences are stated, respond appropriately but let the system handle recommendations

## Communication Style
- Warm, approachable, and customer-focused
- Professional yet conversational tone
- Brief, direct answers to questions
- No unnecessary small talk or verbose explanations
- Precise to the point ,polite conversation with the customers

## IMPORTANT INSTRUCTIONS
- DO NOT list menu items or recommendations in your response text
- format recommendations in boxes, bullet points, or any other format
- include prices or descriptions of menu items unless specifically asked about a particular item
- Instead, provide a friendly, conversational response about the query without listing specific items
- The system will separately display recommended items in a structured format
- The conversation should be strictly to the point and compact(no unnecessary talks)
- Strictly try to give only maximum of 2 sentence responses not more than that(can give more sentence reply in nes)

Your role is to provide helpful guidance and answer questions about food in general, not to present the specific menu items.
"""
    
    # Build the user prompt
    user_prompt = f"""
Act as Restaurassist, the friendly and professional restaurant waiter. You're speaking with a guest who has the following known preferences:

Guest Profile:
- Dietary preference: {user_preferences.get('diet', 'not specified')}
- Spice preference: {user_preferences.get('spice_level', 'not specified')}
- Dining occasion: {dining_context}
- Current query: "{customer_query}"

Available menu items that may suit this guest's preferences:
{recommendations_text}

## Response Guidelines:
1. Keep responses brief and to the point
2. DO NOT list menu items or format recommendations - this will be handled separately by the system
3. Simply acknowledge the request and provide a friendly, conversational response
4. Only provide detailed descriptions if specifically asked about a particular food item
5. Maintain professional courtesy without unnecessary elaboration

For example, if asked for starter recommendations, respond with something like: "I'd be happy to suggest some starters for you. I've selected some options based on our menu that I think you'll enjoy." (without listing any specific items)

Please respond to the guest's current query with professionalism and helpful guidance, without listing specific menu items.
"""
    
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt
    }

def query_groq_api(messages):
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq client not initialized")

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            top_p=0.9,
            stream=False
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Error with Groq API: {e}")
        raise HTTPException(status_code=500, detail=f"Error with Groq API: {str(e)}")

def get_llama_response(query: str, recommendations: List[MenuItemResponse], session_id: str, user_preferences: Dict = None) -> str:
    # Get professional waiter prompt
    waiter_prompt = get_professional_waiter_prompt(
        customer_query=query,
        recommendations=recommendations,
        user_preferences=user_preferences
    )
    
    # Prepare messages for Groq API
    messages = [
        {"role": "system", "content": waiter_prompt["system_prompt"]},
        {"role": "user", "content": waiter_prompt["user_prompt"]}
    ]
    
    # Get response from Groq
    response = query_groq_api(messages)
    
    # Add the AI's response to chat memory
    chat_memory.add_message(session_id, "assistant", response)
    
    return response

def extract_food_intent(query: str) -> str:
    messages = [
        {"role": "system", "content": "You are a friendly and helpful AI assistant. You engage in normal conversations with users, answer their questions, and provide useful information in a polite and conversational manner."},
        {"role": "user", "content": f"""You are chatting with a friendly assistant. Respond to this query in a polite, conversational way without giving a direct explanation:

Query: {query}

Response:"""}
    ]
    
    try:
        response = query_groq_api(messages).strip()
        return response
    except Exception as e:
        logger.warning(f"Error in chatbot response, using original query: {e}")
        return query

def get_or_create_session(session_id: Optional[str] = None) -> str:
    """Get an existing session or create a new one if not found"""
    if session_id and session_id in chat_memory.sessions:
        return session_id
    
    return chat_memory.create_session()

# === ENDPOINTS ===

@app.get("/")
def read_root():
    return {"message": "Welcome to Food Studio Menu AI Assistant", "status": "online"}

@app.post("/query", response_model=AIResponse)
def process_query(request: QueryRequest):
    try:
        # Get or create a session
        session_id = get_or_create_session(request.session_id)
        
        # Extract preferences from query
        new_preferences = extract_preferences(request.query)
        
        # Update preferences in memory
        if new_preferences:
            chat_memory.update_preferences(session_id, new_preferences)
        
        # Get current user preferences
        user_preferences = chat_memory.get_preferences(session_id)
        
        # Process the query
        processed_query = extract_food_intent(request.query)
        logger.info(f"Processed query: '{request.query}' -> '{processed_query}'")

        # Store the user's query in chat memory
        chat_memory.add_message(session_id, "user", request.query)
        
        # Get recommendations based on the query and preferences
        recommendations = get_menu_recommendations(
            processed_query,
            top_k=request.top_k,
            min_similarity=request.min_similarity,
            preferences=user_preferences
        )

        # Get AI response with user preferences
        answer = get_llama_response(
            query=request.query,
            recommendations=recommendations,
            session_id=session_id,
            user_preferences=user_preferences
        )

        # If we have recommendations to show, add a flag to indicate we're showing recommendations separately
        has_recommendations = len(recommendations) > 0
        
        # If we have recommendations, append to the answer to make it clear recommendations are coming
        if has_recommendations and not "I've selected" in answer and not "recommendations" in answer.lower():
            answer += "\n\nI've selected some items from our menu that might interest you."

        return AIResponse(
            answer=answer,
            recommendations=recommendations,
            processed_query=processed_query,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.get("/menu-items", response_model=List[Dict[str, Any]])
def get_all_menu_items():
    if menu_df is None:
        raise HTTPException(status_code=500, detail="Menu data not loaded")
    return menu_df.fillna("").to_dict('records')

@app.get("/menu-categories")
def get_menu_categories():
    if menu_df is None:
        raise HTTPException(status_code=500, detail="Menu data not loaded")
    return {"categories": menu_df['Category'].unique().tolist()}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "menu_data": menu_df is not None,
        "embedding_model": embedding_model is not None,
        "groq_client": groq_client is not None,
        "item_embeddings": item_embeddings is not None
    }

# === SESSION MANAGEMENT ENDPOINTS ===

@app.post("/query")
async def query_endpoint(data: QueryRequest):
    try:
        conversation = await get_conversation_history(data.session_id)

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        messages = [
            {"role": "system", "content": "You are a helpful restaurant assistant for Food Studio."},
            *conversation,
            {"role": "user", "content": data.query}
        ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": "llama3-70b-8192",
                    "messages": messages,
                    "temperature": 0.5,
                    "max_tokens": 1024
                }
            )

        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]

        await store_conversation(data.session_id, data.query, answer)
        recommendations = await get_recommendations(data.query, data.top_k, data.min_similarity)

        return {"answer": answer, "recommendations": recommendations}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Failed to process query"})


# Core endpoints
@app.post("/speech-to-text")
async def speech_to_text(file: UploadFile = File(...), session_id: str = Form(...)):
    try:
        # Verify audio format
        if file.content_type not in ["audio/webm", "audio/wav"]:
            raise HTTPException(400, "Unsupported audio format")

        # Create temp file with proper extension
        file_ext = "wav" if "wav" in file.content_type else "webm"
        with tempfile.NamedTemporaryFile(suffix=f".{file_ext}", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            
        # Process audio
        transcript = stt_pipe(tmp.name)["text"]
        os.remove(tmp.name)
        
        return {"transcript": transcript}
    except Exception as e:
        logger.error(f"STT Error: {str(e)}")
        return JSONResponse(status_code=500, content={"error": "Speech processing failed"})

@app.post("/text-to-speech")
async def text_to_speech(data: TTSRequest, background_tasks: BackgroundTasks):
    try:
        filename = f"tts_{uuid.uuid4().hex}.wav"
        tts_model.tts_to_file(
            text=data.text,
            file_path=filename
        )
        def iterfile():
            with open(filename, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
            os.remove(filename)
        return StreamingResponse(
            iterfile(),
            media_type="audio/wav",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"TTS Error: {str(e)}")
        return JSONResponse(status_code=500, content={"error": "Speech generation failed"})




            
@app.post("/sessions/create", response_model=SessionResponse)
def create_session():
    """Create a new chat session"""
    session_id = chat_memory.create_session()
    return chat_memory.get_session_info(session_id)

@app.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    """Get information about a specific session"""
    session_info = chat_memory.get_session_info(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_info

@app.get("/sessions", response_model=List[SessionResponse])
def list_sessions():
    """List all active sessions"""
    return chat_memory.list_sessions()

@app.get("/sessions/{session_id}/history")
def get_session_history(session_id: str):
    """Get the chat history for a specific session"""
    messages = chat_memory.get_messages(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Filter out system messages for client display
    client_messages = [msg for msg in messages if msg["role"] != "system"]
    return {"session_id": session_id, "messages": client_messages}

@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a specific session"""
    if session_id not in chat_memory.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del chat_memory.sessions[session_id]
    return {"status": "success", "message": f"Session {session_id} deleted"}

@app.post("/sessions/cleanup")
def cleanup_sessions():
    """Clean up expired sessions"""
    count = chat_memory.cleanup_expired_sessions()
    return {"status": "success", "message": f"Cleaned up {count} expired sessions"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

