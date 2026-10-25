import argparse
import html
import warnings
from collections import defaultdict, deque
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import MarkerCluster


REQUIRED_COLUMNS = {
    "Horodatage",
    "Utilisateur",
    "POI",
    "Action",
    "Latitude",
    "Longitude",
}
CHECK_IN = "Check-in"
CHECK_OUT = "Check-out"
MAP_COLORS = [
    "red",
    "blue",
    "green",
    "purple",
    "orange",
    "darkred",
    "cadetblue",
    "darkgreen",
    "pink",
    "gray",
]
BASEMAP_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
)
BASEMAP_ATTRIBUTION = (
    "Tiles &copy; Esri -- Source: Esri, DeLorme, NAVTEQ, USGS, "
    "Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), "
    "Esri (Thailand), TomTom"
)

#TODO : Faire l'analyse par organisation. Ca implique de mettre le fichier log_location.csv avec l'organisation declarée. Et probalement exporter USER_ORG / POI_ORG dans un fichier config. A voir.
#TODO : Ecrire le fichier *.html sur NExtcloud avec les fonctions d'ecriture nextcloud.


def load_logs(csv_path: Path) -> pd.DataFrame:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Fichier CSV introuvable : {csv_path}")

    logs = pd.read_csv(csv_path, encoding="utf-8-sig")
    missing_columns = REQUIRED_COLUMNS - set(logs.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Colonnes manquantes dans le CSV : {missing}")
    if logs.empty:
        raise ValueError("Le fichier CSV ne contient aucun pointage.")

    logs["Horodatage"] = pd.to_datetime(logs["Horodatage"], errors="coerce")
    logs["Latitude"] = pd.to_numeric(logs["Latitude"], errors="coerce")
    logs["Longitude"] = pd.to_numeric(logs["Longitude"], errors="coerce")
    logs["POI"] = logs["POI"].fillna("").astype(str).str.strip()
    logs["Utilisateur"] = logs["Utilisateur"].fillna("").astype(str).str.strip()
    logs["Action"] = logs["Action"].fillna("").astype(str).str.strip()

    invalid_rows = (
        logs["Horodatage"].isna()
        | logs["Latitude"].isna()
        | logs["Longitude"].isna()
        | ~logs["Latitude"].between(-90, 90)
        | ~logs["Longitude"].between(-180, 180)
        | logs["Utilisateur"].eq("")
        | ~logs["Action"].isin({CHECK_IN, CHECK_OUT})
    )
    if invalid_rows.any():
        csv_lines = (logs.index[invalid_rows] + 2).tolist()
        raise ValueError(
            "Données manquantes ou invalides aux lignes CSV : "
            + ", ".join(map(str, csv_lines))
        )

    missing_poi = logs["POI"].eq("")
    if missing_poi.any():
        csv_lines = (logs.index[missing_poi] + 2).tolist()
        warnings.warn(
            "Pointages ignorés car le POI est vide aux lignes CSV : "
            + ", ".join(map(str, csv_lines)),
            stacklevel=2,
        )
        logs = logs.loc[~missing_poi]
    if logs.empty:
        raise ValueError("Aucun pointage exploitable : tous les POI sont vides.")

    if "Précision (m)" in logs.columns:
        logs["Précision (m)"] = pd.to_numeric(
            logs["Précision (m)"], errors="coerce"
        )
    else:
        logs["Précision (m)"] = float("nan")

    return logs.sort_values("Horodatage").reset_index(drop=True)


def pair_visits(logs: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    open_check_ins: dict[tuple[str, str], deque] = defaultdict(deque)
    visits = []
    unmatched_check_outs = 0

    for row in logs.itertuples(index=False):
        key = (row.Utilisateur, row.POI)
        if row.Action == CHECK_IN:
            open_check_ins[key].append(row)
            continue

        if not open_check_ins[key]:
            unmatched_check_outs += 1
            continue

        check_in = open_check_ins[key].popleft()
        visits.append(
            {
                "Utilisateur": row.Utilisateur,
                "POI": row.POI,
                "Début": check_in.Horodatage,
                "Fin": row.Horodatage,
                "Durée (min)": (
                    row.Horodatage - check_in.Horodatage
                ).total_seconds()
                / 60,
                "Latitude": check_in.Latitude,
                "Longitude": check_in.Longitude,
            }
        )

    unmatched_check_ins = sum(len(queue) for queue in open_check_ins.values())
    return pd.DataFrame(visits), unmatched_check_ins, unmatched_check_outs


def summarize_by_poi(
    logs: pd.DataFrame, visits: pd.DataFrame
) -> pd.DataFrame:
    check_in_counts = (
        logs.loc[logs["Action"].eq(CHECK_IN)]
        .groupby("POI")
        .size()
        .rename("Fréquence (check-in)")
    )
    summary = check_in_counts.to_frame()

    if not visits.empty:
        duration_stats = visits.groupby("POI")["Durée (min)"].agg(
            [
                ("Visites avec durée", "count"),
                ("Durée moyenne (min)", "mean"),
                ("Durée médiane (min)", "median"),
                ("Durée totale (min)", "sum"),
            ]
        )
        summary = summary.join(duration_stats, how="left")

    summary["Visites avec durée"] = (
        summary["Visites avec durée"].fillna(0).astype(int)
    )
    return summary.reset_index().sort_values("POI").reset_index(drop=True)


def create_map(logs: pd.DataFrame, summary: pd.DataFrame, output_path: Path) -> None:
    center = [logs["Latitude"].mean(), logs["Longitude"].mean()]
    map_view = folium.Map(
        location=center,
        zoom_start=6,
        tiles=BASEMAP_URL,
        attr=BASEMAP_ATTRIBUTION,
    )
    marker_cluster = MarkerCluster(name="POI").add_to(map_view)
    colors = {
        poi: MAP_COLORS[index % len(MAP_COLORS)]
        for index, poi in enumerate(sorted(logs["POI"].unique()))
    }
    summary_by_poi = summary.set_index("POI")

    locations = (
        logs.groupby(["POI", "Latitude", "Longitude"], as_index=False)
        .agg(
            **{
                "Nombre de pointages": ("Action", "size"),
                "Précision moyenne (m)": ("Précision (m)", "mean"),
            }
        )
    )

    for _, location in locations.iterrows():
        poi = location["POI"]
        poi_stats = summary_by_poi.loc[poi]
        average_duration = poi_stats.get("Durée moyenne (min)")
        average_duration_text = (
            "Non disponible"
            if pd.isna(average_duration)
            else f"{average_duration:.1f} min"
        )
        average_precision = location["Précision moyenne (m)"]
        precision_text = (
            "Non disponible"
            if pd.isna(average_precision)
            else f"{average_precision:.0f} m"
        )
        popup_html = (
            f"<b>{html.escape(poi)}</b><br>"
            f"Fréquence : {int(poi_stats['Fréquence (check-in)'])} check-in<br>"
            f"Durée moyenne : {average_duration_text}<br>"
            f"Pointages à cette coordonnée : {location['Nombre de pointages']}<br>"
            f"Précision GPS moyenne : {precision_text}<br>"
            f"Coordonnées : {location['Latitude']:.6f}, "
            f"{location['Longitude']:.6f}"
        )
        folium.Marker(
            location=[location["Latitude"], location["Longitude"]],
            tooltip=html.escape(poi),
            popup=folium.Popup(popup_html, max_width=320),
            icon=folium.Icon(color=colors[poi], icon="info-sign"),
        ).add_to(marker_cluster)

    if len(locations) > 1:
        map_view.fit_bounds(
            [
                [locations["Latitude"].min(), locations["Longitude"].min()],
                [locations["Latitude"].max(), locations["Longitude"].max()],
            ],
            padding=(24, 24),
        )

    folium.LayerControl().add_to(map_view)
    map_view.get_root().html.add_child(
        folium.Element(
            "<div style='position:fixed;bottom:12px;left:12px;z-index:9999;"
            "background:white;padding:8px;border:1px solid #999'>"
            "Fond Esri ; la précision GPS enregistrée peut être faible."
            "</div>"
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    map_view.save(str(output_path))


def main() -> None:
    default_dir = Path(__file__).resolve().parent
    analyse_result_dir = Path.joinpath(default_dir, "analyse_result")
    analyse_result_dir.mkdir(parents=True, exist_ok=True)
    print(f"Résultats d'analyse dans : {analyse_result_dir}")
    
    parser = argparse.ArgumentParser(
        description=(
            "Génère une carte interactive des POI et des statistiques "
            "de fréquence et de durée de présence."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path.joinpath(default_dir, "log_location.csv"),
        help="CSV des pointages (par défaut : log_location.csv à côté du script).",
    )
    parser.add_argument(
        "--map-output",
        type=Path,
        default=Path.joinpath(analyse_result_dir, "carte_poi.html"),
        help="Fichier HTML de la carte.",
    )
    parser.add_argument(
        "--stats-output",
        type=Path,
        default=Path.joinpath(analyse_result_dir, "statistiques_poi.csv"),
        help="Fichier CSV des statistiques par POI.",
    )
    args = parser.parse_args()

    logs = load_logs(args.input)
    visits, unmatched_check_ins, unmatched_check_outs = pair_visits(logs)
    summary = summarize_by_poi(logs, visits)
    create_map(logs, summary, args.map_output)

    args.stats_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.stats_output, index=False, encoding="utf-8-sig")

    print("Statistiques par POI (durées en minutes) :")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.1f}"))
    print(f"\nCarte créée : {args.map_output}")
    print(f"Statistiques exportées : {args.stats_output}")
    if unmatched_check_ins or unmatched_check_outs:
        warnings.warn(
            f"{unmatched_check_ins} check-in sans check-out et "
            f"{unmatched_check_outs} check-out sans check-in ; "
            "ces événements restent comptés dans la fréquence, mais "
            "ne contribuent pas aux durées.",
            stacklevel=1,
        )


if __name__ == "__main__":
    main()
