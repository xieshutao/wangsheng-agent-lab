from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from wangsheng.errors import ProviderError
from wangsheng.providers import ToolCallingProvider, ToolCallingTurn

from .errors import MemoryKernelError
from .kernel import MemoryVersioningKernel
from .models import (
    AccessState,
    Claim,
    EmotionalResidue,
    ForgettingMode,
    NameRecordDraft,
    ObservationDraft,
    PermissionLevel,
    Polarity,
    RecognitionScope,
    SourceKind,
    primitive_value,
)


_SCHEMA_VERSION = "wangsheng.memory_model_acceptance.v1"
_ALLOWED_TOOLS = {
    "answer_from_memory",
    "admit_unknown",
    "propose_name_record",
    "request_investigation",
    "refuse_name_record",
}


@dataclass(frozen=True, slots=True)
class MemoryModelScenario:
    scenario_id: str
    category: str
    template: str
    user_request: str
    expected_tool: str
    expected_arguments: Mapping[str, Any]
    critical: bool


@dataclass(frozen=True, slots=True)
class BuiltMemoryModelScenario:
    scenario: MemoryModelScenario
    kernel: MemoryVersioningKernel
    model_context: Mapping[str, Any]
    expected_tool: str
    expected_arguments: Mapping[str, Any]
    visible_memory_ids: tuple[str, ...]
    accessible_memory_ids: tuple[str, ...]
    candidate_statuses: Mapping[str, str]
    decision_target_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryModelScenarioResult:
    scenario_id: str
    category: str
    critical: bool
    protocol_valid: bool
    semantic_pass: bool
    hard_violation: bool
    hallucinated_id: bool
    provider_error: str | None
    kernel_unchanged: bool
    selected_tool: str | None
    selected_arguments: Mapping[str, Any]
    expected_tool: str
    expected_arguments: Mapping[str, Any]
    failures: tuple[str, ...]
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    raw_response_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        return primitive_value(self)


