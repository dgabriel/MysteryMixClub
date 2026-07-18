"""Wire-vocabulary aliasing for the club/mix rename (MYS-196 cutover).

The JSON wire speaks club/mix (`club_id`, `mix_number`, …) while Python field
names remain on the old vocabulary until the R3/R4 identifier cleanup. Every
request/response model in the API inherits :class:`WireModel`, whose alias
generator maps exactly the renamed fields; everything else passes through
untouched.

- Serialization: FastAPI serializes response models by alias, so responses emit
  the new keys.
- Validation: requests accept the new keys; ``populate_by_name=True`` also lets
  internal code construct models by field name (and tolerates old keys from any
  straggler client — harmless during the transition, gone when R3/R4 renames
  the fields for real and deletes this module).
"""

from __future__ import annotations

from pydantic import AliasGenerator, BaseModel, ConfigDict

# The complete wire rename map. Field names not listed are unchanged.
WIRE_ALIASES = {
    "league_id": "club_id",
    "league_name": "club_name",
    "round_id": "mix_id",
    "round_number": "mix_number",
    "total_rounds": "total_mixes",
    "current_round": "current_mix",
}


def _wire_name(field_name: str) -> str:
    return WIRE_ALIASES.get(field_name, field_name)


class WireModel(BaseModel):
    """Base for every API request/response model: old field names in, new wire out."""

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=_wire_name,
            serialization_alias=_wire_name,
        ),
        populate_by_name=True,
    )
