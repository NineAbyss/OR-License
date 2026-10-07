
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


KNOWLEDGE_OWNERS = frozenset({"user", "dataset", "external_system", "or_expert"})


class LedgerError(ValueError):
    pass


def _as_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise LedgerError("expected a string or an array of strings")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class AnswerUnit:
    text: str

    @classmethod
    def from_value(cls, value: Any) -> "AnswerUnit":
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, Mapping):
            text = str(value.get("text", "")).strip()
        else:
            raise LedgerError("answer_units entries must be strings or objects")
        if not text:
            raise LedgerError("answer unit text must not be empty")
        return cls(text=text)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text}


@dataclass(frozen=True)
class RuleAnchor:
    verifier_rule_ids: tuple[str, ...] = ()
    objective_components: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: Any) -> "RuleAnchor":
        if value is None:
            return cls()
        if isinstance(value, str):
            return cls(verifier_rule_ids=(value,))
        if not isinstance(value, Mapping):
            raise LedgerError("rule_anchor must be an object")
        objectives: list[str] = []
        for key in ("objective_component", "objective_components"):
            for item in _as_string_list(value.get(key)):
                if item not in objectives:
                    objectives.append(item)
        return cls(
            verifier_rule_ids=_as_string_list(
                value.get("verifier_rule_ids", value.get("rule_ids"))
            ),
            objective_components=tuple(objectives),
        )

    @property
    def objective_component(self) -> str | None:
        return self.objective_components[0] if self.objective_components else None

    def to_dict(self) -> dict[str, Any]:
        objective: str | list[str] | None
        if not self.objective_components:
            objective = None
        elif len(self.objective_components) == 1:
            objective = self.objective_components[0]
        else:
            objective = list(self.objective_components)
        return {
            "verifier_rule_ids": list(self.verifier_rule_ids),
            "objective_component": objective,
        }


@dataclass(frozen=True)
class LedgerFact:
    fact_id: str
    slot_id: str
    statement: str
    knowledge_owner: str
    rule_anchor: RuleAnchor = field(default_factory=RuleAnchor)
    in_brief: bool = False
    answer_units: tuple[AnswerUnit, ...] = ()

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], *, allow_missing_statement: bool = False
    ) -> "LedgerFact":
        fact_id = str(value.get("fact_id", value.get("id", ""))).strip()
        if not fact_id:
            raise LedgerError("every fact requires fact_id")
        slot_id = str(value.get("slot_id") or fact_id).strip()
        statement = str(value.get("statement", value.get("description", ""))).strip()
        if not statement and not allow_missing_statement:
            raise LedgerError(f"fact {fact_id} requires statement")
        owner = str(value.get("knowledge_owner", "user")).strip()
        if owner not in KNOWLEDGE_OWNERS:
            raise LedgerError(
                f"fact {fact_id} has unknown knowledge_owner {owner!r}; "
                f"expected one of {sorted(KNOWLEDGE_OWNERS)}"
            )

        raw_units = value.get("answer_units", []) or []
        if isinstance(raw_units, (str, Mapping)):
            raw_units = [raw_units]
        units = tuple(AnswerUnit.from_value(item) for item in raw_units)
        if not units and owner == "user" and statement:
            units = (AnswerUnit(statement),)

        return cls(
            fact_id=fact_id,
            slot_id=slot_id,
            statement=statement,
            knowledge_owner=owner,
            rule_anchor=RuleAnchor.from_value(value.get("rule_anchor")),
            in_brief=bool(value.get("in_brief", False)),
            answer_units=units,
        )

    def render(self, separator: str = "\n") -> str:
        return separator.join(unit.text for unit in self.answer_units).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "slot_id": self.slot_id,
            **({"statement": self.statement} if self.statement else {}),
            "knowledge_owner": self.knowledge_owner,
            "rule_anchor": self.rule_anchor.to_dict(),
            "in_brief": self.in_brief,
            "answer_units": [unit.to_dict() for unit in self.answer_units],
        }


@dataclass(frozen=True)
class CompletenessReport:
    covered_verifier_rule_ids: tuple[str, ...]
    covered_objective_components: tuple[str, ...]
    missing_verifier_rule_ids: tuple[str, ...]
    missing_objective_components: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_verifier_rule_ids and not self.missing_objective_components

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "covered_verifier_rule_ids": list(self.covered_verifier_rule_ids),
            "covered_objective_components": list(self.covered_objective_components),
            "missing_verifier_rule_ids": list(self.missing_verifier_rule_ids),
            "missing_objective_components": list(self.missing_objective_components),
        }