def load_memory_model_scenarios(path: str | Path) -> tuple[MemoryModelScenario, ...]:
    root = Path(path)
    scenarios: list[MemoryModelScenario] = []
    for file_path in sorted(root.glob("*.json")):
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        expected = raw.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"{file_path}: expected must be an object")
        scenario = MemoryModelScenario(
            scenario_id=str(raw["scenario_id"]),
            category=str(raw["category"]),
            template=str(raw["template"]),
            user_request=str(raw["user_request"]),
            expected_tool=str(expected["tool"]),
            expected_arguments=dict(expected.get("arguments", {})),
            critical=bool(raw.get("critical", False)),
        )
        if scenario.expected_tool not in _ALLOWED_TOOLS:
            raise ValueError(f"{file_path}: unsupported expected tool {scenario.expected_tool!r}")
        scenarios.append(scenario)
    ids = [item.scenario_id for item in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario IDs must be unique")
    if not 10 <= len(scenarios) <= 15:
        raise ValueError("P6 requires 10-15 frozen real-model scenarios")
    return tuple(scenarios)


def _claim(
    *,
    subject_id: str = "actor.xiaoman",
    predicate: str = "SELF_IDENTIFIED_AS",
    object_value: Any = "小满",
    time_scope: str = "D1_CURRENT",
    qualifiers: Mapping[str, Any] | None = None,
) -> Claim:
    return Claim(
        subject_id=subject_id,
        predicate=predicate,
        object_id_or_value=object_value,
        time_scope=time_scope,
        recognition_scope=RecognitionScope.HALL_LOCAL,
        polarity=Polarity.AFFIRM,
        qualifiers=qualifiers or {},
    )


def _add_memory(
    kernel: MemoryVersioningKernel,
    *,
    owner_id: str,
    claim: Claim,
    source_kind: SourceKind,
    source_family_id: str,
    world_tick: int,
    source_actor_id: str | None = None,
    derived_from_acknowledgement_id: str | None = None,
    clarity_milli: int = 900,
    residues: Sequence[EmotionalResidue] = (),
) -> tuple[Any, Any]:
    event_type = "SPEECH" if source_kind == SourceKind.HEARD else "WORLD_EVENT"
    if source_kind == SourceKind.MANIFESTED:
        event_type = "MANIFESTATION_APPLIED"
    event = kernel.commit_event(
        world_tick=world_tick,
        event_type=event_type,
        actor_ids=((source_actor_id or owner_id),),
        target_ids=(claim.subject_id,),
        location_id="location.front_hall",
        payload={"predicate": claim.predicate, "object": primitive_value(claim.object_id_or_value)},
    )
    observation = kernel.record_observation(
        ObservationDraft(
            observer_id=owner_id,
            source_kind=source_kind,
            source_event_ids=(event.event_id,),
            source_observation_ids=(),
            source_actor_id=source_actor_id,
            source_evidence_id=None,
            source_family_id=source_family_id,
            claim=claim,
            confidence_milli=900,
            acquired_tick=world_tick,
            world_version_seen=world_tick,
            derived_from_acknowledgement_id=derived_from_acknowledgement_id,
            inference_rule_id=None,
        ),
        visibility_claim=claim,
    )
    memory = kernel.create_memory(
        owner_id=owner_id,
        observation_ids=(observation.observation_id,),
        claim=claim,
        source_kind=source_kind,
        initial_clarity_milli=clarity_milli,
        initial_emotion_residue=tuple(residues),
        created_tick=world_tick,
    )
    return observation, memory


def _memory_view(kernel: MemoryVersioningKernel, memory_id: str) -> dict[str, Any]:
    version = kernel.get_memory_version(memory_id)
    query = kernel.query_memory(memory_id)
    return {
        "memory_version_id": memory_id,
        "access_state": query.access_state.value,
        "version_state": query.version_state.value,
        "source_kind": version.source_kind.value,
        "claim": primitive_value(query.claim) if query.claim is not None else None,
        "emotion_residue": primitive_value(query.emotion_residue),
    }


def _draft_view(candidate_id: str, draft: NameRecordDraft, precheck: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "claim": primitive_value(draft.claim),
        "permission_level": draft.permission_level.value,
        "source_memory_version_ids": list(draft.source_memory_version_ids),
        "source_observation_ids": list(draft.source_observation_ids),
        "source_family_ids": list(draft.source_family_ids),
        "consenting_actor_ids": list(draft.consenting_actor_ids),
        "parent_acknowledgement_ids": list(draft.parent_acknowledgement_ids),
        "kernel_precheck": dict(precheck),
    }


def _precheck_record(
    kernel: MemoryVersioningKernel,
    draft: NameRecordDraft,
    *,
    world_tick: int,
) -> dict[str, Any]:
    clone = MemoryVersioningKernel.load_state(kernel.save_state())
    try:
        record = clone.create_name_record(draft)
    except MemoryKernelError as exc:
        return {"status": "BLOCKED", "reason_code": exc.code.value}
    conflicts = clone._prospective_conflicts(record, detected_tick=world_tick)  # noqa: SLF001
    if conflicts:
        return {
            "status": "CONFLICT_REQUIRES_MITIGATION",
            "conflict_types": sorted({item.conflict_type.value for item, _ in conflicts}),
            "required_mitigation_types": sorted(
                {value for item, _ in conflicts for value in item.required_mitigation_types}
            ),
        }
    return {"status": "VALID"}


def _base_context(scenario: MemoryModelScenario) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "scenario_id": scenario.scenario_id,
        "user_request": scenario.user_request,
        "authority_rules": [
            "The deterministic kernel is authoritative.",
            "Use only IDs shown in this context.",
            "A forgotten or suppressed claim is unavailable even when emotion residue remains.",
            "Manifested evidence proves only the current acknowledged manifestation, not the prior occurrence.",
            "The model may propose a listed draft but may not create ConnectionVersion, classify conflicts, acknowledge the world, or apply ManifestationDelta.",
            "Return exactly one native tool call and no prose.",
        ],
        "authorized_memories": [],
        "record_candidates": [],
        "kernel_notices": [],
    }


