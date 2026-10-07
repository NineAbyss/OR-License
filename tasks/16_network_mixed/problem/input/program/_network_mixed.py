
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import math


def prepare_mixed(testdata):
    if testdata.get("variant") != "mixed":
        return testdata
    data = deepcopy(testdata)
    factories = data["factories"]
    centrals = data["central_warehouses"]
    regionals = data["regional_centers"]
    nodes = {**factories, **centrals, **regionals}
    records = {}
    for section in ("factory_to_cdc", "cdc_to_rdc"):
        for key, arc in data["arcs"][section].items():
            pair = tuple(key.split("|")[:2])
            records.setdefault(pair, []).append(arc)
    for row in data.get("mixed_transport_records", []):
        pair = (row["source"], row["destination"])
        records.setdefault(pair, []).append(row)

    def geometry(source, destination, existing):
        rows = records.get((source, destination), [])
        values = {}
        for field in ("distance_km", "transit_days"):
            values[field] = existing.get(field)
            if values[field] is None:
                values[field] = next((r[field] for r in rows if r.get(field) is not None), None)
        if values["distance_km"] is None:
            try:
                a, b = nodes[source], nodes[destination]
                lat1, lon1, lat2, lon2 = map(math.radians, (
                    a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Missing coordinates for {source} -> {destination}; ask the organizer") from exc
            h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
            km = 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h)))) * 1.17
            values["distance_km"] = float(Decimal(str(km)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        if values["transit_days"] is None:
            values["transit_days"] = max(1, math.ceil(values["distance_km"] / 1320))
        return values

    for cdc in centrals.values():
        cdc["holding_rate"] = {"candy": 0.15, "chocolate": 0.16}
    for factory, meta in factories.items():
        categories = {data["products"][p]["category"] for p in meta["products"]}
        if len(categories) != 1:
            raise ValueError("factory_to_cdc schema requires one category per factory")
        category = categories.pop()
        for cdc in centrals:
            key = f"{factory}|{cdc}"
            arc = data["arcs"]["factory_to_cdc"].setdefault(key, {})
            arc.update(factory=factory, cdc=cdc, category=category,
                       mode="ambient" if category == "candy" else "constant_temperature",
                       freight_rate=0.24 if category == "candy" else 0.47,
                       freight_basis="yuan_per_cmtr_km", shipment_interval_days=3,
                       **geometry(factory, cdc, arc))
    for cdc in centrals:
        for rdc in regionals:
            cold = rdc in {"R01", "R02", "R03", "R05"}
            for category in ("candy", "chocolate"):
                temperature = category == "chocolate" and cold
                key = f"{cdc}|{rdc}|{category}"
                arc = data["arcs"]["cdc_to_rdc"].setdefault(key, {})
                arc.update(cdc=cdc, rdc=rdc, category=category,
                           mode="constant_temperature" if temperature else "ambient",
                           freight_rate=0.39 if category == "candy" else (1.02 if temperature else 0.45),
                           freight_basis="yuan_per_cmtr_km", shipment_interval_days=3 if temperature else 2,
                           **geometry(cdc, rdc, arc))
    return data
