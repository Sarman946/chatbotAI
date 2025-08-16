import { useState, useEffect, useRef } from 'react';
import axios from 'axios';

function FoodStudioApp() {
  // State management
  const [menuItems, setMenuItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([
    { 
      type: 'bot', 
      message: "Hello! I'm your Food Studio assistant. How can I help you today? You can ask about our menu, dietary options, or popular dishes!"
    }
  ]);
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [filteredItems, setFilteredItems] = useState([]);
  const [healthStatus, setHealthStatus] = useState({});
  // Add state for session ID to maintain conversation context
  const [sessionId, setSessionId] = useState(null);
  
  // Voice assistant states
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessingSpeech, setIsProcessingSpeech] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [audioQueue, setAudioQueue] = useState([]);
  
  // Refs
  const chatEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(new Audio());
  
  // API base URL - replace with your backend URL
  const API_URL = 'http://localhost:8000';

  // Create a session or get existing session when the app loads
  useEffect(() => {
    const storedSessionId = localStorage.getItem('foodStudioSessionId');
    
    const initializeSession = async () => {
      try {
        if (storedSessionId) {
          // Verify if the stored session still exists
          const response = await axios.get(`${API_URL}/sessions/${storedSessionId}`);
          setSessionId(storedSessionId);
          
          // Load existing chat history
          const historyResponse = await axios.get(`${API_URL}/sessions/${storedSessionId}/history`);
          if (historyResponse.data.messages && historyResponse.data.messages.length > 0) {
            // Convert API messages to our chat format
            const formattedHistory = historyResponse.data.messages.map(msg => ({
              type: msg.role === 'user' ? 'user' : 'bot',
              message: msg.content
            }));
            
            // Keep the welcome message and add history
            setChatHistory(prev => [prev[0], ...formattedHistory]);
          }
        } else {
          // Create a new session
          const response = await axios.post(`${API_URL}/sessions/create`);
          const newSessionId = response.data.session_id;
          setSessionId(newSessionId);
          localStorage.setItem('foodStudioSessionId', newSessionId);
        }
      } catch (err) {
        console.error('Error initializing session:', err);
        // If there's an error with stored session, create a new one
        try {
          const response = await axios.post(`${API_URL}/sessions/create`);
          const newSessionId = response.data.session_id;
          setSessionId(newSessionId);
          localStorage.setItem('foodStudioSessionId', newSessionId);
        } catch (sessionErr) {
          setError('Failed to initialize chat session. Please refresh the page.');
        }
      }
    };

    initializeSession();
  }, [API_URL]);

  // Fetch initial data from backend
  useEffect(() => {
    const fetchInitialData = async () => {
      setLoading(true);
      try {
        // Fetch menu items, categories, and health status in parallel
        const [menuResponse, categoriesResponse, healthResponse] = await Promise.all([
          axios.get(`${API_URL}/menu-items`),
          axios.get(`${API_URL}/menu-categories`),
          axios.get(`${API_URL}/health`)
        ]);
        
        setMenuItems(menuResponse.data);
        setFilteredItems(menuResponse.data);
        setCategories(['All', ...categoriesResponse.data.categories]);
        setHealthStatus(healthResponse.data);
        setError(null);
      } catch (err) {
        setError('Failed to load menu data. Please try again later.');
        console.error('Error fetching initial data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchInitialData();
  }, []);

  // Auto-scroll chat to bottom when messages are added
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // Filter menu items when category changes
  useEffect(() => {
    if (selectedCategory === 'All') {
      setFilteredItems(menuItems);
    } else {
      setFilteredItems(menuItems.filter(item => item.Category === selectedCategory));
    }
  }, [selectedCategory, menuItems]);

  // Setup audio player for TTS responses
  useEffect(() => {
    const audioPlayer = audioPlayerRef.current;

    const handleAudioEnded = () => {
      setIsPlayingAudio(false);
      
      // Play next audio in queue if available
      if (audioQueue.length > 0) {
        const nextAudio = audioQueue[0];
        playAudio(nextAudio);
        setAudioQueue(prev => prev.slice(1));
      }
    };

    audioPlayer.addEventListener('ended', handleAudioEnded);
    
    return () => {
      audioPlayer.removeEventListener('ended', handleAudioEnded);
      audioPlayer.pause();
    };
  }, [audioQueue]);

  // Play audio
  const playAudio = (audioBlob) => {
    if (!audioBlob) return;
    
    const audioUrl = URL.createObjectURL(audioBlob);
    const audioPlayer = audioPlayerRef.current;
    
    audioPlayer.src = audioUrl;
    audioPlayer.play().catch(error => {
      console.error('Error playing audio:', error);
      setIsPlayingAudio(false);
    });
    
    setIsPlayingAudio(true);
  };

  // Queue audio for playback
  const queueAudio = (audioBlob) => {
    if (!audioBlob) return;

    if (isPlayingAudio) {
      setAudioQueue(prev => [...prev, audioBlob]);
    } else {
      playAudio(audioBlob);
    }
  };

  // Process TTS from response text
  const processTextToSpeech = async (text) => {
    if (!text || !sessionId) return;

    try {
      const response = await axios.post(
        `${API_URL}/text-to-speech`,
        { text, session_id: sessionId },
        { responseType: 'blob' }
      );

      queueAudio(response.data);
    } catch (err) {
      console.error('Error with text-to-speech:', err);
    }
  };

  // Start recording audio
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await processRecording(audioBlob);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Error accessing microphone:', err);
      setError('Could not access microphone. Please check permissions.');
    }
  };

  // Stop recording audio
  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      setIsProcessingSpeech(true);
    }
  };

  // Process recording - convert to text and send query
  const processRecording = async (audioBlob) => {
    if (!audioBlob || !sessionId) {
      setIsProcessingSpeech(false);
      return;
    }

    try {
      // Create form data with audio blob and session ID
      const formData = new FormData();
      formData.append('file', audioBlob);
      formData.append('session_id', sessionId);

      // Send to speech-to-text endpoint
      const response = await axios.post(`${API_URL}/speech-to-text`, formData);
      
      if (response.data && response.data.transcript) {
        const transcript = response.data.transcript.trim();
        
        if (transcript) {
          // Add user message to chat
          setChatInput(transcript);
          
          // Process the query automatically
          await processQuery(transcript);
        }
      }
    } catch (err) {
      console.error('Error processing speech:', err);
      setChatHistory(prev => [
        ...prev,
        {
          type: 'bot',
          message: "I'm having trouble understanding. Could you please type your question?"
        }
      ]);
    } finally {
      setIsProcessingSpeech(false);
    }
  };

  // Process query (used by both text and voice input)
  const processQuery = async (queryText) => {
    if (!queryText.trim() || !sessionId) return;

    // Add user message to chat
    const userMessage = { type: 'user', message: queryText };
    setChatHistory(prev => [...prev, userMessage]);
    
    // Clear input field if it's being shown
    setChatInput('');
    
    // Show typing indicator
    setChatHistory(prev => [...prev, { type: 'typing' }]);

    try {
      // Make API call with the query and include session ID
      const response = await axios.post(`${API_URL}/query`, {
        query: queryText,
        top_k: 5,
        min_similarity: 0.3,
        session_id: sessionId
      });
      
      // Remove typing indicator
      setChatHistory(prev => prev.filter(msg => msg.type !== 'typing'));
      
      // Create a new structure for the bot's response
      const newMessages = [];
      
      // Add bot text response
      if (response.data.answer.trim()) {
        newMessages.push({ 
          type: 'bot', 
          message: response.data.answer 
        });
        
        // Convert bot response to speech
        processTextToSpeech(response.data.answer);
      }
      
      // Add recommendation cards as a separate message if available
      if (response.data.recommendations && response.data.recommendations.length > 0) {
        newMessages.push({
          type: 'recommendations',
          items: response.data.recommendations
        });
      }
      
      // Update chat history with all new messages
      setChatHistory(prev => [...prev.filter(msg => msg.type !== 'typing'), ...newMessages]);
      
    } catch (err) {
      // Remove typing indicator and add error message
      setChatHistory(prev => {
        const updatedHistory = prev.filter(msg => msg.type !== 'typing');
        return [...updatedHistory, { 
          type: 'bot', 
          message: 'Sorry, I had trouble processing your request. Could you try again?' 
        }];
      });
      console.error('Error submitting query:', err);
    }
  };

  // Handle chat form submission
  const handleChatSubmit = async (e) => {
    e.preventDefault();
    await processQuery(chatInput);
  };

  // Function to handle starting a new conversation
  const handleNewConversation = async () => {
    try {
      // Create a new session
      const response = await axios.post(`${API_URL}/sessions/create`);
      const newSessionId = response.data.session_id;
      
      // Update local storage and state
      localStorage.setItem('foodStudioSessionId', newSessionId);
      setSessionId(newSessionId);
      
      // Reset chat history to just the welcome message
      setChatHistory([{ 
        type: 'bot', 
        message: "Hello! I'm your Food Studio assistant. How can I help you today? You can ask about our menu, dietary options, or popular dishes!"
      }]);
      
    } catch (err) {
      console.error('Error creating new session:', err);
      setError('Failed to start a new conversation. Please try again.');
    }
  };

  // Format price as Indian Rupees
  const formatPrice = (price) => {
    return `₹${price}`;
  };

  // Toggle voice recording
  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-4">
      <header className="bg-gradient-to-r from-orange-600 to-red-600 text-white p-6 rounded-lg shadow-lg mb-8">
        <h1 className="text-3xl font-bold text-center">Food Studio Menu</h1>
        <p className="text-center mt-2">Chat with our AI Assistant</p>
        
        {/* System status indicator */}
        <div className="mt-4 flex justify-center">
          <div className="bg-white bg-opacity-20 px-3 py-1 rounded-full text-sm flex items-center">
            <span className={`h-2 w-2 rounded-full mr-2 ${healthStatus.status === 'healthy' ? 'bg-green-400' : 'bg-red-400'}`}></span>
            <span>System Status: {healthStatus.status === 'healthy' ? 'Online' : 'Limited'}</span>
          </div>
        </div>
      </header>

      {/* Error message */}
      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-6">
          {error}
        </div>
      )}

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Column - Chat Interface */}
        <div className="lg:col-span-1">
          <div className="bg-white p-6 rounded-lg shadow-md mb-6 flex flex-col h-full max-h-[600px]">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">Chat with our Food Assistant</h2>
              
              {/* New conversation button */}
              <button 
                onClick={handleNewConversation}
                className="bg-orange-100 hover:bg-orange-200 text-orange-800 text-sm font-medium py-1 px-3 rounded-md transition-colors"
              >
                New Conversation
              </button>
            </div>
            
            {/* Session ID and voice indicator */}
            <div className="mb-3 flex justify-between items-center">
              {sessionId && (
                <div className="text-xs text-gray-500">
                  <span>Session ID: {sessionId.substring(0, 8)}... </span>
                  {chatHistory.length > 1 && <span>(Conversation memory active)</span>}
                </div>
              )}
              
              {/* Voice indicators */}
              <div className="flex items-center">
                {isPlayingAudio && (
                  <div className="mr-3 flex items-center text-xs text-green-600">
                    <span className="inline-block h-2 w-2 rounded-full bg-green-500 mr-1"></span>
                    Speaking...
                  </div>
                )}
                {isProcessingSpeech && (
                  <div className="mr-3 flex items-center text-xs text-orange-600">
                    <span className="inline-block h-2 w-2 rounded-full bg-orange-500 mr-1"></span>
                    Processing...
                  </div>
                )}
              </div>
            </div>
            
            {/* Chat History Display */}
            <div className="flex-grow overflow-y-auto mb-4 p-2">
              <div className="space-y-4">
                {chatHistory.map((chat, index) => {
                  if (chat.type === 'user') {
                    return (
                      <div key={index} className="flex justify-end">
                        <div className="bg-orange-500 text-white rounded-lg py-2 px-4 max-w-[80%]">
                          {chat.message}
                        </div>
                      </div>
                    );
                  } else if (chat.type === 'bot') {
                    return (
                      <div key={index} className="flex justify-start">
                        <div className="bg-gray-100 rounded-lg py-2 px-4 max-w-[80%]">
                          <div className="whitespace-pre-wrap">{chat.message}</div>
                        </div>
                      </div>
                    );
                  } else if (chat.type === 'typing') {
                    return (
                      <div key={index} className="flex justify-start">
                        <div className="bg-gray-100 rounded-lg py-2 px-4">
                          <span className="flex space-x-1">
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                          </span>
                        </div>
                      </div>
                    );
                  } else if (chat.type === 'recommendations') {
                    return (
                      <div key={index} className="flex justify-start">
                        <div className="bg-gray-100 rounded-lg py-3 px-4 max-w-[95%] w-full">
                          <h4 className="text-sm font-semibold text-orange-700 mb-2">Recommended for You:</h4>
                          <div className="grid grid-cols-1 gap-2">
                            {chat.items.map((item, itemIndex) => (
                              <div key={itemIndex} className="bg-white border border-orange-200 p-3 rounded-md shadow-sm hover:shadow-md transition-shadow">
                                <div className="flex justify-between items-start">
                                  <div className="font-medium text-orange-800">{item.item_name}</div>
                                  <div className="font-bold text-orange-600">{formatPrice(item.price)}</div>
                                </div>
                                <div className="text-xs text-gray-500 mt-1">
                                  {item.category}
                                  {item.tags && <span> • {item.tags}</span>}
                                </div>
                                {item.description && (
                                  <div className="text-sm mt-2 text-gray-700">{item.description}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                })}

                <div ref={chatEndRef} />
              </div>
            </div>
            
            {/* Chat Input Form */}
            <form onSubmit={handleChatSubmit} className="mt-auto">
              <div className="flex">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Ask about our menu, specials, or recommendations..."
                  className="flex-grow px-3 py-2 border border-gray-300 rounded-l-md shadow-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                  disabled={isRecording || isProcessingSpeech}
                />
                <button
                  type="button"
                  onClick={toggleRecording}
                  disabled={!sessionId || isProcessingSpeech}
                  className={`px-3 py-2 border-y ${isRecording 
                    ? 'bg-red-600 hover:bg-red-700 text-white' 
                    : 'bg-blue-500 hover:bg-blue-600 text-white'} 
                    transition-colors disabled:opacity-50`}
                >
                  {isRecording ? (
                    <div className="flex items-center">
                      <span className="inline-block h-2 w-2 rounded-full bg-red-300 mr-1 animate-pulse"></span>
                      <span>Stop</span>
                    </div>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clipRule="evenodd" />
                    </svg>
                  )}
                </button>
                <button
                  type="submit"
                  disabled={loading || !chatInput.trim() || !sessionId || isRecording || isProcessingSpeech}
                  className="bg-orange-500 hover:bg-orange-600 text-white font-medium py-2 px-4 rounded-r-md disabled:opacity-50 transition-colors"
                >
                  Send
                </button>
              </div>
              {isRecording && (
                <div className="text-center mt-2 text-sm text-red-600">
                  Recording... Click the microphone button when done.
                </div>
              )}
              {isProcessingSpeech && (
                <div className="text-center mt-2 text-sm text-orange-600">
                  Processing your voice...
                </div>
              )}
            </form>
          </div>
        </div>

        {/* Right Column - Menu Browser */}
        <div className="lg:col-span-1">
          <div className="bg-white p-6 rounded-lg shadow-md">
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-xl font-semibold">Browse Our Menu</h2>
              
              {/* Category Filter */}
              <div>
                <label htmlFor="category" className="sr-only">Filter by Category</label>
                <select
                  id="category"
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                >
                  {categories.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            
            {/* Loading state */}
            {loading && (
              <div className="flex justify-center items-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-orange-500"></div>
              </div>
            )}
            
            {/* Menu Items Grid */}
            {!loading && filteredItems.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[500px] overflow-y-auto p-1">
                {filteredItems.map((item, index) => (
                  <div key={index} className="border rounded-lg overflow-hidden hover:shadow-md transition-shadow">
                    <div className="bg-gray-100 px-4 py-2 border-b">
                      <span className="text-xs font-medium text-gray-500">{item.Category}</span>
                      {item.Tags && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {item.Tags.split(',').map((tag, i) => (
                            <span key={i} className="px-2 py-1 bg-orange-100 text-orange-800 text-xs rounded-full">
                              {tag.trim()}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="p-4">
                      <div className="flex justify-between items-start">
                        <h3 className="font-medium">{item.Name}</h3>
                        <span className="font-bold text-orange-600">{formatPrice(item.Price)}</span>
                      </div>
                      {item.Description && (
                        <p className="mt-2 text-sm text-gray-600">{item.Description}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {/* Empty state */}
            {!loading && filteredItems.length === 0 && (
              <div className="text-center py-12">
                <p className="text-gray-500">No menu items found in this category.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default FoodStudioApp;