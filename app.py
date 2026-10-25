import datetime
import hashlib
import os
import uuid
import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
from streamlit_js_eval import get_geolocation, streamlit_js_eval
import hashlib

import os
import uuid

from streamlit.runtime.secrets import secrets_singleton

LOG_FILE = "log_location.csv"


if not secrets_singleton.load_if_toml_exists():
    raise RuntimeError(
        "Configuration Streamlit absente : créez .streamlit/secrets.toml "
        "à partir de secrets.toml.example."
    )

streamlit_secrets = secrets_singleton.to_dict()
auth_config = streamlit_secrets.get("auth")
if not isinstance(auth_config, dict):
    raise RuntimeError("La section [auth] est absente de .streamlit/secrets.toml.")

authentik_config = auth_config.get("authentik", {})
if not isinstance(authentik_config, dict):
    raise RuntimeError("La section [auth.authentik] doit être une table TOML.")

client_kwargs = authentik_config.get("client_kwargs", {})
if not isinstance(client_kwargs, dict):
    raise RuntimeError("[auth.authentik.client_kwargs] doit être une table TOML.")


auth_config["authentik"] = authentik_config
secrets_singleton.merge_programmatic_secrets({"auth": auth_config})


# --- COMPTES AUTORISÉS & POI ---
USER_ORG = {
    "jc": ("JC", "ddcm"),
    "nico": ("Nico", "atae"),
    "default": ("DefaultUser", "DefaultOrg"),
}

POI_LIST = {
    "ddcm": ["Maison", "Bureau", "Bois", "Piece d'eau", "Chateau", "Rouen Coloc", "Noema", "Nouveau"],
    "atae": ["Maison", "Bureau", "Chantier1", "Chantier2", "Chantier3", "Repas", "Nouveau"],
    "DefaultOrg": ["Lieu1", "Lieu2", "NouveauLieu"]
}

st.set_page_config(page_title="Pointage GPS", page_icon="📍", layout="centered")

# --- INITIALISATION DU COOKIE MANAGER ---
if "cookie_manager" not in st.session_state:
    st.session_state.cookie_manager = stx.CookieManager(
        key="init_cookie_manager"
    )

cookie_manager = st.session_state.cookie_manager

# Le cookie manager reste utilisé uniquement pour l'identifiant de l'appareil.
cookies = cookie_manager.get_all()

device_id = cookies.get("checkloc_device_id") if isinstance(cookies, dict) else None

# 1. Gestion du Device ID persistant
if not device_id and isinstance(cookies, dict):
    new_device_id = str(uuid.uuid4())
    cookie_manager.set(
        "checkloc_device_id",
        new_device_id,
        max_age=365 * 24 * 3600,
        key="set_device_id_cookie",
    )
    device_id = new_device_id

if "last_action" not in st.session_state:
    st.session_state.last_action = None

if "action_type" not in st.session_state:
    st.session_state.action_type = None


# --- FONCTION DE GENERATION DU HASH APPAREIL ---
def generate_device_hash(dev_id):
    try:
        user_agent = streamlit_js_eval(
            js_expressions="navigator.userAgent", key="get_user_agent"
        )
    except Exception:
        user_agent = "Unknown"

    raw_fingerprint = f"{dev_id}-{user_agent}"
    return hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()[:16]


# --- AUTHENTIFICATION AUTHENTIK ---
# --- AUTHENTIFICATION AUTHENTIK ---
if not st.user.get("is_logged_in", False):
    st.title("🔐 Connexion Pointage GPS")
    if st.button("Se connecter avec Authentik", type="primary"):
        st.login("authentik")
    st.stop()

safe_claims = {k: v for k, v in st.user.items() if k != "tokens"}
print(f"[OIDC] Claims reçus: {sorted(safe_claims)}")

auth_username = (
    st.user.get("preferred_username")
    or st.user.get("name")
    or st.user.get("sub")
)
if not auth_username:
    st.error("Identité utilisateur introuvable dans le token.")
    st.stop()

raw_org = st.user.get("organization")
auth_org = raw_org.strip().casefold() if isinstance(raw_org, str) else ""
if not auth_org:
    st.error("Aucune organisation associée à ce compte.")
    st.stop()

current_user = auth_username
current_user_org = auth_org
print(f"[OIDC] Authenticated user: {auth_username!r}, org: {auth_org!r}")

