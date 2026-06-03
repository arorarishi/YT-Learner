import streamlit as st
import os
import sys
import re
import asyncio
from openai import AsyncOpenAI
from datetime import datetime

# Add the current directory to sys.path so we can import from yt_summarizer_v2
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import existing logic from your project
# We import these but will carefully manage the client to support BYOK
from yt_summarizer_v2.main import (
    get_transcript_text, 
    extract_video_id, 
    fetch_video_metadata,
    PROMPT_TEMPLATES,
    MODEL_NAME
)
from yt_summarizer_v2.database import DatabaseRepository

# Page Configuration
st.set_page_config(
    page_title="YouTube AI Intelligence Hub",
    page_icon="📺",
    layout="wide"
)

# Custom CSS for Premium Look
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
    }
    .stTextInput > div > div > input {
        background-color: rgba(255, 255, 255, 0.05) !important;
        color: white !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
    }
    .stButton > button {
        background: linear-gradient(90deg, #3b82f6 0%, #2563eb 100%) !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 2rem !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: transform 0.2s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4) !important;
    }
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 1.5rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Database
db = DatabaseRepository()

# Sidebar: BYOK (Bring Your Own Key)
with st.sidebar:
    st.title("Settings")
    
    api_provider = st.selectbox("API Provider", ["DeepInfra (DeepSeek-V3)", "OpenAI (GPT-4o)"])
    
    if api_provider == "DeepInfra (DeepSeek-V3)":
        default_url = "https://api.deepinfra.com/v1/openai"
        default_model = "deepseek-ai/DeepSeek-V3"
    else:
        default_url = "https://api.openai.com/v1"
        default_model = "gpt-4o"
        
    api_key = st.text_input("Enter API Key", type="password", help="Your key is only used for this session and is never stored.")
    
    st.divider()
    st.markdown("### About")
    st.info("This tool uses AI to analyze YouTube transcripts. For long videos, it uses chunked processing to avoid context limits.")

# Helper for Async AI Calls with dynamic client
async def run_summarization(client, transcript, template, model, template_type):
    # We redefine summarize_in_chunks here to use the dynamic client passed from Streamlit
    lines = transcript.split('\n')
    chunks = []
    current_chunk = []
    current_length = 0
    max_chunk_chars = 50000
    
    for line in lines:
        if current_length + len(line) > max_chunk_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = current_chunk[-3:] if len(current_chunk) > 3 else []
            current_length = sum(len(l) for l in current_chunk)
        current_chunk.append(line)
        current_length += len(line)
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    sem = asyncio.Semaphore(5)
    
    async def process_chunk(i, chunk):
        async with sem:
            chunk_info = f"\n\n(Note: This is segment {i+1} of {len(chunks)} of the video transcript.)"
            prompt = f"{template}{chunk_info}\n\nTranscript Segment:\n{chunk}"
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts accurately and clearly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=3000 if template_type == "detailed_notes" else 1500
            )
            return i, response.choices[0].message.content

    st.write(f"⏳ Processing {len(chunks)} segments concurrently...")
    tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks)]
    results = await asyncio.gather(*tasks)
    
    results.sort(key=lambda x: x[0])
    summaries = [r[1] for r in results]

    return "\n\n---\n\n".join(summaries) if len(chunks) > 1 else summaries[0]

# Main UI
st.title("📺 YouTube Intelligence Hub")
st.markdown("Transform long videos into actionable insights in seconds.")

col1, col2 = st.columns([2, 1])

with col1:
    youtube_url = st.text_input("Paste YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    template_type = st.selectbox("Intelligence Type", 
                                 options=list(PROMPT_TEMPLATES.keys()),
                                 format_func=lambda x: x.replace('_', ' ').title())

with col2:
    st.markdown("<br>", unsafe_allow_html=True) # Spacer
    generate_btn = st.button("Generate Insight", use_container_width=True)

if generate_btn:
    if not api_key:
        st.error("❌ Please provide an API Key in the sidebar.")
    elif not youtube_url:
        st.error("❌ Please provide a YouTube URL.")
    else:
        try:
            video_id = extract_video_id(youtube_url)
            
            # Initialize dynamic client
            client = AsyncOpenAI(api_key=api_key, base_url=default_url)
            
            with st.status("🚀 Initializing processing...", expanded=True) as status:
                # 1. Fetch Metadata
                st.write("🔍 Fetching video metadata...")
                title, channel, thumb_url, thumb_blob = fetch_video_metadata(youtube_url)
                
                # 2. Fetch Transcript
                st.write("📄 Extracting transcript...")
                transcript = get_transcript_text(video_id)
                if not transcript:
                    st.error("Transcript not available for this video.")
                    st.stop()
                
                # Save to local library if you want to keep track
                db.save_transcript_metadata(video_id, transcript, title, channel, thumb_url, thumb_blob)
                
                # 3. Generate Insight
                st.write("🧠 Analyzing with AI...")
                template = PROMPT_TEMPLATES.get(template_type, "Please summarize:")
                
                final_summary = asyncio.run(run_summarization(client, transcript, template, default_model, template_type))
                
                # Save result to DB
                template_col_map = {
                    "summary": "summary_text", "quiz": "quiz_text", "study_notes": "study_notes_text",
                    "detailed_notes": "detailed_notes_text", "flash_cards": "flash_cards_text", "tags": "tags_text"
                }
                col_name = template_col_map.get(template_type)
                if col_name:
                    db.update_content(video_id, col_name, final_summary)
                
                status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

            # Display Results
            st.divider()
            res_tab, trans_tab = st.tabs(["💡 AI Insight", "📝 Full Transcript"])
            
            with res_tab:
                st.markdown(f"### {template_type.replace('_', ' ').title()}")
                st.markdown(final_summary)
                st.download_button("Download Markdown", final_summary, file_name=f"{video_id}_{template_type}.md")
                
            with trans_tab:
                st.text_area("Transcript Content", transcript, height=400)

        except Exception as e:
            st.error(f"Error: {str(e)}")

# Library Section (at bottom)
st.divider()
st.subheader("📚 Your Recent Analysis Library")
try:
    videos = db.get_all_videos()
    if videos:
        cols = st.columns(3)
        for i, video in enumerate(videos[:6]): # Show last 6
            with cols[i % 3]:
                with st.container():
                    st.image(video['thumbnail_url'], use_container_width=True)
                    st.markdown(f"**{video['title']}**")
                    st.caption(video['channel_name'])
    else:
        st.info("No videos in library yet. Start by pasting a URL above!")
except:
    st.warning("Library view unavailable.")
