import asyncio
from typing import Any, Dict, Tuple, List
from openai import AsyncOpenAI
from fastapi import HTTPException


class AIService:
    def __init__(self, api_key: str, base_url: str, model_name: str):
        if not api_key:
            raise RuntimeError("API key is required to create the AI service.")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    async def create_completion(self, messages: List[Dict[str, str]], max_tokens: int) -> Any:
        try:
            return await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens
            )
        except Exception as exc:
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    err_data = await exc.response.json()
                except Exception:
                    err_data = {"error": {"message": str(exc)}}
                if err_data.get("error", {}).get("code") == "invalid_api_key":
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid API key. Please verify your API key and try again."
                    )
            raise

    async def summarize_transcript(
        self,
        transcript: str,
        prompt: str,
        template_type: str,
        max_chunk_chars: int = 50000
    ) -> Tuple[str, int, int, float]:
        lines = transcript.split("\n")
        chunks = []
        current_chunk = []
        current_length = 0

        for line in lines:
            if current_length + len(line) > max_chunk_chars and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = current_chunk[-3:] if len(current_chunk) > 3 else []
                current_length = sum(len(l) for l in current_chunk)

            current_chunk.append(line)
            current_length += len(line)

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        if not chunks:
            return "", 0, 0, 0.0

        max_tokens = 3000 if template_type == "detailed_notes" else 1500
        sem = asyncio.Semaphore(5)

        async def process_chunk(index: int, chunk: str):
            async with sem:
                chunk_info = f"\n\n(Note: This is segment {index} of {len(chunks)} of the video transcript.)"
                chunk_prompt = f"{prompt}{chunk_info}\n\nTranscript Segment:\n{chunk}"
                response = await self.create_completion(
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that summarizes video transcripts accurately and clearly."},
                        {"role": "user", "content": chunk_prompt}
                    ],
                    max_tokens=max_tokens
                )
                c_summary = response.choices[0].message.content
                p_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
                c_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0
                cost = getattr(response.usage, "estimated_cost", 0.0) if response.usage else 0.0
                return index, c_summary, p_tokens, c_tokens, cost

        tasks = [process_chunk(idx, chunk) for idx, chunk in enumerate(chunks, start=1)]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])

        summaries = [res[1] for res in results]
        total_prompt_tokens = sum(res[2] for res in results)
        total_completion_tokens = sum(res[3] for res in results)
        total_cost = sum(res[4] for res in results)

        combined_summary = "\n\n---\n\n".join(summaries) if len(chunks) > 1 else summaries[0]
        return combined_summary, total_prompt_tokens, total_completion_tokens, total_cost