# --- DETERMINATION DE LA DERNIERE ACTION DU USER ---
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_init = pd.read_csv(LOG_FILE, on_bad_lines="skip")
        if (
            not df_init.empty
            and "Action" in df_init.columns
            and "Utilisateur" in df_init.columns
        ):
            user_logs = df_init[df_init["Utilisateur"] == current_user]
            if not user_logs.empty:
                st.session_state.last_action = user_logs["Action"].iloc[-1]
    except Exception:
        pass


# --- INTERFACE PRINCIPALE ---
st.markdown(
    """
    <style>
    div.stButton > button {
        width: 100%;
        height: 60px;
        font-size: 18px !important;
        font-weight: bold;
    }
    </style>
""",
    unsafe_allow_html=True,
)

col_header, col_logout = st.columns([3, 1])
with col_header:
    st.title("📍 Pointage GPS")
    st.write(f"👤 **Utilisateur :** `{current_user}` ({current_user_org})")
with col_logout:
    st.write("")
    if st.button("🚪 Déconnexion", key="btn_logout"):
        st.session_state.last_action = None
        st.session_state.action_type = None
        st.logout()

st.divider()

# Récupération des POI autorisés en fonction de l'organisation de l'utilisateur
available_pois = POI_LIST.get(current_user_org, [])
if available_pois:
    selected_poi = st.selectbox("📌 Sélectionner un Lieu pré-défini :", available_pois)
else:
    selected_poi = None
    st.warning("Aucun lieu n'est configuré pour votre organisation.")

st.divider()

is_checkin_disabled = st.session_state.last_action == "Check-in"
is_checkout_disabled = (
    st.session_state.last_action == "Check-out"
    or st.session_state.last_action is None
)

col1, col2 = st.columns(2)

with col1:
    if st.button(
        "🟢 Arrivée",
        type="primary",
        disabled=is_checkin_disabled or selected_poi is None,
        key="btn_checkin",
    ):
        st.session_state.action_type = "Check-in"

with col2:
    if st.button(
        "🔴 Départ",
        disabled=is_checkout_disabled or selected_poi is None,
        key="btn_checkout",
    ):
        st.session_state.action_type = "Check-out"


# --- TRAITEMENT DU POINTAGE ---
if st.session_state.action_type and selected_poi is not None:
    st.info(
        f"Demande de localisation en cours pour **{st.session_state.action_type}** à **{selected_poi}**..."
    )

    loc = get_geolocation()

    if loc and "coords" in loc:
        lat = loc["coords"]["latitude"]
        lon = loc["coords"]["longitude"]
        accuracy = loc["coords"]["accuracy"]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        device_hash = generate_device_hash(device_id)

        new_entry = {
            "Horodatage": now,
            "Utilisateur": current_user,
            "POI": selected_poi,
            "Action": st.session_state.action_type,
            "Latitude": lat,
            "Longitude": lon,
            "Précision (m)": round(accuracy, 1),
            "Device_Hash": device_hash,
        }

        df_new = pd.DataFrame([new_entry])
        if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
            df_new.to_csv(LOG_FILE, index=False)
        else:
            df_new.to_csv(LOG_FILE, mode="a", header=False, index=False)

        st.session_state.last_action = st.session_state.action_type

        st.success(
            f"✅ **{st.session_state.action_type} enregistré !** ({now})"
        )

        osm_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}"
        st.markdown(
            f"📍 **Lieu :** {selected_poi} (`{lat}, {lon}`) — [Voir sur OpenStreetMap]({osm_url})"
        )
        st.caption(f"🔒 *Empreinte appareil : `{device_hash}`*")

        st.session_state.action_type = None
        st.rerun()

    elif loc is False:
        st.error(
            "❌ Géolocalisation refusée par le navigateur ou indisponible."
        )
        st.session_state.action_type = None

st.divider()

# --- HISTORIQUE DES POINTAGES ---
st.subheader("📋 Mon historique de pointages")
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_logs = pd.read_csv(LOG_FILE, on_bad_lines="skip")
        if not df_logs.empty and "Utilisateur" in df_logs.columns:
            df_user_logs = df_logs[df_logs["Utilisateur"] == current_user]
            if not df_user_logs.empty:
                selected_columns = [
                    "Horodatage",
                    "Action",
                    "POI",
                    "Latitude",
                    "Longitude",
                ]
                available_cols = [
                    c for c in selected_columns if c in df_user_logs.columns
                ]
                st.dataframe(
                    df_user_logs[available_cols].sort_index(ascending=False),
                    width="content",
                )
            else:
                st.info("Aucun pointage trouvé pour votre compte.")
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier CSV : {e}")
else:
    st.info("Aucun pointage archivé pour le moment.")