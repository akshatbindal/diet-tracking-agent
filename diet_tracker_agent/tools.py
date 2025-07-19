# diet_tracker_agent/tools.py

import datetime
from typing import Dict, List, Any
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1 import FieldFilter
from google.cloud.firestore_v1.base_query import And
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from settings import get_settings
from google import genai

SETTINGS = get_settings()
DB_CLIENT = firestore.Client(project=SETTINGS.GCLOUD_PROJECT_ID)
COLLECTION = DB_CLIENT.collection(SETTINGS.DB_COLLECTION_NAME)
GENAI_CLIENT = genai.Client(vertexai=True, location=SETTINGS.GCLOUD_LOCATION, project=SETTINGS.GCLOUD_PROJECT_ID)
EMBEDDING_DIMENSION = 768
EMBEDDING_FIELD_NAME = "embedding"

FOOD_DESC_FORMAT = """
Food Items: {food_items}
Timestamp: {timestamp}
Nutrition Summary: {nutrition_summary}
Food Image ID: {image_id}
User ID: {user_id}
"""


def sanitize_image_id(image_id: str) -> str:
    """Sanitize image ID by removing any leading/trailing whitespace."""
    if image_id.startswith("[IMAGE-"):
        image_id = image_id.split("ID ")[1].split("]")[0]
    return image_id.strip()


def extract_food_and_nutrition_from_image(image_bytes: bytes, mime_type: str) -> tuple[list, dict]:
    """
    Use Gemini to recognize foods and estimate nutrition from an image.
    Returns (recognized_foods, nutrition_summary_dict)
    """
    prompt = (
        "You are a nutritionist. Given a food image, list the food items you see and estimate the total nutrition (calories, protein, carbs, fat, etc.) in a dictionary."
        " Respond in JSON with keys: 'food_items' (list of strings), 'nutrition_summary' (dict with keys: calories, protein, carbs, fat, etc.)."
    )
    image_part = genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    contents = genai.types.Content(role="user", parts=[image_part, genai.types.Part.from_text(prompt)])
    response = GENAI_CLIENT.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=genai.types.GenerateContentConfig(system_instruction=prompt),
    )
    text = response.candidates[0].content.parts[0].text
    import json
    try:
        result = json.loads(text)
        food_items = result.get("food_items", [])
        nutrition_summary = result.get("nutrition_summary", {})
        return food_items, nutrition_summary
    except Exception:
        return [], {}


def store_food_data(
    image_id: str,
    image_bytes: bytes,
    mime_type: str,
    user_id: str,
    timestamp: str = None,
) -> str:
    """
    Store food data in the database. Uses Gemini to extract food/nutrition from image.
    Args:
        image_id (str): Unique image identifier.
        image_bytes (bytes): Raw image data.
        mime_type (str): MIME type of the image.
        user_id (str): User identifier.
        timestamp (str, optional): ISO format timestamp. If None, uses current UTC time.
    Returns:
        str: Success message with image_id.
    """
    try:
        image_id = sanitize_image_id(image_id)
        if not timestamp:
            timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        # Check if already exists
        doc = get_food_data_by_image_id(image_id)
        if doc:
            return f"Meal with ID {image_id} already exists"
        # Use Gemini to extract food/nutrition
        food_items, nutrition_summary = extract_food_and_nutrition_from_image(image_bytes, mime_type)
        # Create embedding for vector search
        result = GENAI_CLIENT.models.embed_content(
            model="text-embedding-004",
            contents=FOOD_DESC_FORMAT.format(
                food_items=food_items,
                timestamp=timestamp,
                nutrition_summary=nutrition_summary,
                image_id=image_id,
                user_id=user_id,
            ),
        )
        embedding = result.embeddings[0].values
        doc = {
            "image_id": image_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "recognized_foods": food_items,
            "nutrition_summary": nutrition_summary,
            EMBEDDING_FIELD_NAME: Vector(embedding),
        }
        COLLECTION.add(doc)
        return f"Meal stored successfully with ID: {image_id}"
    except Exception as e:
        raise Exception(f"Failed to store meal: {str(e)}")


def search_food_by_time(
    user_id: str,
    start_time: str,
    end_time: str,
) -> str:
    """
    Query meals by time range and user. Returns nutrition summary and foods.
    Args:
        user_id (str): User identifier.
        start_time (str): Start ISO timestamp.
        end_time (str): End ISO timestamp.
    Returns:
        str: List of meals and nutrition summaries.
    """
    try:
        filters = [
            FieldFilter("user_id", "==", user_id),
            FieldFilter("timestamp", ">=", start_time),
            FieldFilter("timestamp", "<=", end_time),
        ]
        composite_filter = And(filters=filters)
        query = COLLECTION.where(filter=composite_filter)
        result = "Meals in time range:\n"
        for doc in query.stream():
            data = doc.to_dict()
            data.pop(EMBEDDING_FIELD_NAME, None)
            result += f"\n{FOOD_DESC_FORMAT.format(**data)}"
        return result
    except Exception as e:
        raise Exception(f"Error querying meals: {str(e)}")


def search_relevant_food_by_natural_language_query(
    user_id: str,
    query_text: str,
    limit: int = 5,
) -> str:
    """
    Vector search for meals by query (e.g., "how much protein did I eat yesterday?").
    Args:
        user_id (str): User identifier.
        query_text (str): Search query.
        limit (int): Max results.
    Returns:
        str: List of relevant meals.
    """
    try:
        # Generate embedding for the query text
        result = GENAI_CLIENT.models.embed_content(
            model="text-embedding-004", contents=query_text
        )
        query_embedding = result.embeddings[0].values
        vector_query = COLLECTION.find_nearest(
            vector_field=EMBEDDING_FIELD_NAME,
            query_vector=Vector(query_embedding),
            distance_measure=DistanceMeasure.EUCLIDEAN,
            limit=limit,
        )
        result_str = "Relevant meals:\n"
        for doc in vector_query.stream():
            data = doc.to_dict()
            data.pop(EMBEDDING_FIELD_NAME, None)
            result_str += f"\n{FOOD_DESC_FORMAT.format(**data)}"
        return result_str
    except Exception as e:
        raise Exception(f"Error searching meals: {str(e)}")


def get_food_data_by_image_id(image_id: str) -> Dict[str, Any]:
    """
    Retrieve meal data from the database using the image_id.
    Args:
        image_id (str): Unique image identifier.
    Returns:
        Dict[str, Any]: Meal data dict, or empty dict if not found.
    """
    image_id = sanitize_image_id(image_id)
    query = COLLECTION.where(filter=FieldFilter("image_id", "==", image_id)).limit(1)
    docs = list(query.stream())
    if not docs:
        return {}
    doc_data = docs[0].to_dict()
    doc_data.pop(EMBEDDING_FIELD_NAME, None)
    return doc_data