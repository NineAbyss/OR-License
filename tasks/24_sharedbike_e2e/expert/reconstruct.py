#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def haversine_km(
    lat1: np.ndarray | float,
    lng1: np.ndarray | float,
    lat2: np.ndarray | float,
    lng2: np.ndarray | float,
) -> np.ndarray:
    lat1r = np.radians(np.asarray(lat1, dtype=np.float64))
    lng1r = np.radians(np.asarray(lng1, dtype=np.float64))
    lat2r = np.radians(np.asarray(lat2, dtype=np.float64))
    lng2r = np.radians(np.asarray(lng2, dtype=np.float64))
    value = np.sin((lat2r - lat1r) / 2.0) ** 2 + np.cos(lat1r) * np.cos(
        lat2r
    ) * np.sin((lng2r - lng1r) / 2.0) ** 2
    return 6_371.0088 * 2.0 * np.arctan2(
        np.sqrt(value), np.sqrt(np.maximum(0.0, 1.0 - value))
    )


def nearest_nodes(
    lat: np.ndarray,
    lng: np.ndarray,
    catalog: pd.DataFrame,
    threshold_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    lat = np.asarray(lat, dtype=float)
    lng = np.asarray(lng, dtype=float)
    nodes = np.full(len(lat), None, dtype=object)
    distances = np.full(len(lat), np.nan)
    station_lat = catalog["lat"].to_numpy(float)
    station_lng = catalog["lng"].to_numpy(float)
    station_ids = catalog["station"].to_numpy(object)
    if not len(station_ids):
        raise ValueError("station catalog must not be empty")
    positions = np.flatnonzero(np.isfinite(lat) & np.isfinite(lng))
    for start in range(0, len(positions), 4096):
        batch = positions[start:start + 4096]
        all_distances = haversine_km(
            lat[batch, None], lng[batch, None],
            station_lat[None, :], station_lng[None, :],
        )
        nearest = np.argmin(all_distances, axis=1)
        observed = all_distances[np.arange(len(batch)), nearest]
        distances[batch] = observed
        accepted = observed <= threshold_km
        nodes[batch[accepted]] = station_ids[nearest[accepted]]
    return nodes, distances


def reconstruct_od(input_files: dict[str, Path], catalog: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    raw = input_files["raw_events.parquet"]
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.execute("SET memory_limit='8GB'")
    frame = con.execute(
        f"""
        SELECT
          record_token,
          first(fleet_token ORDER BY sample_seq) AS fleet_token,
          first(public_date ORDER BY sample_seq) AS public_date,
          first(departure_hour ORDER BY sample_seq) AS departure_hour,
          first(departure_5min_bin ORDER BY sample_seq) AS departure_5min_bin,
          max(elapsed_sec_rounded) AS duration_sec,
          count(*) AS point_count,
          count(*) FILTER (WHERE spatial_valid) AS valid_point_count,
          arg_min(public_lat, sample_seq) FILTER (WHERE spatial_valid) AS origin_lat,
          arg_min(public_lng, sample_seq) FILTER (WHERE spatial_valid) AS origin_lng,
          arg_max(public_lat, sample_seq) FILTER (WHERE spatial_valid) AS destination_lat,
          arg_max(public_lng, sample_seq) FILTER (WHERE spatial_valid) AS destination_lng
        FROM read_parquet('{sql_path(raw)}')
        GROUP BY record_token
        """
    ).df()
    con.close()
    frame = frame.sort_values("record_token").reset_index(drop=True)
    threshold = float(policy["od_construction"]["station_assignment_max_distance_km"])
    frame["origin_node_id"], frame["origin_assignment_distance_km"] = nearest_nodes(
        frame["origin_lat"].to_numpy(float),
        frame["origin_lng"].to_numpy(float),
        catalog,
        threshold,
    )
    frame["destination_node_id"], frame["destination_assignment_distance_km"] = nearest_nodes(
        frame["destination_lat"].to_numpy(float),
        frame["destination_lng"].to_numpy(float),
        catalog,
        threshold,
    )
    frame["start_public_datetime"] = (
        pd.to_datetime(frame["public_date"])
        + pd.to_timedelta(frame["departure_hour"], unit="h")
        + pd.to_timedelta(frame["departure_5min_bin"], unit="m")
    )
    frame["end_public_datetime"] = frame["start_public_datetime"] + pd.to_timedelta(
        frame["duration_sec"], unit="s"
    )
    frame["assigned"] = frame["origin_node_id"].notna() & frame[
        "destination_node_id"
    ].notna()
    frame["trip_id"] = "T" + frame.index.astype(str).str.zfill(6)
    return frame[
        [
            "trip_id",
            "record_token",
            "fleet_token",
            "start_public_datetime",
            "end_public_datetime",
            "duration_sec",
            "point_count",
            "valid_point_count",
            "origin_node_id",
            "destination_node_id",
            "origin_lat",
            "origin_lng",
            "destination_lat",
            "destination_lng",
            "origin_assignment_distance_km",
            "destination_assignment_distance_km",
            "assigned",
        ]
    ]


def flow_matrix(
    od: pd.DataFrame,
    catalog: pd.DataFrame,
    hours: pd.DatetimeIndex,
    node_column: str,
    time_column: str,
) -> np.ndarray:
    node_index = {node: index for index, node in enumerate(catalog["station"])}
    hour_index = {stamp: index for index, stamp in enumerate(hours)}
    selected = od[od["assigned"]].copy()
    selected["flow_hour"] = pd.to_datetime(selected[time_column]).dt.floor("h")
    grouped = selected.groupby(["flow_hour", node_column]).size()
    output = np.zeros((len(hours), len(catalog)), dtype=np.int64)
    for (stamp, node), value in grouped.items():
        if stamp in hour_index and node in node_index:
            output[hour_index[stamp], node_index[node]] = int(value)
    return output


def station_panel(
    input_files: dict[str, Path],
    catalog: pd.DataFrame,
    od: pd.DataFrame,
    policy: dict[str, Any],
) -> pd.DataFrame:
    start = pd.Timestamp(policy["time"]["evaluation_start"])
    count = int(policy["time"]["station_hour_count"])
    hours = pd.date_range(start, periods=count, freq="h")
    departures = flow_matrix(od, catalog, hours, "origin_node_id", "start_public_datetime")
    arrivals = flow_matrix(od, catalog, hours, "destination_node_id", "end_public_datetime")
    anchor = pd.read_csv(input_files["inventory_anchor.csv"])
    anchor["station"] = anchor["station"].astype(str)
    anchor_values = (
        anchor.set_index("station")
        .reindex(catalog["station"])["available_bikes"]
        .to_numpy(dtype=np.int64)
    )
    if np.isnan(anchor_values.astype(float)).any():
        raise RuntimeError("inventory anchor does not cover the catalog")
    events = pd.read_csv(input_files["operator_events.csv"])
    adjustments = np.zeros_like(departures)
    if len(events):
        events["event_datetime"] = pd.to_datetime(events["event_datetime"])
        node_index = {node: index for index, node in enumerate(catalog["station"])}
        hour_index = {stamp: index for index, stamp in enumerate(hours)}
        for row in events.itertuples(index=False):
            boundary = pd.Timestamp(row.event_datetime).floor("h")
            if boundary in hour_index and str(row.station) in node_index:
                adjustments[hour_index[boundary], node_index[str(row.station)]] += int(
                    row.inventory_delta
                )
    stock = np.zeros_like(departures)
    stock[0] = anchor_values
    for period in range(count - 1):
        stock[period + 1] = (
            stock[period]
            - departures[period]
            + arrivals[period]
            + adjustments[period]
        )
    if (stock < 0).any():
        raise RuntimeError("public inventory recurrence produced negative stock")
    rows: list[pd.DataFrame] = []
    for period, boundary in enumerate(hours):
        target = boundary + pd.Timedelta(hours=1)
        current = catalog.copy()
        current["date"] = boundary.date().isoformat()
        current["hour"] = int(boundary.hour)
        current["target_date"] = target.date().isoformat()
        current["target_hour"] = int(target.hour)
        current["stock"] = stock[period]
        current["demand"] = departures[period]
        current["surplus"] = stock[period] - departures[period]
        current["demand_in_reference"] = arrivals[period]
        rows.append(current)
    panel = pd.concat(rows, ignore_index=True)
    return panel[
        [
            "station",
            "date",
            "hour",
            "target_date",
            "target_hour",
            "stock",
            "demand",
            "surplus",
            "demand_in_reference",
            "lat",
            "lng",
            "district",
            "zone_type",
            "service_priority_class",
            "capacity",
        ]
    ].sort_values(["date", "hour", "station"]).reset_index(drop=True)


def pairwise_haversine(catalog: pd.DataFrame) -> np.ndarray:
    lat = np.radians(catalog["lat"].to_numpy(float))
    lng = np.radians(catalog["lng"].to_numpy(float))
    dlat = lat[:, None] - lat[None, :]
    dlng = lng[:, None] - lng[None, :]
    value = np.sin(dlat / 2.0) ** 2 + np.cos(lat[:, None]) * np.cos(
        lat[None, :]
    ) * np.sin(dlng / 2.0) ** 2
    return 6_371.0088 * 2.0 * np.arctan2(
        np.sqrt(value), np.sqrt(np.maximum(0.0, 1.0 - value))
    )


def routes(catalog: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    catalog = catalog.sort_values("station").reset_index(drop=True)
    distances = pairwise_haversine(catalog)
    k = int(policy["routes"]["neighbors_per_origin"])
    edges: dict[tuple[int, int], dict[str, int]] = {}
    for source in range(len(catalog)):
        ordered = sorted(
            (destination for destination in range(len(catalog)) if destination != source),
            key=lambda destination: (
                float(distances[source, destination]),
                str(catalog.iloc[destination]["station"]),
            ),
        )
        for destination in ordered[:k]:
            edges[(source, destination)] = {"tag_knn": 1, "tag_intra_district": 0}
    if bool(policy["routes"]["include_same_region_pairs"]):
        for _, group in catalog.groupby("district", sort=False):
            for source in group.index:
                for destination in group.index:
                    if source == destination:
                        continue
                    edge = edges.setdefault(
                        (int(source), int(destination)),
                        {"tag_knn": 0, "tag_intra_district": 0},
                    )
                    edge["tag_intra_district"] = 1
    output = []
    for (source, destination), tags in sorted(edges.items()):
        raw_distance = float(distances[source, destination])
        output.append(
            {
                "from_station": catalog.iloc[source]["station"],
                "to_station": catalog.iloc[destination]["station"],
                "distance_km": round(raw_distance, 3),
                "cost_per_bike": round(2.0 + 0.5 * raw_distance, 3),
                "from_district": catalog.iloc[source]["district"],
                "to_district": catalog.iloc[destination]["district"],
                **tags,
            }
        )
    return pd.DataFrame(output).sort_values(["from_station", "to_station"]).reset_index(drop=True)


def penalties(catalog: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    mapping = policy["penalty"]["class_to_unmet_penalty"]
    output = catalog[["station", "service_priority_class"]].rename(
        columns={"station": "node_id"}
    )
    output["unmet_penalty"] = output["service_priority_class"].map(mapping)
    return output[["node_id", "unmet_penalty", "service_priority_class"]].sort_values(
        "node_id"
    ).reset_index(drop=True)


def reconstruct(input_files: dict[str, Path], output_root: Path) -> dict[str, Any]:
    policy = yaml.safe_load((input_files["task_policy.yaml"]).read_text(encoding="utf-8"))
    catalog = pd.read_csv(input_files["station_catalog.csv"]).sort_values("station").reset_index(drop=True)
    od = reconstruct_od(input_files, catalog, policy)
    panel = station_panel(input_files, catalog, od, policy)
    route_table = routes(catalog, policy)
    penalty_table = penalties(catalog, policy)
    write_csv(output_root / "od_trips.csv", od)
    write_csv(output_root / "stations.csv", panel)
    write_csv(output_root / "routes.csv", route_table)
    write_csv(output_root / "zone_unmet_penalty.csv", penalty_table)
    summary = {
        "lineage": "public E2E inputs only",
        "rows": {
            "od_trips.csv": int(len(od)),
            "stations.csv": int(len(panel)),
            "routes.csv": int(len(route_table)),
            "zone_unmet_penalty.csv": int(len(penalty_table)),
        },
        "assigned_records": int(od["assigned"].sum()),
    }
    write_json(output_root / "reconstruction_summary.json", summary)
    return summary


if __name__ == "__main__":
    import sys
    case = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(case.parent))
    from sharedbike_shared.data import public_input_files
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconstruct(public_input_files(case), args.output_dir.resolve()), indent=2))