class Ledger:

    def __init__(
        self,
        facts: Iterable[LedgerFact],
        *,
        case_id: str = "",
        schema_version: int = 1,
        frozen: bool = False,
        source_path: Path | None = None,
    ) -> None:
        ordered = tuple(facts)
        by_id: dict[str, LedgerFact] = {}
        for fact in ordered:
            if fact.fact_id in by_id:
                raise LedgerError(f"duplicate fact_id: {fact.fact_id}")
            if fact.knowledge_owner == "user" and not fact.render():
                raise LedgerError(f"fact {fact.fact_id} requires answer_units")
            by_id[fact.fact_id] = fact
        self.facts = ordered
        self.by_id = by_id
        self.case_id = case_id
        self.schema_version = schema_version
        self.frozen = frozen
        self.source_path = source_path

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any] | Sequence[Any],
        *,
        source_path: Path | None = None,
    ) -> "Ledger":
        if isinstance(value, Mapping):
            raw_facts = value.get("facts", value.get("ledger", []))
            case_id = str(value.get("case_id", value.get("scenario_id", "")))
            schema_version = int(value.get("schema_version", value.get("version", 1)))
            frozen = bool(value.get("frozen", False))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            raw_facts = value
            case_id = ""
            schema_version = 1
            frozen = False
        else:
            raise LedgerError("ledger must be an object or an array of facts")
        if isinstance(raw_facts, Mapping):
            normalized_facts = []
            for fact_id, raw in raw_facts.items():
                if isinstance(raw, Mapping):
                    item = dict(raw)
                    item.setdefault("fact_id", fact_id)
                    normalized_facts.append(item)
            raw_facts = normalized_facts
        if not isinstance(raw_facts, Sequence) or isinstance(raw_facts, (str, bytes, bytearray)):
            raise LedgerError("ledger.facts must be an array")
        parsed: list[LedgerFact] = []
        for index, raw in enumerate(raw_facts):
            if not isinstance(raw, Mapping):
                raise LedgerError(f"ledger.facts[{index}] must be an object")
            parsed.append(LedgerFact.from_dict(raw, allow_missing_statement=True))
        return cls(
            parsed,
            case_id=case_id,
            schema_version=schema_version,
            frozen=frozen,
            source_path=source_path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"cannot read ledger: {source}") from exc
        return cls.from_dict(payload, source_path=source)

    def __len__(self) -> int:
        return len(self.facts)

    def __iter__(self) -> Iterator[LedgerFact]:
        return iter(self.facts)

    def __contains__(self, fact_id: object) -> bool:
        return fact_id in self.by_id

    def __getitem__(self, fact_id: str) -> LedgerFact:
        return self.by_id[fact_id]

    def get(self, fact_id: str) -> LedgerFact | None:
        return self.by_id.get(fact_id)

    @property
    def required_fact_ids(self) -> tuple[str, ...]:
        return tuple(
            fact.fact_id
            for fact in self.facts
            if fact.knowledge_owner == "user" and not fact.in_brief
        )

    def fact_ids_for_owner(self, owner: str) -> tuple[str, ...]:
        return tuple(fact.fact_id for fact in self.facts if fact.knowledge_owner == owner)

    def completeness(
        self,
        verifier_rule_ids: Iterable[str] = (),
        objective_components: Iterable[str] = (),
    ) -> CompletenessReport:
        covered_rules = sorted(
            {rule for fact in self.facts for rule in fact.rule_anchor.verifier_rule_ids}
        )
        covered_objectives = sorted(
            {
                component
                for fact in self.facts
                for component in fact.rule_anchor.objective_components
            }
        )
        expected_rules = {str(item) for item in verifier_rule_ids}
        expected_objectives = {str(item) for item in objective_components}
        return CompletenessReport(
            covered_verifier_rule_ids=tuple(covered_rules),
            covered_objective_components=tuple(covered_objectives),
            missing_verifier_rule_ids=tuple(sorted(expected_rules - set(covered_rules))),
            missing_objective_components=tuple(
                sorted(expected_objectives - set(covered_objectives))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "frozen": self.frozen,
            "facts": [fact.to_dict() for fact in self.facts],
        }


def load_ledger(path: str | Path) -> Ledger:
    return Ledger.load(path)
