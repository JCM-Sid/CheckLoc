import datetime
import hashlib
import os
import time
import uuid
import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
from streamlit_js_eval import get_geolocation, streamlit_js_eval
import hashlib

import os
from pathlib import Path
import uuid

from flet.auth import OAuthProvider
from dotenv import load_dotenv


### --- Config Authentik ----
# Charge le fichier d'environnement spécifique
env_path = Path(__file__).parent / ".env_secrets"
load_dotenv(dotenv_path=env_path)


AK = "https://auth.apps.ddcm.fr"
authentik_provider = OAuthProvider(
    client_id=os.environ["authentik_client_id"],
    client_secret=os.environ["Aauthentik_client_secret"],
    authorization_endpoint=f"{AK}/application/o/authorize/",
    token_endpoint=f"{AK}/application/o/token/",
    user_endpoint=f"{AK}/application/o/userinfo/",
    user_scopes=["openid", "profile", "email"],
    user_id_fn=lambda u: u.get("preferred_username") or u.get("sub"),
    redirect_url="https://checkloc.apps.ddcm.fr/oauth_callback",
)




LOG_FILE = "log_location.csv"

# --- CONFIGURATION UTILISATEURS & POI ---
USERS_DB = {
    "JCM": {"pwd": "poc", "org": "Perso"},
    "Nico": {"pwd": "test", "org": "ATAE"},
}

POI_LIST = {
    "Perso": ["Maison", "Bureau", "Bois", "Piece d'eau", "Chateau", "nouveau"],
    "ATAE": ["Maison", "Bureau", "Chantier1", "Chantier2", "Chantier3", "Repas", "Nouveau"],
}



st.set_page_config(page_title="Pointage GPS", page_icon="📍", layout="centered")

# --- INITIALISATION DU COOKIE MANAGER ---
if "cookie_manager" not in st.session_state:
    st.session_state.cookie_manager = stx.CookieManager(
        key="init_cookie_manager"
    )

cookie_manager = st.session_state.cookie_manager

# On récupère l'ensemble des cookies disponibles
cookies = cookie_manager.get_all()

# Synchronisation du cookie d'authentification
auth_cookie = cookies.get("checkloc_user") if isinstance(cookies, dict) else None
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

# 2. Reconnexion automatique si le cookie auth valide est présent
if "user" not in st.session_state or st.session_state.user is None:
    if auth_cookie and auth_cookie in USERS_DB:
        st.session_state.user = auth_cookie
        st.session_state.user_org = USERS_DB[auth_cookie]["org"]
    else:
        st.session_state.user = None
        st.session_state.user_org = None

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


# --- ÉCRAN DE CONNEXION (Affiché uniquement si NON connecté) ---
if not st.session_state.user:
    st.title("🔐 Connexion Pointage GPS")

    with st.form("login_form"):
        username_input = st.text_input("Nom d'utilisateur")
        password_input = st.text_input("Mot de passe", type="password")
        submit_button = st.form_submit_button("Se connecter", type="primary")

        if submit_button:
            if (
                username_input in USERS_DB
                and USERS_DB[username_input]["pwd"] == password_input
            ):
                st.session_state.user = username_input
                st.session_state.user_org = USERS_DB[username_input]["org"]
                cookie_manager.set(
                    "checkloc_user",
                    username_input,
                    max_age=30 * 24 * 3600,
                    key="set_user_cookie",
                )
                st.success("Connexion réussie !")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Nom d'utilisateur ou mot de passe incorrect.")

    st.stop()


# --- DETERMINATION DE LA DERNIERE ACTION DU USER ---
if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
    try:
        df_init = pd.read_csv(LOG_FILE, on_bad_lines="skip")
        if (
            not df_init.empty
            and "Action" in df_init.columns
            and "Utilisateur" in df_init.columns
        ):
            user_logs = df_init[df_init["Utilisateur"] == st.session_state.user]
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
    st.write(f"👤 **Utilisateur :** `{st.session_state.user}` ({st.session_state.user_org})")
with col_logout:
    st.write("")
    if st.button("🚪 Déconnexion", key="btn_logout"):
        cookie_manager.delete("checkloc_user", key="delete_user_cookie")
        st.session_state.user = None
        st.session_state.user_org = None
        st.session_state.last_action = None
        time.sleep(0.5)
        st.rerun()

st.divider()

# Récupération des POI autorisés en fonction de l'organisation de l'utilisateur
available_pois = POI_LIST.get(st.session_state.user_org, [])
selected_poi = st.selectbox("📌 Sélectionner un Lieu pré-défini :", available_pois)

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
        disabled=is_checkin_disabled,
        key="btn_checkin",
    ):
        st.session_state.action_type = "Check-in"

with col2:
    if st.button(
        "🔴 Départ", disabled=is_checkout_disabled, key="btn_checkout"
    ):
        st.session_state.action_type = "Check-out"


# --- TRAITEMENT DU POINTAGE ---
if st.session_state.action_type:
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
            "Utilisateur": st.session_state.user,
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
            df_user_logs = df_logs[df_logs["Utilisateur"] == st.session_state.user]
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