"""Phase 4 personalized learning API: paths, lessons, exercises, reviews.

All endpoints go through the Pydantic-validated structured JSON pipeline:
the model is asked for JSON only, validated, retried once on failure, and a
persistent failure becomes HTTP 502 with the raw text attached — never
fabricated data.

The backend is stateless: the developer knowledge profile (known topics,
tech levels) lives in the client's localStorage and is sent with requests
as `skip_topics`. Server-side profiles are a later phase.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from llm.prompts import (
    EQUIVALENCE_GRADES,
    GOAL_DESCRIPTIONS,
    LEARN_EXERCISES_TEMPLATE,
    LEARN_PATH_TEMPLATE,
    LEARN_REVIEW_TEMPLATE,
    LEARN_TOPIC_TEMPLATE,
    LEVEL_NAMES,
    SYSTEM_PROMPT,
)
from llm.provider import AIProvider, get_provider
from llm.structured import StructuredOutputError, generate_json

router = APIRouter()

Experience = Literal["beginner", "intermediate", "advanced", "expert"]
Goal = Literal["basics", "productive", "migrate", "production", "interview"]
ExerciseKind = Literal["basic", "intermediate", "production", "migration"]
Verdict = Literal["correct", "partial", "incorrect"]


# ---------------------------------------------------------------------------
# Learning path
# ---------------------------------------------------------------------------


class KnownTech(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    version: Optional[str] = Field(default=None, max_length=40)


class LearnPathRequest(BaseModel):
    known: list[KnownTech] = Field(min_length=1, max_length=10)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    experience: Experience
    goal: Goal
    skip_topics: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Topic titles the developer already knows; excluded from the path.",
    )


class PathTopic(BaseModel):
    title: str
    known_equivalent: str = Field(
        default="",
        description="What this maps to in the developer's known stack, or '' when new.",
    )
    new_in_target: bool = False
    estimated_minutes: int = Field(ge=1, le=240)


class PathModule(BaseModel):
    title: str
    why_this_module: str
    topics: list[PathTopic] = Field(min_length=1)


class LearningPath(BaseModel):
    path_title: str
    modules: list[PathModule] = Field(min_length=1)


@router.post("/learn/path", response_model=LearningPath)
async def learn_path(
    req: LearnPathRequest, provider: AIProvider = Depends(get_provider)
) -> LearningPath:
    known_block = "\n".join(
        f"- {t.name}{' (' + t.version + ')' if t.version else ''}" for t in req.known
    )
    skip_block = (
        "The developer already knows these topics — do NOT include them "
        f"in the path:\n" + "\n".join(f"- {s}" for s in req.skip_topics)
        if req.skip_topics
        else "No topics are marked as known yet."
    )
    task = LEARN_PATH_TEMPLATE.format(
        known_block=known_block,
        target_tech=req.target_tech,
        target_version=f" ({req.target_version})" if req.target_version else "",
        experience=req.experience,
        goal_description=GOAL_DESCRIPTIONS[req.goal],
        skip_block=skip_block,
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, LearningPath)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


# ---------------------------------------------------------------------------
# Lesson for one topic at one level
# ---------------------------------------------------------------------------


class LearnTopicRequest(BaseModel):
    known: list[KnownTech] = Field(min_length=1, max_length=10)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    topic: str = Field(min_length=1, max_length=160)
    level: Literal[1, 2, 3, 4]


class Lesson(BaseModel):
    topic: str
    level: int
    level_name: str
    what_stays_same: str = ""
    what_changes: str
    why_different: str
    source_example: str
    target_example: str
    idiomatic_target: str
    new_capabilities: list[str] = Field(default_factory=list)
    production_notes: str = ""


@router.post("/learn/topic", response_model=Lesson)
async def learn_topic(
    req: LearnTopicRequest, provider: AIProvider = Depends(get_provider)
) -> Lesson:
    known_list = ", ".join(t.name for t in req.known)
    task = LEARN_TOPIC_TEMPLATE.format(
        known_list=known_list,
        target_tech=req.target_tech,
        target_version=f" ({req.target_version})" if req.target_version else "",
        topic=req.topic,
        level=req.level,
        level_name=LEVEL_NAMES[req.level],
    )
    try:
        lesson = await generate_json(provider, SYSTEM_PROMPT, task, Lesson)
        lesson.level = req.level
        lesson.level_name = LEVEL_NAMES[req.level]
        return lesson
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


# ---------------------------------------------------------------------------
# Exercises
# ---------------------------------------------------------------------------


class LearnExercisesRequest(BaseModel):
    known: list[KnownTech] = Field(min_length=1, max_length=10)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    topic: str = Field(min_length=1, max_length=160)
    level: Literal[1, 2, 3, 4]


class Exercise(BaseModel):
    kind: ExerciseKind
    title: str
    prompt: str
    starter_code: str = ""


class ExerciseSet(BaseModel):
    exercises: list[Exercise] = Field(min_length=1)


@router.post("/learn/exercises", response_model=ExerciseSet)
async def learn_exercises(
    req: LearnExercisesRequest, provider: AIProvider = Depends(get_provider)
) -> ExerciseSet:
    known_list = ", ".join(t.name for t in req.known)
    task = LEARN_EXERCISES_TEMPLATE.format(
        known_list=known_list,
        target_tech=req.target_tech,
        target_version=f" ({req.target_version})" if req.target_version else "",
        topic=req.topic,
        level=req.level,
        level_name=LEVEL_NAMES[req.level],
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, ExerciseSet)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


# ---------------------------------------------------------------------------
# Solution review
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    exercise_title: str = Field(min_length=1, max_length=160)
    exercise_prompt: str = Field(min_length=1, max_length=6000)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    solution: str = Field(min_length=1, max_length=12000)


class ExerciseReview(BaseModel):
    verdict: Verdict
    correct_parts: list[str] = Field(default_factory=list)
    incorrect_parts: list[str] = Field(default_factory=list)
    better_implementation: str
    best_practices: list[str] = Field(default_factory=list)


@router.post("/learn/review", response_model=ExerciseReview)
async def learn_review(
    req: ReviewRequest, provider: AIProvider = Depends(get_provider)
) -> ExerciseReview:
    task = LEARN_REVIEW_TEMPLATE.format(
        target_tech=req.target_tech,
        target_version=f" ({req.target_version})" if req.target_version else "",
        exercise_title=req.exercise_title,
        exercise_prompt=req.exercise_prompt,
        solution=req.solution,
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, ExerciseReview)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )
