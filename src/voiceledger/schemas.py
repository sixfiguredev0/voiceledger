from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(StrictModel):
    kind: Literal["assign", "merge", "split", "bounds", "text", "mark", "reanalyze"]
    row_ids: list[str] = Field(default_factory=list, max_length=20000)
    speaker_id: str | None = None
    name: str | None = Field(default=None, max_length=120)
    source_speaker_id: str | None = None
    scope: Literal["selected", "cluster"] = "selected"
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    split_at_ms: int | None = Field(default=None, ge=0)
    text: str | None = Field(default=None, max_length=20000)
    right_text: str | None = Field(default=None, max_length=20000)
    category: Literal["speech", "noise", "irrelevant", "overlap", "uncertain"] | None = None
    min_speakers: int | None = Field(default=None, ge=1, le=100)
    max_speakers: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "assign" and not (self.speaker_id or (self.name and self.name.strip())):
            raise ValueError("Choose an existing speaker or enter a name.")
        if self.kind == "merge" and not (self.source_speaker_id and self.speaker_id):
            raise ValueError("Choose both speakers to merge.")
        if self.kind in ("bounds", "reanalyze"):
            if self.start_ms is None or self.end_ms is None or self.end_ms <= self.start_ms:
                raise ValueError("Choose a valid start and end time.")
        if self.kind == "split" and self.split_at_ms is None:
            raise ValueError("Choose the split time.")
        if self.kind == "text" and self.text is None:
            raise ValueError("Provide replacement text.")
        if self.kind == "mark" and self.category is None:
            raise ValueError("Choose a region category.")
        if self.min_speakers and self.max_speakers and self.min_speakers > self.max_speakers:
            raise ValueError("The minimum speaker count exceeds the maximum.")
        return self


class PreviewRequest(StrictModel):
    recording_id: str
    base_revision: int
    actions: list[Action] = Field(min_length=1, max_length=20)


class AssistantRequest(StrictModel):
    recording_id: str
    base_revision: int
    row_ids: list[str] = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=4000)


class AssistantResponse(StrictModel):
    explanation: str
    clarification: str | None = None
    actions: list[Action] = Field(default_factory=list, max_length=20)


class JobRequest(StrictModel):
    recording_id: str
    mode: Literal["fast", "balanced", "accuracy"] = "balanced"
    language: Literal["bg", "en", "auto"] = "bg"