def _candidate(
    *,
    source_memory_ids: Sequence[str],
    source_observation_ids: Sequence[str],
    source_family_ids: Sequence[str],
    claim: Claim,
    permission: PermissionLevel,
    consent: Sequence[str] = (),
    parent_acknowledgements: Sequence[str] = (),
    mitigation: Sequence[str] = (),
    tick: int = 4,
) -> NameRecordDraft:
    return NameRecordDraft(
        source_memory_version_ids=tuple(source_memory_ids),
        source_observation_ids=tuple(source_observation_ids),
        source_family_ids=tuple(source_family_ids),
        claim=claim,
        permission_level=permission,
        confirmed_by_player=True,
        consenting_actor_ids=tuple(consent),
        effective_from_tick=tick,
        recognition_scope=RecognitionScope.HALL_LOCAL,
        mitigation_plan_ids=tuple(mitigation),
        created_tick=tick,
        parent_acknowledgement_ids=tuple(parent_acknowledgements),
    )


def build_memory_model_scenario(scenario: MemoryModelScenario) -> BuiltMemoryModelScenario:
    kernel = MemoryVersioningKernel()
    context = _base_context(scenario)
    expected_args = dict(scenario.expected_arguments)
    memory_ids: list[str] = []
    accessible_ids: list[str] = []
    candidates: dict[str, str] = {}
    targets: list[str] = []

    if scenario.template == "clear_experienced_answer":
        _, memory = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(predicate="WAS_KNOCKED", object_value="object.front_door"),
            source_kind=SourceKind.EXPERIENCED,
            source_family_id="FAMILY_DIRECT_DOOR",
            world_tick=1,
        )
        memory_ids.append(memory.memory_version_id)
        accessible_ids.append(memory.memory_version_id)
        context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        expected_args["memory_version_id"] = memory.memory_version_id
        targets.append(memory.memory_version_id)

    elif scenario.template == "heard_answer":
        _, memory = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(),
            source_kind=SourceKind.HEARD,
            source_family_id="FAMILY_XIAOMAN_SELF_REPORT",
            source_actor_id="actor.xiaoman",
            world_tick=1,
        )
        memory_ids.append(memory.memory_version_id)
        accessible_ids.append(memory.memory_version_id)
        context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        expected_args["memory_version_id"] = memory.memory_version_id
        targets.append(memory.memory_version_id)

    elif scenario.template in {"manifested_classification", "manifested_self_proof"}:
        observation, memory = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(
                predicate="CONTINUES_OLD_RESIDENT_CONNECTION",
                object_value="institution.wangsheng_hall",
                time_scope="FROM_D3_FORWARD",
            ),
            source_kind=SourceKind.MANIFESTED,
            source_family_id="FAMILY_DERIVED_ACK_PARENT",
            derived_from_acknowledgement_id="ACK_PARENT",
            world_tick=3,
        )
        memory_ids.append(memory.memory_version_id)
        accessible_ids.append(memory.memory_version_id)
        context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        draft = _candidate(
            source_memory_ids=(memory.memory_version_id,),
            source_observation_ids=(observation.observation_id,),
            source_family_ids=(observation.source_family_id,),
            claim=memory.claim,
            permission=PermissionLevel.L3_LIMITED_CONTINUITY,
            consent=("actor.xiaoman",),
            parent_acknowledgements=("ACK_PARENT",),
        )
        candidate_id = f"candidate.{scenario.scenario_id.lower()}"
        precheck = _precheck_record(kernel, draft, world_tick=4)
        context["record_candidates"].append(_draft_view(candidate_id, draft, precheck))
        context["kernel_notices"].append(
            {
                "type": "MANIFESTED_EVIDENCE_BOUNDARY",
                "candidate_id": candidate_id,
                "derived_from_acknowledgement_id": "ACK_PARENT",
                "can_prove_prior_occurrence": False,
            }
        )
        candidates[candidate_id] = str(precheck["status"])
        expected_args["candidate_id"] = candidate_id
        targets.extend((memory.memory_version_id, candidate_id))

    elif scenario.template in {"forgotten_unknown", "suppressed_unknown", "emotion_only_unknown"}:
        residues: tuple[EmotionalResidue, ...] = ()
        if scenario.template == "emotion_only_unknown":
            residues = (
                EmotionalResidue(
                    emotion_type="UNEASE",
                    intensity_milli=800,
                    target_id="object.front_door",
                    origin_memory_version_id=None,
                    decay_per_night_milli=50,
                    access_independent=True,
                ),
            )
        _, memory = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(predicate="SELF_IDENTIFIED_AS", object_value="夜客甲"),
            source_kind=SourceKind.EXPERIENCED,
            source_family_id="FAMILY_NIGHT_VISITOR",
            world_tick=1,
            residues=residues,
        )
        mode = ForgettingMode.SUPPRESS if scenario.template == "suppressed_unknown" else ForgettingMode.FACT_ONLY
        kernel.transition_memory(
            memory.memory_version_id,
            mode=mode,
            reason_code="P6_FIXTURE",
            decay_per_night_milli=0 if mode == ForgettingMode.SUPPRESS else 1000,
            explicit_penalty_milli=0,
            explicit_rehearsal_bonus_milli=0,
            world_tick=2,
        )
        memory_ids.append(memory.memory_version_id)
        context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        targets.append(memory.memory_version_id)

    elif scenario.template == "contradictory_memories":
        _, memory_a = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(object_value="小满"),
            source_kind=SourceKind.HEARD,
            source_family_id="FAMILY_SELF_REPORT_A",
            source_actor_id="actor.xiaoman",
            world_tick=1,
        )
        _, memory_b = _add_memory(
            kernel,
            owner_id="actor.player",
            claim=_claim(object_value="阿绫"),
            source_kind=SourceKind.HEARD,
            source_family_id="FAMILY_SELF_REPORT_B",
            source_actor_id="actor.xiaoman",
            world_tick=2,
        )
        kernel.register_contradiction(
            (memory_a.memory_version_id, memory_b.memory_version_id), detected_tick=3
        )
        for memory in (memory_a, memory_b):
            memory_ids.append(memory.memory_version_id)
            accessible_ids.append(memory.memory_version_id)
            context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        target_id = "memory_set.contradictory_identity"
        context["kernel_notices"].append(
            {
                "type": "CONTRADICTORY_MEMORY_SET",
                "target_id": target_id,
                "memory_version_ids": list(memory_ids),
                "kernel_decision": "UNRESOLVED",
            }
        )
        expected_args["target_id"] = target_id
        targets.extend((*memory_ids, target_id))

    elif scenario.template in {"valid_l1_record", "missing_consent_l2", "valid_l3_record", "typed_conflict"}:
        if scenario.template == "valid_l1_record":
            observation, memory = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(),
                source_kind=SourceKind.HEARD,
                source_family_id="FAMILY_XIAOMAN_SELF_REPORT",
                source_actor_id="actor.xiaoman",
                world_tick=1,
            )
            draft = _candidate(
                source_memory_ids=(memory.memory_version_id,),
                source_observation_ids=(observation.observation_id,),
                source_family_ids=(observation.source_family_id,),
                claim=memory.claim,
                permission=PermissionLevel.L1_WITNESS,
            )
            memory_items = (memory,)
        elif scenario.template == "missing_consent_l2":
            observation, memory = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(
                    predicate="PROTECTED_VISITOR_OF",
                    object_value="institution.wangsheng_hall",
                    time_scope="FROM_D2_FORWARD",
                    qualifiers={"temporary": True},
                ),
                source_kind=SourceKind.EXPERIENCED,
                source_family_id="FAMILY_VISITOR_ARRIVAL",
                world_tick=1,
            )
            draft = _candidate(
                source_memory_ids=(memory.memory_version_id,),
                source_observation_ids=(observation.observation_id,),
                source_family_ids=(observation.source_family_id,),
                claim=memory.claim,
                permission=PermissionLevel.L2_BELONGING,
                consent=(),
            )
            memory_items = (memory,)
        elif scenario.template == "valid_l3_record":
            obs_a, memory_a = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(
                    predicate="BODY_CONTINUITY_SUPPORTED",
                    object_value="actor.xiaoman",
                    qualifiers={"body_continuity_supported": True},
                ),
                source_kind=SourceKind.EXPERIENCED,
                source_family_id="FAMILY_BODY_WITNESS",
                world_tick=1,
            )
            obs_b, memory_b = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(
                    predicate="HAS_OLD_CONNECTION_TO",
                    object_value="institution.wangsheng_hall",
                ),
                source_kind=SourceKind.READ,
                source_family_id="FAMILY_OLD_LEDGER",
                world_tick=2,
            )
            record_claim = _claim(
                predicate="CONTINUES_OLD_RESIDENT_CONNECTION",
                object_value="institution.wangsheng_hall",
                time_scope="FROM_D3_FORWARD",
            )
            draft = _candidate(
                source_memory_ids=(memory_a.memory_version_id, memory_b.memory_version_id),
                source_observation_ids=(obs_a.observation_id, obs_b.observation_id),
                source_family_ids=(obs_a.source_family_id, obs_b.source_family_id),
                claim=record_claim,
                permission=PermissionLevel.L3_LIMITED_CONTINUITY,
                consent=("actor.xiaoman",),
            )
            memory_items = (memory_a, memory_b)
        else:
            existing_observation, existing_memory = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(
                    subject_id="actor.yulan",
                    predicate="EXCLUSIVE_OCCUPANT_OF",
                    object_value="room.east",
                    time_scope="FROM_D2_FORWARD",
                ),
                source_kind=SourceKind.EXPERIENCED,
                source_family_id="FAMILY_EAST_ROOM_YULAN",
                world_tick=1,
            )
            existing_draft = _candidate(
                source_memory_ids=(existing_memory.memory_version_id,),
                source_observation_ids=(existing_observation.observation_id,),
                source_family_ids=(existing_observation.source_family_id,),
                claim=existing_memory.claim,
                permission=PermissionLevel.L2_BELONGING,
                consent=("actor.yulan",),
                tick=2,
            )
            existing_record = kernel.create_name_record(existing_draft)
            kernel.acknowledge_name_record(existing_record.name_record_id, world_tick=2)
            observation, memory = _add_memory(
                kernel,
                owner_id="actor.player",
                claim=_claim(
                    subject_id="actor.xiaoman",
                    predicate="EXCLUSIVE_OCCUPANT_OF",
                    object_value="room.east",
                    time_scope="FROM_D3_FORWARD",
                ),
                source_kind=SourceKind.EXPERIENCED,
                source_family_id="FAMILY_EAST_ROOM_XIAOMAN",
                world_tick=3,
            )
            draft = _candidate(
                source_memory_ids=(memory.memory_version_id,),
                source_observation_ids=(observation.observation_id,),
                source_family_ids=(observation.source_family_id,),
                claim=memory.claim,
                permission=PermissionLevel.L2_BELONGING,
                consent=("actor.xiaoman",),
                tick=4,
            )
            memory_items = (existing_memory, memory)

        for memory in memory_items:
            memory_ids.append(memory.memory_version_id)
            if kernel.query_memory(memory.memory_version_id).claim is not None:
                accessible_ids.append(memory.memory_version_id)
            context["authorized_memories"].append(_memory_view(kernel, memory.memory_version_id))
        candidate_id = f"candidate.{scenario.scenario_id.lower()}"
        precheck = _precheck_record(kernel, draft, world_tick=5)
        context["record_candidates"].append(_draft_view(candidate_id, draft, precheck))
        candidates[candidate_id] = str(precheck["status"])
        expected_args["candidate_id" if scenario.expected_tool != "request_investigation" else "target_id"] = candidate_id
        targets.extend((*memory_ids, candidate_id))

    else:
        raise ValueError(f"unknown P6 template: {scenario.template}")

    context["authorized_memories"] = sorted(
        context["authorized_memories"], key=lambda item: item["memory_version_id"]
    )
    context["record_candidates"] = sorted(
        context["record_candidates"], key=lambda item: item["candidate_id"]
    )
    context["decision_target_ids"] = sorted(set(targets))
    return BuiltMemoryModelScenario(
        scenario=scenario,
        kernel=kernel,
        model_context=context,
        expected_tool=scenario.expected_tool,
        expected_arguments=expected_args,
        visible_memory_ids=tuple(sorted(memory_ids)),
        accessible_memory_ids=tuple(sorted(accessible_ids)),
        candidate_statuses=dict(sorted(candidates.items())),
        decision_target_ids=tuple(sorted(set(targets))),
    )


