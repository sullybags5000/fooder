"""Pydantic models for structured LLM output and Fitbit payloads."""
from pydantic import BaseModel, Field
from typing import List, Optional


class FoodItem(BaseModel):
    name: str = Field(..., description="Specific dish name, e.g. 'grilled chicken breast'")
    portion: str = Field(..., description="Estimated portion, e.g. '150g' or '1 cup'")
    calories: float = Field(..., description="Estimated kcal")
    protein_g: float = Field(0, description="Protein in grams")
    carbs_g: float = Field(0, description="Carbs in grams")
    fat_g: float = Field(0, description="Fat in grams")


class MealAnalysis(BaseModel):
    """Top-level response from the vision LLM."""
    description: str = Field(..., description="One-line description of the meal")
    items: List[FoodItem]
    total_calories: float
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float
    confidence: float = Field(..., ge=0, le=1, description="0-1, how confident the model is")
    notes: Optional[str] = Field(None, description="Caveats, e.g. 'hidden oil not visible'")
