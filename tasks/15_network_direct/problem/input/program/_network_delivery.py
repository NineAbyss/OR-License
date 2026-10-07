from __future__ import annotations

import math
from typing import Any


def final_supply_nodes(data: dict[str, Any]) -> set[str]:
    policy = data.get('direct_delivery', {})
    if data.get('variant') == 'direct' and policy.get('allow_new_relations'):
        return set(data['factories']) | set(data['central_warehouses']) | set(data['regional_centers'])
    return set(data['arcs']['node_to_customer']['distance_km'])


def delivery_distance(data: dict[str, Any], node: str, customer: str) -> float | None:
    if node not in final_supply_nodes(data) or customer not in data['customers']:
        return None
    existing = data['arcs']['node_to_customer']['distance_km'].get(node, {}).get(customer)
    if existing is not None:
        return float(existing)
    policy = data.get('direct_delivery', {})
    if data.get('variant') != 'direct' or not policy.get('allow_new_relations'):
        return None
    coordinates = data['coordinates']
    if node not in coordinates or customer not in coordinates:
        return None
    a, b = coordinates[node], coordinates[customer]
    lat1, lon1 = math.radians(a['latitude']), math.radians(a['longitude'])
    lat2, lon2 = math.radians(b['latitude']), math.radians(b['longitude'])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    great_circle = 2 * policy['earth_radius_km'] * math.asin(math.sqrt(min(1.0, max(0.0, h))))
    return round(policy['distance_multiplier'] * great_circle, policy['distance_decimals'])


def delivery_transit_days(data: dict[str, Any], node: str, customer: str) -> float:
    existing = data['arcs']['node_to_customer']['transit_days'].get(node, {}).get(customer)
    if existing is not None:
        return float(existing)
    km = delivery_distance(data, node, customer)
    if km is None:
        raise ValueError(f"no delivery relation {node} -> {customer}")
    policy = data["direct_delivery"]
    if policy["transit_rule"] != "distance_over_speed":
        raise ValueError("unsupported direct-delivery transit-time rule")
    return km / policy["average_speed_kmh"] / 24.0


def delivery_holding_rate(data: dict[str, Any], node: str, category: str) -> float:
    if node in data['factories']:
        return data['factories'][node]['holding_rate_finished']
    meta = data['central_warehouses'].get(node) or data['regional_centers'][node]
    return meta['holding_rate'][category]
