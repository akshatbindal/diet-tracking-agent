# diet_tracker_agent/agent.py

from google.adk.agents import LlmAgent
from diet_tracker_agent.tools import (
    store_food_data,
    search_food_by_time,
    search_relevant_food_by_natural_language_query,
    get_food_data_by_image_id,
)
from diet_tracker_agent.callbacks import modify_image_data_in_history
import os
from settings import get_settings
from google.adk.planners import BuiltInPlanner
from google.genai import types

SETTINGS = get_settings()
os.environ["GOOGLE_CLOUD_PROJECT"] = SETTINGS.GCLOUD_PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = SETTINGS.GCLOUD_LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

# Get the code file directory path and read the task prompt file
current_dir = os.path.dirname(os.path.abspath(__file__))
prompt_path = os.path.join(current_dir, "task_prompt.md")
with open(prompt_path, "r") as file:
    task_prompt = file.read()

root_agent = LlmAgent(
    name="diet_tracker_agent",
    model="gemini-2.5-flash",
    description=(
        "Personal diet tracker agent to help users track their food intake, analyze meals, calculate calories and nutrition, and answer dietary queries."
    ),
    instruction=task_prompt,
    tools=[
        store_food_data,
        get_food_data_by_image_id,
        search_food_by_time,
        search_relevant_food_by_natural_language_query,
    ],
    before_model_callback=modify_image_data_in_history,
)