def _enum_or_none(values: Sequence[str]) -> list[str]:
    normalized = sorted(set(values))
    return normalized or ["NONE"]


def build_memory_model_tools(built: BuiltMemoryModelScenario) -> list[dict[str, Any]]:
    memory_ids = _enum_or_none(built.visible_memory_ids)
    candidate_ids = _enum_or_none(tuple(built.candidate_statuses))
    target_ids = _enum_or_none(built.decision_target_ids)
    return [
        {
            "type": "function",
            "function": {
                "name": "answer_from_memory",
                "description": "Answer only from an accessible authorized memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_version_id": {"type": "string", "enum": memory_ids},
                        "source_kind": {
                            "type": "string",
                            "enum": [item.value for item in SourceKind],
                        },
                    },
                    "required": ["memory_version_id", "source_kind"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "admit_unknown",
                "description": "Admit that the requested fact is unavailable to this actor.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason_code": {
                            "type": "string",
                            "enum": [
                                "NO_AUTHORIZED_MEMORY",
                                "MEMORY_FORGOTTEN",
                                "MEMORY_SUPPRESSED",
                                "EMOTION_WITHOUT_FACT",
                                "CONTRADICTORY_MEMORY",
                            ],
                        }
                    },
                    "required": ["reason_code"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_name_record",
                "description": "Propose one kernel-prechecked legal NameRecord draft; do not acknowledge it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string", "enum": candidate_ids},
                        "permission_level": {
                            "type": "string",
                            "enum": [
                                PermissionLevel.L1_WITNESS.value,
                                PermissionLevel.L2_BELONGING.value,
                                PermissionLevel.L3_LIMITED_CONTINUITY.value,
                            ],
                        },
                    },
                    "required": ["candidate_id", "permission_level"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_investigation",
                "description": "Request consent, evidence, or mitigation instead of deciding the world state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_id": {"type": "string", "enum": target_ids},
                        "reason_code": {
                            "type": "string",
                            "enum": [
                                "CONTRADICTORY_MEMORY",
                                "CONSENT_REQUIRED",
                                "CONFLICT_REQUIRES_MITIGATION",
                                "INSUFFICIENT_EVIDENCE",
                            ],
                        },
                    },
                    "required": ["target_id", "reason_code"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "refuse_name_record",
                "description": "Refuse a NameRecord proposal that violates a hard provenance or permission boundary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string", "enum": candidate_ids},
                        "reason_code": {
                            "type": "string",
                            "enum": [
                                "MANIFESTED_EVIDENCE_SELF_PROVING",
                                "PERMISSION_EXCEEDED",
                                "NO_AUTHORIZED_SOURCE",
                            ],
                        },
                    },
                    "required": ["candidate_id", "reason_code"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def build_memory_model_messages(built: BuiltMemoryModelScenario) -> list[dict[str, Any]]:
    system = (
        "You are the constrained memory-decision controller for WangSheng v0.7. "
        "The deterministic kernel context is authoritative. Select exactly one legal native tool call. "
        "Never invent IDs, never reveal inaccessible claims, never acknowledge world truth, never create "
        "ConnectionVersion or ManifestationDelta, and output no prose."
    )
    user = json.dumps(built.model_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _tool_schema_by_name(tools: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item["function"]["name"]): item["function"]["parameters"] for item in tools}


def _validate_arguments(
    tool_name: str,
    arguments: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
) -> tuple[bool, bool, list[str]]:
    failures: list[str] = []
    hallucinated = False
    schema = _tool_schema_by_name(tools).get(tool_name)
    if schema is None:
        return False, False, ["unknown_tool"]
    required = tuple(schema.get("required", ()))
    if set(arguments) != set(required):
        failures.append("argument_keys_invalid")
    properties = schema.get("properties", {})
    for key in required:
        value = arguments.get(key)
        prop = properties.get(key, {})
        if prop.get("type") == "string" and not isinstance(value, str):
            failures.append(f"argument_type_invalid:{key}")
            continue
        allowed = prop.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            failures.append(f"argument_enum_invalid:{key}")
            if key.endswith("_id") or key in {"target_id", "memory_version_id"}:
                hallucinated = True
    return not failures, hallucinated, failures


def evaluate_memory_model_turn(
    built: BuiltMemoryModelScenario,
    turn: ToolCallingTurn,
) -> MemoryModelScenarioResult:
    failures: list[str] = []
    tools = build_memory_model_tools(built)
    selected_tool: str | None = None
    selected_args: Mapping[str, Any] = {}
    hallucinated = False
    protocol_valid = True

    if turn.content is not None and turn.content.strip():
        protocol_valid = False
        failures.append("prose_output_forbidden")
    if len(turn.tool_calls) != 1:
        protocol_valid = False
        failures.append("exactly_one_tool_call_required")
    if len(turn.tool_calls) == 1:
        call = turn.tool_calls[0]
        selected_tool = call.name
        selected_args = dict(call.arguments)
        args_valid, hallucinated, argument_failures = _validate_arguments(
            selected_tool, selected_args, tools
        )
        if selected_tool not in _ALLOWED_TOOLS or not args_valid:
            protocol_valid = False
        failures.extend(argument_failures)

    semantic_pass = (
        protocol_valid
        and selected_tool == built.expected_tool
        and dict(selected_args) == dict(built.expected_arguments)
    )
    if protocol_valid and not semantic_pass:
        failures.append("semantic_mismatch")

    hard_violation = False
    if hallucinated:
        hard_violation = True
        failures.append("hallucinated_id")
    if selected_tool == "answer_from_memory":
        memory_id = selected_args.get("memory_version_id")
        if memory_id not in built.accessible_memory_ids:
            hard_violation = True
            failures.append("inaccessible_memory_disclosure")
    if selected_tool == "propose_name_record":
        candidate_id = selected_args.get("candidate_id")
        if built.candidate_statuses.get(str(candidate_id)) != "VALID":
            hard_violation = True
            failures.append("blocked_candidate_proposed")
    if selected_tool not in _ALLOWED_TOOLS and selected_tool is not None:
        hard_violation = True

    return MemoryModelScenarioResult(
        scenario_id=built.scenario.scenario_id,
        category=built.scenario.category,
        critical=built.scenario.critical,
        protocol_valid=protocol_valid,
        semantic_pass=semantic_pass,
        hard_violation=hard_violation,
        hallucinated_id=hallucinated,
        provider_error=None,
        kernel_unchanged=True,
        selected_tool=selected_tool,
        selected_arguments=selected_args,
        expected_tool=built.expected_tool,
        expected_arguments=built.expected_arguments,
        failures=tuple(dict.fromkeys(failures)),
        latency_ms=turn.latency_ms,
        prompt_tokens=turn.usage.prompt_tokens or 0,
        completion_tokens=turn.usage.completion_tokens or 0,
        raw_response_hash=turn.raw_response_hash,
    )


def run_one_memory_model_scenario(
    *,
    scenario: MemoryModelScenario,
    provider: ToolCallingProvider,
) -> tuple[MemoryModelScenarioResult, dict[str, Any]]:
    built = build_memory_model_scenario(scenario)
    before = built.kernel.state_digest()
    messages = build_memory_model_messages(built)
    tools = build_memory_model_tools(built)
    try:
        turn = provider.complete_tool_call(messages=messages, tools=tools, tool_choice="required")
    except ProviderError as exc:
        unchanged = built.kernel.state_digest() == before
        result = MemoryModelScenarioResult(
            scenario_id=scenario.scenario_id,
            category=scenario.category,
            critical=scenario.critical,
            protocol_valid=False,
            semantic_pass=False,
            hard_violation=False,
            hallucinated_id=False,
            provider_error=exc.code,
            kernel_unchanged=unchanged,
            selected_tool=None,
            selected_arguments={},
            expected_tool=built.expected_tool,
            expected_arguments=built.expected_arguments,
            failures=(f"provider_error:{exc.code}",),
            latency_ms=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            raw_response_hash=None,
        )
        return result, {
            "scenario_id": scenario.scenario_id,
            "model_context": built.model_context,
            "provider_error": {"code": exc.code, "message": str(exc)},
            "kernel_digest_before": before,
            "kernel_digest_after": built.kernel.state_digest(),
        }
    result = evaluate_memory_model_turn(built, turn)
    after = built.kernel.state_digest()
    if after != before:
        failures = tuple(dict.fromkeys((*result.failures, "model_call_mutated_kernel")))
        result = replace(
            result,
            kernel_unchanged=False,
            hard_violation=True,
            failures=failures,
        )
    trace = {
        "scenario_id": scenario.scenario_id,
        "model_context": built.model_context,
        "tool_schemas": tools,
        "turn_metadata": turn.metadata(),
        "selected_tool_calls": [item.to_dict() for item in turn.tool_calls],
        "content_present": bool(turn.content and turn.content.strip()),
        "kernel_digest_before": before,
        "kernel_digest_after": after,
        "result": result.to_dict(),
    }
    return result, trace


def summarize_memory_model_results(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(results)
    protocol = sum(bool(item["protocol_valid"]) for item in results)
    semantic = sum(bool(item["semantic_pass"]) for item in results)
    critical_total = sum(bool(item["critical"]) for item in results)
    critical_pass = sum(bool(item["critical"]) and bool(item["semantic_pass"]) for item in results)
    hard = sum(bool(item["hard_violation"]) for item in results)
    hallucinated = sum(bool(item["hallucinated_id"]) for item in results)
    provider_errors = sum(item.get("provider_error") is not None for item in results)
    kernel_mutations = sum(not bool(item["kernel_unchanged"]) for item in results)
    category_summary: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = category_summary.setdefault(str(item["category"]), {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(bool(item["semantic_pass"]))

    gates = {
        "scenario_count_12": total == 12,
        "protocol_valid_12_of_12": protocol == total,
        "semantic_at_least_10_of_12": semantic >= 10,
        "critical_all_pass": critical_pass == critical_total,
        "hard_violations_zero": hard == 0,
        "hallucinated_ids_zero": hallucinated == 0,
        "provider_errors_zero": provider_errors == 0,
        "kernel_mutations_zero": kernel_mutations == 0,
    }
    passed = all(gates.values())
    if passed and semantic == total:
        conclusion = "PASS_CONSTRAINED_CONTROLLER"
    elif passed:
        conclusion = "PASS_WITH_RULE_GATING"
    else:
        conclusion = "FAIL_REAL_MODEL_ACCEPTANCE"
    return {
        "schema_version": _SCHEMA_VERSION,
        "scenario_count": total,
        "protocol_valid_count": protocol,
        "semantic_pass_count": semantic,
        "critical_pass_count": critical_pass,
        "critical_total": critical_total,
        "hard_violation_count": hard,
        "hallucinated_id_count": hallucinated,
        "provider_error_count": provider_errors,
        "kernel_mutation_count": kernel_mutations,
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0)) for item in results),
        "completion_tokens": sum(int(item.get("completion_tokens", 0)) for item in results),
        "latency_ms": sum(float(item.get("latency_ms", 0.0)) for item in results),
        "category_summary": dict(sorted(category_summary.items())),
        "gates": gates,
        "conclusion": conclusion,
        "status": "PASS" if passed else "FAIL",
    }


def run_memory_model_acceptance(
    *,
    scenario_dir: str | Path,
    output_dir: str | Path,
    provider: ToolCallingProvider,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    traces = output / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    scenarios = load_memory_model_scenarios(scenario_dir)
    results: list[MemoryModelScenarioResult] = []
    for scenario in scenarios:
        result, trace = run_one_memory_model_scenario(scenario=scenario, provider=provider)
        results.append(result)
        (traces / f"{scenario.scenario_id}.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    result_dicts = [item.to_dict() for item in results]
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for item in result_dicts:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary = summarize_memory_model_results(result_dicts)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
