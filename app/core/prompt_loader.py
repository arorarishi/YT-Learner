import os
import yaml
from typing import Dict, Optional

DEFAULT_PROMPTS = {
    "summary": "You are an expert summarizer. Please provide a comprehensive summary."
}


def load_prompt_templates(prompts_dir: Optional[str] = None) -> Dict[str, str]:
    if not prompts_dir:
        return DEFAULT_PROMPTS.copy()

    templates: Dict[str, str] = {}
    if not os.path.isdir(prompts_dir):
        return DEFAULT_PROMPTS.copy()

    for filename in os.listdir(prompts_dir):
        if not filename.endswith(".yaml"):
            continue

        path = os.path.join(prompts_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            template_name = filename.replace(".yaml", "")
            template_data = yaml.safe_load(raw)
            if isinstance(template_data, dict) and "prompt" in template_data:
                templates[template_name] = template_data["prompt"].strip()
            else:
                templates[template_name] = raw.strip()
            print(f"INFO: Loaded prompt template: {template_name}")
        except Exception as exc:
            print(f"Warning: Could not load prompt {filename}: {exc}")

    if not templates:
        return DEFAULT_PROMPTS.copy()

    return templates
