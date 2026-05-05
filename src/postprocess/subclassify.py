"""Map an Overture-tagged building polygon to one of our 9 subclasses.

Overture buildings carry two label fields: `subtype` (broad: residential,
commercial, education, …) and `class` (narrow: apartments, school, …).
We aggregate them into a 9-class palette suited to a city-level map.

Decision order:
  1. Specific Overture `class` (apartments, school, hospital…) -> direct map
  2. Overture `subtype` (residential, education…) -> mapped category;
     for `residential`, refine via num_floors then footprint area.
  3. No tag -> area heuristic: house if small, apartment_block if large.
"""
from __future__ import annotations

# class -> our subclass (preferred over subtype when present)
CLASS_TO_SUB: dict[str, str] = {
    # residential
    "house": "house", "detached": "house", "bungalow": "house",
    "cabin": "house", "farm": "house",
    "apartments": "apartment_block", "dormitory": "apartment_block",
    "residential": "apartment_block", "barracks": "apartment_block",
    # education / civic / health
    "school": "school", "kindergarten": "school", "university": "school",
    "college": "school",
    "hospital": "hospital", "clinic": "hospital",
    "civic": "civic", "government": "civic", "townhall": "civic",
    "library": "civic", "fire_station": "civic", "police": "civic",
    "courthouse": "civic", "embassy": "civic",
    # religious
    "church": "religious", "mosque": "religious", "temple": "religious",
    "cathedral": "religious", "chapel": "religious", "shrine": "religious",
    "monastery": "religious",
    # commercial
    "retail": "commercial", "commercial": "commercial",
    "office": "commercial", "supermarket": "commercial",
    "kiosk": "commercial", "store": "commercial", "hotel": "commercial",
    "restaurant": "commercial", "cafe": "commercial",
    # industrial / utility
    "industrial": "industrial", "warehouse": "industrial",
    "factory": "industrial", "manufacture": "industrial",
    "service": "industrial",
    # transportation
    "transportation": "transportation", "train_station": "transportation",
    "hangar": "transportation", "parking": "transportation",
    # outbuilding / minor
    "garage": "outbuilding", "garages": "outbuilding", "shed": "outbuilding",
    "carport": "outbuilding", "roof": "outbuilding",
    "outbuilding": "outbuilding", "stable": "outbuilding",
    # agricultural
    "agricultural": "agricultural", "barn": "agricultural",
    "greenhouse": "agricultural", "farm_auxiliary": "agricultural",
}

# subtype -> our subclass when class is missing
SUBTYPE_TO_SUB: dict[str, str | None] = {
    "residential": None,        # use floors/area to split house vs apartment_block
    "education": "school",
    "medical": "hospital",
    "religious": "religious",
    "commercial": "commercial",
    "entertainment": "commercial",
    "industrial": "industrial",
    "service": "industrial",
    "civic": "civic",
    "transportation": "transportation",
    "outbuilding": "outbuilding",
    "agricultural": "agricultural",
    "military": "civic",
}

HOUSE_MAX_AREA_M2 = 250.0


def subclass_from_overture(over_row: dict | None, area_m2: float) -> str:
    """Resolve building subclass for one polygon."""
    if over_row is not None:
        cls = over_row.get("overture_class")
        if isinstance(cls, str):
            cls = cls.lower().strip()
            if cls and cls != "none" and cls != "nan" and cls in CLASS_TO_SUB:
                return CLASS_TO_SUB[cls]
        sub = over_row.get("overture_subtype")
        if isinstance(sub, str):
            sub = sub.lower().strip()
            if sub == "residential":
                nf = over_row.get("num_floors")
                try:
                    if nf is not None and float(nf) >= 3:
                        return "apartment_block"
                    elif nf is not None and float(nf) >= 1:
                        return "house"
                except Exception:
                    pass
                return "house" if area_m2 <= HOUSE_MAX_AREA_M2 else "apartment_block"
            mapped = SUBTYPE_TO_SUB.get(sub)
            if mapped:
                return mapped
    return "house" if area_m2 <= HOUSE_MAX_AREA_M2 else "apartment_block"
