import base64
import html
import io
import math
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

import folium
import numpy as np
import pandas as pd
import streamlit as st
from branca.element import MacroElement, Template
from PIL import Image
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from sklearn.cluster import KMeans
from streamlit_folium import st_folium
from supabase import Client, create_client


# ============================================================
# SISTEM PENDUKUNG KEPUTUSAN OPTIMASI DISTRIBUSI LOGISTIK
# PT BUKIT INTI MAKMUR ABADI
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "logo.jpg"
TIMEZONE = ZoneInfo("Asia/Jakarta")
RANDOM_STATE = 42
N_CLUSTERS = 4
MAX_K_OTOMATIS = 10  # dipertahankan agar fungsi lama tetap kompatibel
TECHNICAL_EMAIL_DOMAIN = "bima.app"

REQUIRED_DAILY_ORDER_COLUMNS = ["id_toko", "nama_toko", "demand"]
DAILY_DEMAND_ALIASES = ["demand", "order", "qty", "quantity", "jumlah_order"]

try:
    PAGE_ICON = Image.open(LOGO_PATH) if LOGO_PATH.exists() else "📦"
except OSError:
    PAGE_ICON = "📦"

st.set_page_config(
    page_title="SPK Distribusi PT BIMA",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


def image_to_data_uri(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_image}"


st.markdown(
    """
    <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        .bima-header {
            display:flex; align-items:center; gap:18px; margin-bottom:1rem;
        }
        .bima-header-logo { width:72px; height:auto; }
        .bima-header-title {
            margin:0; font-size:clamp(1.8rem,3vw,2.7rem); line-height:1.15;
            font-weight:750; letter-spacing:-0.02em;
        }
        .bima-header-subtitle { opacity:.72; margin-top:.3rem; }
        .bima-login-logo-wrap { display:flex; justify-content:center; margin-bottom:.7rem; }
        .bima-login-logo { width:92px; height:auto; }
        .bima-login-title { text-align:center; font-size:2rem; font-weight:750; }
        .bima-login-subtitle { text-align:center; opacity:.72; margin:.2rem 0 1rem; }
        .bima-muted { opacity:.72; }
        section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
            padding-top:.8rem;
        }
        section[data-testid="stSidebar"] button[kind="primary"] {
            font-weight:650;
        }
        @media (max-width:700px) {
            .bima-header { align-items:flex-start; gap:12px; }
            .bima-header-logo { width:54px; }
            .bima-header-title { font-size:1.55rem; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SUPABASE DAN AUTENTIKASI
# ============================================================
def get_secret(name: str) -> str:
    value = st.secrets.get(name, "")
    return str(value).strip() if value is not None else ""


def make_user_client() -> Client:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_PUBLISHABLE_KEY")
    if not url or not key:
        st.error("Konfigurasi Supabase belum lengkap pada Streamlit Secrets.")
        st.stop()
    return create_client(url, key)


def make_admin_client() -> Client:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_SECRET_KEY belum tersedia pada Streamlit Secrets.")
    return create_client(url, key)


def username_to_email(username: str) -> str:
    username = username.strip().lower()
    if "@" in username:
        return username
    return f"{username}@{TECHNICAL_EMAIL_DOMAIN}"


def clear_auth_state() -> None:
    for key in [
        "access_token", "refresh_token", "user_id", "profile", "authenticated",
        "menu_super_admin", "menu_staff", "menu_driver",
    ]:
        st.session_state.pop(key, None)


def restore_session(client: Client) -> bool:
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if not access_token or not refresh_token:
        return False
    try:
        response = client.auth.set_session(access_token, refresh_token)
        if response.session:
            st.session_state.access_token = response.session.access_token
            st.session_state.refresh_token = response.session.refresh_token
        if response.user:
            st.session_state.user_id = str(response.user.id)
        return True
    except Exception:
        clear_auth_state()
        return False


def load_current_profile(client: Client) -> dict | None:
    user_id = st.session_state.get("user_id")
    if not user_id:
        return None
    try:
        response = (
            client.table("profiles")
            .select("id,username,nama,role,vehicle_id,status")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return response.data
    except Exception:
        return None


def render_login(client: Client) -> None:
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
                display:none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    left, center, right = st.columns([1, 1.35, 1])
    with center:
        if LOGO_PATH.exists():
            try:
                uri = image_to_data_uri(LOGO_PATH)
                st.markdown(
                    f'<div class="bima-login-logo-wrap"><img class="bima-login-logo" '
                    f'src="{uri}" alt="Logo PT BIMA"></div>',
                    unsafe_allow_html=True,
                )
            except OSError:
                pass

        st.markdown(
            '<div class="bima-login-title">Masuk Sistem Pendukung Keputusan</div>'
            '<div class="bima-login-subtitle">Optimasi Distribusi Logistik PT Bukit Inti Makmur Abadi</div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            with st.form("login_form"):
                username = st.text_input("Nama Pengguna", placeholder="Masukkan nama pengguna")
                password = st.text_input("Sandi", type="password", placeholder="Masukkan kata sandi")
                submitted = st.form_submit_button("Masuk", type="primary", use_container_width=True)

        if submitted:
            if not username.strip() or not password:
                st.error("Nama pengguna dan sandi harus diisi.")
                return
            try:
                auth = client.auth.sign_in_with_password(
                    {"email": username_to_email(username), "password": password}
                )
                if not auth.user or not auth.session:
                    st.error("Login gagal.")
                    return

                st.session_state.access_token = auth.session.access_token
                st.session_state.refresh_token = auth.session.refresh_token
                st.session_state.user_id = str(auth.user.id)
                profile = load_current_profile(client)

                if not profile:
                    client.auth.sign_out()
                    clear_auth_state()
                    st.error("Profil pengguna tidak ditemukan.")
                    return
                if not bool(profile.get("status", False)):
                    client.auth.sign_out()
                    clear_auth_state()
                    st.error("Akun sedang dinonaktifkan.")
                    return

                st.session_state.profile = profile
                st.session_state.authenticated = True
                st.rerun()
            except Exception:
                st.error("Nama pengguna atau sandi tidak sesuai.")


def render_app_header(role_label: str | None = None) -> None:
    role_html = f'<div class="bima-header-subtitle">{html.escape(role_label)}</div>' if role_label else ""
    if LOGO_PATH.exists():
        try:
            uri = image_to_data_uri(LOGO_PATH)
            st.markdown(
                f"""
                <div class="bima-header">
                    <img class="bima-header-logo" src="{uri}" alt="Logo PT BIMA">
                    <div>
                        <div class="bima-header-title">Sistem Pendukung Keputusan Optimasi Distribusi Logistik</div>
                        <div class="bima-header-subtitle">PT Bukit Inti Makmur Abadi</div>
                        {role_html}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return
        except OSError:
            pass
    st.title("Sistem Pendukung Keputusan Optimasi Distribusi Logistik")
    st.caption("PT Bukit Inti Makmur Abadi")


def perform_logout(client: Client) -> None:
    try:
        client.auth.sign_out()
    except Exception:
        pass
    clear_auth_state()
    st.rerun()


# ============================================================
# UTILITAS DATA DAN DATABASE
# ============================================================
def today_jakarta() -> date:
    return datetime.now(TIMEZONE).date()


def normalize_store_id(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].replace("-", "", 1).isdigit():
        return text[:-2]
    return text


def normalize_text(value) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [str(c).strip().lower() for c in result.columns]
    return result


def read_excel(uploaded_file) -> pd.DataFrame:
    return normalize_column_names(pd.read_excel(io.BytesIO(uploaded_file.getvalue())))


def fetch_all(client: Client, table: str, columns: str = "*", order_by: str | None = None) -> list[dict]:
    rows: list[dict] = []
    start = 0
    page_size = 1000
    while True:
        query = client.table(table).select(columns).range(start, start + page_size - 1)
        if order_by:
            query = query.order(order_by)
        response = query.execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def get_stores_df(client: Client) -> pd.DataFrame:
    rows = fetch_all(
        client,
        "stores",
        "id,id_toko,nama_toko,alamat,longitude,latitude,zona,status",
        "id",
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["id","id_toko","nama_toko","alamat","longitude","latitude","zona","status"])
    df["id_toko"] = df["id_toko"].apply(normalize_store_id)
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["status"] = df["status"].fillna(False).astype(bool)
    return df


def get_vehicles_df(client: Client) -> pd.DataFrame:
    rows = fetch_all(
        client,
        "vehicles",
        "id,kode_mobil,no_mobil,supir,tipe_mobil,maks_kapasitas,status",
        "id",
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["id","kode_mobil","no_mobil","supir","tipe_mobil","maks_kapasitas","status"])
    df["maks_kapasitas"] = pd.to_numeric(df["maks_kapasitas"], errors="coerce")
    df["status"] = df["status"].fillna(False).astype(bool)
    return df


def split_depot_and_customers(stores_df: pd.DataFrame) -> Tuple[pd.Series, pd.DataFrame]:
    depot_rows = stores_df[stores_df["id_toko"] == "0"]
    if depot_rows.empty:
        raise ValueError("Depot dengan id_toko = 0 tidak ditemukan pada Master Toko.")
    depot = depot_rows.iloc[0]
    customers = stores_df[stores_df["id_toko"] != "0"].copy().reset_index(drop=True)
    return depot, customers


def get_recommendation_for_date(client: Client, tanggal: date) -> dict | None:
    response = (
        client.table("recommendations")
        .select("*")
        .eq("tanggal", tanggal.isoformat())
        .execute()
    )
    data = response.data or []
    return data[0] if data else None


def date_is_locked(client: Client, tanggal: date) -> tuple[bool, str]:
    if tanggal < today_jakarta():
        return True, "Tanggal sudah lewat sehingga data terkunci."
    rec = get_recommendation_for_date(client, tanggal)
    if rec and rec.get("status") == "ditetapkan":
        return True, "Rute tanggal tersebut sudah ditetapkan sehingga data terkunci."
    return False, ""


def delete_unfinalized_recommendation(client: Client, tanggal: date) -> None:
    rec = get_recommendation_for_date(client, tanggal)
    if not rec:
        return
    if rec.get("status") == "ditetapkan" or tanggal < today_jakarta():
        raise ValueError("Rekomendasi sudah terkunci dan tidak dapat dihapus.")

    rec_id = int(rec["id"])
    route_response = client.table("routes").select("id").eq("recommendation_id", rec_id).execute()
    route_ids = [int(r["id"]) for r in (route_response.data or [])]
    if route_ids:
        client.table("route_stops").delete().in_("route_id", route_ids).execute()
        client.table("routes").delete().eq("recommendation_id", rec_id).execute()
    client.table("recommendations").delete().eq("id", rec_id).execute()


def format_qty(value: float) -> str:
    numeric_value = float(value)
    if numeric_value.is_integer():
        return f"{int(numeric_value):,}".replace(",", ".")
    return f"{numeric_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_distance_km(value: float) -> str:
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# ALGORITMA JARAK, ALOKASI, DAN CLARKE & WRIGHT
# ============================================================
def euclidean_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Menghitung jarak Euclidean koordinat yang dikonversi ke kilometer."""
    mean_lat_rad = math.radians((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * 110.574
    dx = (lon2 - lon1) * 111.320 * math.cos(mean_lat_rad)
    return math.sqrt(dx**2 + dy**2)


def distance_depot_to_customer(depot: pd.Series, customer: pd.Series) -> float:
    return euclidean_distance_km(
        float(depot["latitude"]),
        float(depot["longitude"]),
        float(customer["latitude"]),
        float(customer["longitude"]),
    )


def distance_between_customers(customer_a: pd.Series, customer_b: pd.Series) -> float:
    return euclidean_distance_km(
        float(customer_a["latitude"]),
        float(customer_a["longitude"]),
        float(customer_b["latitude"]),
        float(customer_b["longitude"]),
    )


def determine_optimal_k(customers: pd.DataFrame, max_k: int = MAX_K_OTOMATIS) -> Tuple[int, pd.DataFrame]:
    """
    Menentukan jumlah zona secara otomatis dari titik siku kurva WCSS.

    Nilai maksimum K merupakan konfigurasi internal sehingga pengguna tidak perlu
    menentukan parameter metode melalui tampilan aplikasi.
    """
    x = customers[["longitude", "latitude"]].to_numpy()
    n_samples = len(x)
    unique_coordinate_count = len(np.unique(x, axis=0))

    if n_samples == 1 or unique_coordinate_count == 1:
        return 1, pd.DataFrame([{"K": 1, "WCSS/Inertia": 0.0}])

    max_valid_k = min(max_k, n_samples, unique_coordinate_count)
    rows = []

    for k in range(1, max_valid_k + 1):
        model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        model.fit(x)
        rows.append({"K": k, "WCSS/Inertia": float(model.inertia_)})

    evaluation_df = pd.DataFrame(rows)

    if max_valid_k <= 2:
        return max_valid_k, evaluation_df

    k_values = evaluation_df["K"].to_numpy(dtype=float)
    inertia_values = evaluation_df["WCSS/Inertia"].to_numpy(dtype=float)

    k_range = k_values.max() - k_values.min()
    inertia_range = inertia_values.max() - inertia_values.min()

    if k_range == 0 or inertia_range == 0:
        return 2, evaluation_df

    x_normalized = (k_values - k_values.min()) / k_range
    y_normalized = (inertia_values - inertia_values.min()) / inertia_range

    # Jarak vertikal terhadap garis dari titik pertama ke titik terakhir.
    knee_scores = (1 - x_normalized) - y_normalized
    candidate_indices = np.arange(1, len(k_values) - 1)

    if len(candidate_indices) == 0:
        selected_k = 2
    else:
        selected_index = candidate_indices[np.argmax(knee_scores[candidate_indices])]
        selected_k = int(k_values[selected_index])

    selected_k = max(2, min(selected_k, max_valid_k))
    evaluation_df["K_terpilih"] = evaluation_df["K"] == selected_k
    return selected_k, evaluation_df


def run_kmeans(customers: pd.DataFrame, n_clusters: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Membagi seluruh master toko ke dalam zona distribusi."""
    df = customers.copy()
    x = df[["longitude", "latitude"]].to_numpy()

    model = KMeans(n_clusters=n_clusters, random_state=RANDOM_STATE, n_init=10)
    df["cluster"] = model.fit_predict(x) + 1

    centroid_df = pd.DataFrame(
        model.cluster_centers_,
        columns=["centroid_longitude", "centroid_latitude"],
    )
    centroid_df.insert(0, "cluster", range(1, n_clusters + 1))

    cluster_size = df.groupby("cluster").size().reset_index(name="jumlah_toko")
    centroid_df = centroid_df.merge(cluster_size, on="cluster", how="left")
    return df, centroid_df


def route_distance(route: List[int], cluster_data: pd.DataFrame, depot: pd.Series) -> float:
    """Menghitung jarak rute depot -> toko -> depot."""
    if not route:
        return 0.0

    total_distance = distance_depot_to_customer(depot, cluster_data.iloc[route[0]])

    for position in range(len(route) - 1):
        total_distance += distance_between_customers(
            cluster_data.iloc[route[position]],
            cluster_data.iloc[route[position + 1]],
        )

    total_distance += distance_depot_to_customer(depot, cluster_data.iloc[route[-1]])
    return total_distance


def calculate_savings_matrix(cluster_data: pd.DataFrame, depot: pd.Series) -> pd.DataFrame:
    """Menghitung nilai penghematan untuk seluruh pasangan toko dalam satu zona."""
    rows = []
    n_customers = len(cluster_data)
    depot_distances = [
        distance_depot_to_customer(depot, cluster_data.iloc[index])
        for index in range(n_customers)
    ]

    for i in range(n_customers):
        for j in range(i + 1, n_customers):
            distance_i_j = distance_between_customers(cluster_data.iloc[i], cluster_data.iloc[j])
            saving = depot_distances[i] + depot_distances[j] - distance_i_j
            rows.append({"idx_i": i, "idx_j": j, "savings_km": saving})

    if not rows:
        return pd.DataFrame(columns=["idx_i", "idx_j", "savings_km"])

    return pd.DataFrame(rows).sort_values("savings_km", ascending=False).reset_index(drop=True)


def find_route_index(routes: List[List[int]], node: int) -> int:
    """Mencari indeks rute yang memuat node tertentu."""
    for index, route in enumerate(routes):
        if node in route:
            return index
    return -1


def try_merge_routes(route_i: List[int], route_j: List[int], i: int, j: int) -> List[int] | None:
    """Menggabungkan dua rute jika kedua toko berada di ujung rute."""
    if route_i[-1] == i and route_j[0] == j:
        return route_i + route_j
    if route_i[0] == i and route_j[-1] == j:
        return route_j + route_i
    if route_i[0] == i and route_j[0] == j:
        return list(reversed(route_i)) + route_j
    if route_i[-1] == i and route_j[-1] == j:
        return route_i + list(reversed(route_j))
    return None


def build_single_vehicle_route(
    vehicle_customers: pd.DataFrame,
    depot: pd.Series,
    vehicle_capacity: float,
) -> Tuple[List[int], float]:
    """
    Menyusun satu rute untuk pelanggan yang telah dialokasikan ke satu armada.

    Penggabungan awal mengikuti urutan nilai savings. Jika masih tersisa lebih
    dari satu rangkaian, rangkaian digabungkan dengan orientasi berjarak paling
    kecil. Seluruh pelanggan dalam fungsi ini telah dipastikan muat pada satu
    armada.
    """
    data = vehicle_customers.reset_index(drop=True).copy()
    n_customers = len(data)

    if n_customers == 0:
        return [], 0.0

    total_demand = float(data["demand"].sum())
    if total_demand > vehicle_capacity + 1e-9:
        raise ValueError("Total permintaan rute melebihi kapasitas armada.")

    savings_df = calculate_savings_matrix(data, depot)
    routes = [[index] for index in range(n_customers)]
    route_demands = [float(data.iloc[index]["demand"]) for index in range(n_customers)]

    for _, saving_row in savings_df.iterrows():
        i = int(saving_row["idx_i"])
        j = int(saving_row["idx_j"])

        route_i_index = find_route_index(routes, i)
        route_j_index = find_route_index(routes, j)

        if route_i_index == -1 or route_j_index == -1 or route_i_index == route_j_index:
            continue

        candidate_demand = route_demands[route_i_index] + route_demands[route_j_index]
        if candidate_demand > vehicle_capacity + 1e-9:
            continue

        merged_route = try_merge_routes(
            routes[route_i_index],
            routes[route_j_index],
            i,
            j,
        )

        if merged_route is None:
            continue

        keep_index = min(route_i_index, route_j_index)
        remove_index = max(route_i_index, route_j_index)
        routes[keep_index] = merged_route
        route_demands[keep_index] = candidate_demand
        routes.pop(remove_index)
        route_demands.pop(remove_index)

    # Menjamin satu armada menghasilkan tepat satu rute.
    while len(routes) > 1:
        best_candidate = None

        for first_index in range(len(routes)):
            for second_index in range(first_index + 1, len(routes)):
                route_a = routes[first_index]
                route_b = routes[second_index]
                combined_demand = route_demands[first_index] + route_demands[second_index]

                if combined_demand > vehicle_capacity + 1e-9:
                    continue

                candidates = [
                    route_a + route_b,
                    route_a + list(reversed(route_b)),
                    list(reversed(route_a)) + route_b,
                    list(reversed(route_a)) + list(reversed(route_b)),
                ]

                for candidate_route in candidates:
                    candidate_distance = route_distance(candidate_route, data, depot)
                    if best_candidate is None or candidate_distance < best_candidate[0]:
                        best_candidate = (
                            candidate_distance,
                            first_index,
                            second_index,
                            candidate_route,
                            combined_demand,
                        )

        if best_candidate is None:
            raise ValueError("Rangkaian pelanggan tidak dapat digabungkan menjadi satu rute armada.")

        _, first_index, second_index, merged_route, combined_demand = best_candidate
        routes[first_index] = merged_route
        route_demands[first_index] = combined_demand
        routes.pop(second_index)
        route_demands.pop(second_index)

    final_route = routes[0]
    return final_route, route_distance(final_route, data, depot)


def allocate_customers_to_fleet(
    active_customers: pd.DataFrame,
    vehicles_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Mengalokasikan armada ke zona, lalu mengalokasikan toko ke armada.

    Model dibuat dua tahap agar tetap cepat untuk ratusan toko:
    1. menentukan armada yang digunakan pada setiap zona;
    2. membagi toko pada armada terpilih sesuai kapasitas.

    Ketentuan yang dijaga:
    - satu toko dilayani tepat satu armada;
    - satu armada hanya melayani satu zona;
    - total muatan tidak melebihi kapasitas armada;
    - satu armada menghasilkan satu rute;
    - jumlah rute tidak melebihi jumlah armada.
    """
    customers = active_customers.reset_index(drop=True).copy()
    vehicles = vehicles_df.reset_index(drop=True).copy()

    customer_demands = customers["demand"].to_numpy(dtype=float)
    vehicle_capacities = vehicles["maks_kapasitas"].to_numpy(dtype=float)
    zone_ids = sorted(customers["cluster"].astype(int).unique().tolist())
    zone_to_position = {zone_id: position for position, zone_id in enumerate(zone_ids)}

    total_demand = float(customer_demands.sum())
    total_capacity = float(vehicle_capacities.sum())
    max_vehicle_capacity = float(vehicle_capacities.max())
    max_customer_demand = float(customer_demands.max())

    if max_customer_demand > max_vehicle_capacity + 1e-9:
        st.error(
            "Distribusi tidak dapat dijalankan dalam satu perjalanan karena terdapat "
            "permintaan toko yang melebihi kapasitas armada terbesar."
        )
        st.stop()

    if total_demand > total_capacity + 1e-9:
        st.error(
            "Distribusi tidak dapat diselesaikan dalam satu periode pengiriman karena "
            "total permintaan melebihi total kapasitas seluruh armada."
        )
        st.stop()

    if len(zone_ids) > len(vehicles):
        st.error(
            "Jumlah wilayah aktif lebih banyak daripada jumlah armada. Setiap wilayah "
            "memerlukan sedikitnya satu armada agar rute tidak digabungkan antarwilayah."
        )
        st.stop()

    n_vehicles = len(vehicles)
    n_zones = len(zone_ids)

    def y_index(vehicle_index: int, zone_position: int) -> int:
        return vehicle_index * n_zones + zone_position

    # ========================================================
    # TAHAP 1: ALOKASI ARMADA KE ZONA
    # ========================================================
    variable_count = n_vehicles * n_zones
    objective = np.zeros(variable_count, dtype=float)

    # Jumlah armada menjadi prioritas utama. Di antara solusi dengan jumlah
    # armada sama, dipilih kombinasi kapasitas yang lebih mendekati kebutuhan.
    for vehicle_index, capacity in enumerate(vehicle_capacities):
        for zone_position in range(n_zones):
            objective[y_index(vehicle_index, zone_position)] = 1000.0 + capacity * 0.0001

    constraint_rows = []
    constraint_lower = []
    constraint_upper = []

    # Satu armada hanya boleh dialokasikan ke satu zona.
    for vehicle_index in range(n_vehicles):
        row_values = {}
        for zone_position in range(n_zones):
            row_values[y_index(vehicle_index, zone_position)] = 1.0
        constraint_rows.append(row_values)
        constraint_lower.append(-np.inf)
        constraint_upper.append(1.0)

    # Total kapasitas armada pada setiap zona harus mencukupi total permintaan.
    for zone_id in zone_ids:
        zone_position = zone_to_position[zone_id]
        zone_demands = customers.loc[
            customers["cluster"].astype(int) == zone_id,
            "demand",
        ].to_numpy(dtype=float)

        capacity_row = {
            y_index(vehicle_index, zone_position): float(capacity)
            for vehicle_index, capacity in enumerate(vehicle_capacities)
        }
        constraint_rows.append(capacity_row)
        constraint_lower.append(float(zone_demands.sum()))
        constraint_upper.append(np.inf)

        # Kendala jumlah slot membantu memastikan komposisi kapasitas armada
        # sesuai dengan ukuran pesanan individual, bukan hanya totalnya.
        for demand_threshold in np.unique(zone_demands):
            required_slots = int(np.sum(zone_demands >= demand_threshold - 1e-9))
            slot_row = {
                y_index(vehicle_index, zone_position): float(
                    math.floor(capacity / demand_threshold + 1e-9)
                )
                for vehicle_index, capacity in enumerate(vehicle_capacities)
                if capacity + 1e-9 >= demand_threshold
            }
            constraint_rows.append(slot_row)
            constraint_lower.append(float(required_slots))
            constraint_upper.append(np.inf)

    matrix = lil_matrix((len(constraint_rows), variable_count), dtype=float)
    for row_index, row_values in enumerate(constraint_rows):
        for column_index, value in row_values.items():
            matrix[row_index, column_index] = value

    zone_result = milp(
        c=objective,
        integrality=np.ones(variable_count, dtype=int),
        bounds=Bounds(
            np.zeros(variable_count, dtype=float),
            np.ones(variable_count, dtype=float),
        ),
        constraints=LinearConstraint(
            matrix.tocsr(),
            np.asarray(constraint_lower, dtype=float),
            np.asarray(constraint_upper, dtype=float),
        ),
        options={"time_limit": 20.0, "mip_rel_gap": 0.0, "disp": False},
    )

    if zone_result.x is None or not zone_result.success:
        st.error(
            "Permintaan belum dapat dibagi ke armada dalam satu periode pengiriman. "
            "Komposisi kapasitas kendaraan belum mencukupi kebutuhan setiap wilayah."
        )
        st.stop()

    zone_vehicle_matrix = np.rint(zone_result.x).reshape(n_vehicles, n_zones)
    zone_vehicle_indices = {
        zone_id: np.where(zone_vehicle_matrix[:, zone_to_position[zone_id]] == 1)[0].tolist()
        for zone_id in zone_ids
    }

    # ========================================================
    # TAHAP 2: ALOKASI TOKO KE ARMADA TERPILIH
    # ========================================================
    allocation_parts = []

    for zone_id in zone_ids:
        zone_customers = customers[
            customers["cluster"].astype(int) == zone_id
        ].copy()
        original_indices = zone_customers.index.to_numpy(dtype=int)
        zone_customers = zone_customers.reset_index(drop=True)

        selected_vehicle_indices = zone_vehicle_indices[zone_id]
        if not selected_vehicle_indices:
            st.error(f"Tidak ada armada yang teralokasi untuk wilayah {zone_id}.")
            st.stop()

        selected_capacities = vehicle_capacities[selected_vehicle_indices]
        n_zone_customers = len(zone_customers)
        n_selected_vehicles = len(selected_vehicle_indices)
        assignment_variable_count = n_zone_customers * n_selected_vehicles

        def x_index(customer_index: int, local_vehicle_index: int) -> int:
            return customer_index * n_selected_vehicles + local_vehicle_index

        assignment_objective = np.zeros(assignment_variable_count, dtype=float)

        # Mengurutkan toko berdasarkan sudut terhadap pusat zona agar pembagian
        # antarrute cenderung membentuk sektor yang berdekatan.
        center_lat = float(zone_customers["latitude"].mean())
        center_lon = float(zone_customers["longitude"].mean())
        angles = np.arctan2(
            zone_customers["latitude"].to_numpy(dtype=float) - center_lat,
            zone_customers["longitude"].to_numpy(dtype=float) - center_lon,
        )
        angle_order = np.argsort(angles)
        customer_positions = np.zeros(n_zone_customers, dtype=float)
        customer_denominator = max(n_zone_customers - 1, 1)
        for rank, customer_index in enumerate(angle_order):
            customer_positions[customer_index] = rank / customer_denominator

        vehicle_positions = (
            np.linspace(0.0, 1.0, n_selected_vehicles)
            if n_selected_vehicles > 1
            else np.array([0.5])
        )

        for customer_index in range(n_zone_customers):
            for local_vehicle_index in range(n_selected_vehicles):
                assignment_objective[x_index(customer_index, local_vehicle_index)] = abs(
                    customer_positions[customer_index] - vehicle_positions[local_vehicle_index]
                )

        assignment_lower_bounds = np.zeros(assignment_variable_count, dtype=float)
        assignment_upper_bounds = np.ones(assignment_variable_count, dtype=float)

        zone_demands = zone_customers["demand"].to_numpy(dtype=float)
        for customer_index, demand in enumerate(zone_demands):
            for local_vehicle_index, capacity in enumerate(selected_capacities):
                if demand > capacity + 1e-9:
                    assignment_upper_bounds[x_index(customer_index, local_vehicle_index)] = 0.0

        assignment_constraint_count = (
            n_zone_customers
            + n_selected_vehicles
            + n_selected_vehicles
        )
        assignment_matrix = lil_matrix(
            (assignment_constraint_count, assignment_variable_count),
            dtype=float,
        )
        assignment_constraint_lower = np.full(
            assignment_constraint_count,
            -np.inf,
            dtype=float,
        )
        assignment_constraint_upper = np.full(
            assignment_constraint_count,
            np.inf,
            dtype=float,
        )
        row = 0

        # Setiap toko dilayani tepat satu armada.
        for customer_index in range(n_zone_customers):
            for local_vehicle_index in range(n_selected_vehicles):
                assignment_matrix[row, x_index(customer_index, local_vehicle_index)] = 1.0
            assignment_constraint_lower[row] = 1.0
            assignment_constraint_upper[row] = 1.0
            row += 1

        # Muatan setiap armada tidak boleh melebihi kapasitasnya.
        for local_vehicle_index, capacity in enumerate(selected_capacities):
            for customer_index, demand in enumerate(zone_demands):
                assignment_matrix[row, x_index(customer_index, local_vehicle_index)] = demand
            assignment_constraint_upper[row] = capacity
            row += 1

        # Setiap armada yang telah dipilih harus memperoleh sedikitnya satu toko.
        for local_vehicle_index in range(n_selected_vehicles):
            for customer_index in range(n_zone_customers):
                assignment_matrix[row, x_index(customer_index, local_vehicle_index)] = 1.0
            assignment_constraint_lower[row] = 1.0
            row += 1

        assignment_result = milp(
            c=assignment_objective,
            integrality=np.ones(assignment_variable_count, dtype=int),
            bounds=Bounds(assignment_lower_bounds, assignment_upper_bounds),
            constraints=LinearConstraint(
                assignment_matrix.tocsr(),
                assignment_constraint_lower,
                assignment_constraint_upper,
            ),
            options={"time_limit": 20.0, "mip_rel_gap": 0.0, "disp": False},
        )

        if assignment_result.x is None or not assignment_result.success:
            st.error(
                f"Permintaan pada wilayah {zone_id} belum dapat dimuat ke armada "
                "yang tersedia dalam satu perjalanan."
            )
            st.stop()

        assignment_values = np.rint(assignment_result.x).reshape(
            n_zone_customers,
            n_selected_vehicles,
        )
        selected_local_vehicle = assignment_values.argmax(axis=1).astype(int)
        selected_global_vehicle = [
            selected_vehicle_indices[local_index]
            for local_index in selected_local_vehicle
        ]

        zone_allocation = zone_customers.copy()
        zone_allocation["_customer_index"] = original_indices
        zone_allocation["_vehicle_index"] = selected_global_vehicle
        allocation_parts.append(zone_allocation)

    allocation = pd.concat(allocation_parts, ignore_index=True)

    used_vehicle_count = allocation["_vehicle_index"].nunique()
    if used_vehicle_count > len(vehicles):
        raise ValueError("Jumlah armada yang digunakan melebihi armada tersedia.")

    return allocation

def build_routes_from_allocation(
    allocated_customers: pd.DataFrame,
    vehicles_df: pd.DataFrame,
    depot: pd.Series,
) -> pd.DataFrame:
    """Membentuk tepat satu rute untuk setiap armada yang digunakan."""
    route_rows = []

    for vehicle_index in sorted(allocated_customers["_vehicle_index"].unique()):
        vehicle = vehicles_df.iloc[int(vehicle_index)]
        vehicle_customers = allocated_customers[
            allocated_customers["_vehicle_index"] == vehicle_index
        ].copy().reset_index(drop=True)

        zone_values = vehicle_customers["cluster"].astype(int).unique()
        if len(zone_values) != 1:
            raise ValueError("Satu armada teralokasi pada lebih dari satu zona.")

        route_local_indices, total_distance = build_single_vehicle_route(
            vehicle_customers=vehicle_customers,
            depot=depot,
            vehicle_capacity=float(vehicle["maks_kapasitas"]),
        )

        ordered_customers = vehicle_customers.iloc[route_local_indices]
        global_customer_indices = ordered_customers["_customer_index"].astype(int).tolist()
        total_demand = float(ordered_customers["demand"].sum())
        utilization = total_demand / float(vehicle["maks_kapasitas"]) * 100

        route_rows.append(
            {
                "cluster": int(zone_values[0]),
                "node_indices": global_customer_indices,
                "id_toko_sequence": " -> ".join(ordered_customers["id_toko"].astype(str)),
                "nama_toko_sequence": " -> ".join(ordered_customers["nama_toko"].astype(str)),
                "jumlah_toko": len(ordered_customers),
                "total_demand": total_demand,
                "total_jarak_km": float(total_distance),
                "vehicle_id": int(vehicle["id"]),
                "kode_mobil": vehicle["kode_mobil"],
                "no_mobil": vehicle["no_mobil"],
                "supir": vehicle["supir"],
                "tipe_mobil": vehicle["tipe_mobil"],
                "maks_kapasitas": float(vehicle["maks_kapasitas"]),
                "utilisasi_persen": utilization,
                "status_armada": "Teralokasi",
            }
        )

    if not route_rows:
        return pd.DataFrame()

    routes_df = pd.DataFrame(route_rows)
    routes_df = routes_df.sort_values(
        ["cluster", "total_demand"],
        ascending=[True, False],
    ).reset_index(drop=True)
    routes_df["route_local_id"] = routes_df.groupby("cluster").cumcount() + 1
    routes_df.insert(0, "route_id", range(1, len(routes_df) + 1))

    if len(routes_df) > len(vehicles_df):
        raise ValueError("Jumlah rute melebihi jumlah armada tersedia.")

    return routes_df

# ============================================================
# VISUALISASI PETA
# ============================================================
def make_base_map(depot: pd.Series, zoom_start: int = 10) -> folium.Map:
    fmap = folium.Map(
        location=[float(depot["latitude"]), float(depot["longitude"])],
        zoom_start=zoom_start,
        tiles="OpenStreetMap",
    )

    folium.Marker(
        location=[float(depot["latitude"]), float(depot["longitude"])],
        popup="DEPOT - PT Bukit Inti Makmur Abadi",
        tooltip="Depot",
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
    ).add_to(fmap)

    return fmap


def plot_zone_map(customers: pd.DataFrame, depot: pd.Series) -> folium.Map:
    fmap = make_base_map(depot)
    colors = [
        "blue", "green", "purple", "orange", "darkred", "cadetblue",
        "darkpurple", "pink", "darkblue", "darkgreen", "lightblue", "lightgreen",
    ]

    for _, row in customers.iterrows():
        zone = int(row["cluster"])
        folium.CircleMarker(
            location=[float(row["latitude"]), float(row["longitude"])],
            radius=4,
            color=colors[(zone - 1) % len(colors)],
            fill=True,
            fill_opacity=0.75,
            popup=f"{row['id_toko']} - {row['nama_toko']}<br>Zona: {zone}",
        ).add_to(fmap)

    return fmap


def plot_before_optimization_map(active_customers: pd.DataFrame, depot: pd.Series) -> folium.Map:
    fmap = make_base_map(depot)
    depot_point = [float(depot["latitude"]), float(depot["longitude"])]

    for _, row in active_customers.iterrows():
        customer_point = [float(row["latitude"]), float(row["longitude"])]
        folium.CircleMarker(
            location=customer_point,
            radius=3,
            color="gray",
            fill=True,
            fill_opacity=0.6,
            popup=f"{row['id_toko']} - {row['nama_toko']}<br>Qty: {row['demand']}",
        ).add_to(fmap)

        folium.PolyLine(
            locations=[depot_point, customer_point, depot_point],
            color="gray",
            weight=1,
            opacity=0.25,
        ).add_to(fmap)

    return fmap


class RouteFocusControl(MacroElement):
    """Menonjolkan satu jalur dan memudarkan jalur lainnya saat diklik."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        var {{ this.get_name() }}_layers = [
            {% for layer_name in this.route_layer_names %}
            {{ layer_name }}{% if not loop.last %},{% endif %}
            {% endfor %}
        ];

        var {{ this.get_name() }}_defaultStyles =
            {{ this.get_name() }}_layers.map(function(layer) {
                return {
                    weight: layer.options.weight || 4,
                    opacity: layer.options.opacity == null ? 0.82 : layer.options.opacity
                };
            });

        function {{ this.get_name() }}_resetRoutes() {
            {{ this.get_name() }}_layers.forEach(function(layer, index) {
                layer.setStyle({
                    weight: {{ this.get_name() }}_defaultStyles[index].weight,
                    opacity: {{ this.get_name() }}_defaultStyles[index].opacity
                });
            });
        }

        {{ this.get_name() }}_layers.forEach(function(selectedLayer, selectedIndex) {
            selectedLayer.on("click", function(event) {
                if (event.originalEvent) {
                    L.DomEvent.stopPropagation(event.originalEvent);
                }

                {{ this.get_name() }}_layers.forEach(function(layer, index) {
                    if (index === selectedIndex) {
                        layer.setStyle({weight: 7, opacity: 1.0});
                        if (layer.bringToFront) {
                            layer.bringToFront();
                        }
                    } else {
                        layer.setStyle({weight: 2, opacity: 0.10});
                    }
                });
            });
        });

        {{ this._parent.get_name() }}.on("click", function() {
            {{ this.get_name() }}_resetRoutes();
        });
        {% endmacro %}
        """
    )

    def __init__(self, route_layer_names: List[str]):
        super().__init__()
        self._name = "RouteFocusControl"
        self.route_layer_names = route_layer_names


def plot_after_optimization_map(
    assigned_routes: pd.DataFrame,
    active_customers: pd.DataFrame,
    depot: pd.Series,
) -> folium.Map:
    fmap = make_base_map(depot)
    depot_point = [float(depot["latitude"]), float(depot["longitude"])]
    colors = [
        "blue", "green", "purple", "orange", "darkred", "cadetblue",
        "darkpurple", "pink", "darkblue", "darkgreen", "lightblue", "lightgreen",
    ]
    route_layer_names: List[str] = []

    for _, route in assigned_routes.iterrows():
        route_points = [depot_point]
        route_color = colors[(int(route["cluster"]) - 1) % len(colors)]
        no_mobil = html.escape(str(route["no_mobil"]))
        total_qty = format_qty(float(route["total_demand"]))
        total_jarak = format_distance_km(float(route["total_jarak_km"]))

        for node in route["node_indices"]:
            customer = active_customers.iloc[int(node)]
            customer_point = [float(customer["latitude"]), float(customer["longitude"])]
            route_points.append(customer_point)

            folium.CircleMarker(
                location=customer_point,
                radius=4,
                color=route_color,
                fill=True,
                fill_opacity=0.8,
                popup=(
                    f"{customer['id_toko']} - {customer['nama_toko']}<br>"
                    f"Zona: {route['cluster']}<br>"
                    f"Rute: {route['route_id']}<br>"
                    f"Qty toko: {format_qty(float(customer['demand']))}<br>"
                    f"Armada: {no_mobil} - {html.escape(str(route['supir']))}"
                ),
            ).add_to(fmap)

        route_points.append(depot_point)
        popup_html = f"""
        <div style="font-family: Arial, sans-serif; min-width: 215px; padding: 2px 1px;">
            <div style="font-size: 15px; font-weight: 700; margin-bottom: 8px;">
                Informasi Jalur
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr>
                    <td style="padding: 4px 10px 4px 0; color: #5f6368;">No. Mobil</td>
                    <td style="padding: 4px 0; font-weight: 600; text-align: right;">{no_mobil}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; color: #5f6368;">Total Qty</td>
                    <td style="padding: 4px 0; font-weight: 600; text-align: right;">{total_qty}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 10px 4px 0; color: #5f6368;">Jarak</td>
                    <td style="padding: 4px 0; font-weight: 600; text-align: right;">{total_jarak} km</td>
                </tr>
            </table>
        </div>
        """

        route_line = folium.PolyLine(
            locations=route_points,
            color=route_color,
            weight=4,
            opacity=0.82,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"No. Mobil {no_mobil}",
            bubbling_mouse_events=False,
        )
        route_line.add_to(fmap)
        route_layer_names.append(route_line.get_name())

    if route_layer_names:
        fmap.add_child(RouteFocusControl(route_layer_names))

    return fmap


# ============================================================
# VISUALISASI TAMBAHAN DAN PERSISTENSI HASIL
# ============================================================
def prepare_zone_map_data(stores_df: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    depot, customers = split_depot_and_customers(stores_df)
    customers = customers[customers["status"] == True].copy()
    customers = customers.dropna(subset=["longitude", "latitude", "zona"])
    customers["cluster"] = customers["zona"].astype(int)
    return depot, customers


def build_active_customers_from_orders(
    orders_df: pd.DataFrame,
    stores_df: pd.DataFrame,
) -> tuple[pd.Series, pd.DataFrame]:
    depot, _ = split_depot_and_customers(stores_df)
    if orders_df.empty:
        return depot, pd.DataFrame()

    master = stores_df[stores_df["id_toko"] != "0"].copy()
    master = master.rename(columns={"id": "store_id"})
    merged = orders_df.merge(
        master[["store_id","id_toko","nama_toko","alamat","longitude","latitude","zona","status"]],
        on="store_id",
        how="left",
        validate="many_to_one",
    )
    merged = merged[merged["status"] == True].copy()
    merged["cluster"] = pd.to_numeric(merged["zona"], errors="coerce")
    if merged["cluster"].isna().any():
        missing = merged.loc[merged["cluster"].isna(), "nama_toko"].astype(str).tolist()
        raise ValueError(f"Zona belum tersedia untuk toko: {', '.join(missing[:5])}")
    merged["cluster"] = merged["cluster"].astype(int)
    merged["demand"] = pd.to_numeric(merged["demand"], errors="coerce")
    return depot, merged.reset_index(drop=True)


def save_recommendation_to_database(
    client: Client,
    tanggal: date,
    active_customers: pd.DataFrame,
    available_vehicles: pd.DataFrame,
    assigned_routes: pd.DataFrame,
    total_distance_before: float,
    total_distance_after: float,
    reduction_percentage: float,
    avg_utilization: float,
) -> int:
    existing = get_recommendation_for_date(client, tanggal)
    if existing and (existing.get("status") == "ditetapkan" or tanggal < today_jakarta()):
        raise ValueError("Rekomendasi sudah terkunci.")

    # Jika hasil sementara sudah ada, hapus detail lama terlebih dahulu.
    if existing:
        rec_id = int(existing["id"])
        route_response = client.table("routes").select("id").eq("recommendation_id", rec_id).execute()
        route_ids = [int(r["id"]) for r in (route_response.data or [])]
        if route_ids:
            client.table("route_stops").delete().in_("route_id", route_ids).execute()
            client.table("routes").delete().eq("recommendation_id", rec_id).execute()
    else:
        rec_id = -1

    payload = {
        "tanggal": tanggal.isoformat(),
        "jumlah_toko": int(len(active_customers)),
        "total_demand": float(active_customers["demand"].sum()),
        "armada_tersedia": int(len(available_vehicles)),
        "armada_digunakan": int(len(assigned_routes)),
        "jumlah_rute": int(len(assigned_routes)),
        "jarak_sebelum_km": float(total_distance_before),
        "jarak_rekomendasi_km": float(total_distance_after),
        "reduksi_jarak_persen": float(reduction_percentage),
        "rata_utilisasi_persen": float(avg_utilization),
        "status": "belum_ditetapkan",
    }

    if existing:
        response = (
            client.table("recommendations")
            .update(payload)
            .eq("id", rec_id)
            .select("id")
            .execute()
        )
        if response.data:
            rec_id = int(response.data[0]["id"])
    else:
        response = (
            client.table("recommendations")
            .insert(payload)
            .select("id")
            .execute()
        )
        if not response.data:
            raise RuntimeError("Ringkasan rekomendasi gagal disimpan.")
        rec_id = int(response.data[0]["id"])

    route_payloads = []
    for _, route in assigned_routes.iterrows():
        route_payloads.append(
            {
                "recommendation_id": rec_id,
                "nomor_rute": int(route["route_id"]),
                "zona": int(route["cluster"]),
                "vehicle_id": int(route["vehicle_id"]),
                "jumlah_toko": int(route["jumlah_toko"]),
                "total_demand": float(route["total_demand"]),
                "total_jarak_km": float(route["total_jarak_km"]),
                "utilisasi_persen": float(route["utilisasi_persen"]),
            }
        )

    route_insert = (
        client.table("routes")
        .insert(route_payloads)
        .select("id,nomor_rute")
        .execute()
    )
    route_id_map = {int(row["nomor_rute"]): int(row["id"]) for row in (route_insert.data or [])}
    if len(route_id_map) != len(route_payloads):
        raise RuntimeError("Detail rute belum tersimpan secara lengkap.")

    stop_payloads = []
    for _, route in assigned_routes.iterrows():
        db_route_id = route_id_map[int(route["route_id"])]
        for sequence, node_index in enumerate(route["node_indices"], start=1):
            customer = active_customers.iloc[int(node_index)]
            stop_payloads.append(
                {
                    "route_id": db_route_id,
                    "urutan": sequence,
                    "store_id": int(customer["store_id"]),
                    "demand": float(customer["demand"]),
                }
            )

    for start in range(0, len(stop_payloads), 250):
        client.table("route_stops").insert(stop_payloads[start:start+250]).execute()

    return rec_id


def load_saved_bundle(client: Client, recommendation: dict) -> dict:
    rec_id = int(recommendation["id"])
    routes_response = (
        client.table("routes")
        .select("*")
        .eq("recommendation_id", rec_id)
        .order("nomor_rute")
        .execute()
    )
    routes = pd.DataFrame(routes_response.data or [])

    stops = pd.DataFrame()
    if not routes.empty:
        route_ids = routes["id"].astype(int).tolist()
        stops_response = (
            client.table("route_stops")
            .select("id,route_id,urutan,store_id,demand")
            .in_("route_id", route_ids)
            .order("urutan")
            .execute()
        )
        stops = pd.DataFrame(stops_response.data or [])

    stores = get_stores_df(client)
    vehicles = get_vehicles_df(client)
    depot, _ = split_depot_and_customers(stores)

    if routes.empty or stops.empty:
        return {
            "routes": routes,
            "stops": stops,
            "stores": stores,
            "vehicles": vehicles,
            "depot": depot,
            "active_customers": pd.DataFrame(),
            "assigned_routes": pd.DataFrame(),
        }

    stops = stops.merge(
        stores[["id","id_toko","nama_toko","alamat","longitude","latitude","zona"]].rename(columns={"id":"store_id"}),
        on="store_id",
        how="left",
    )
    stops["demand"] = pd.to_numeric(stops["demand"], errors="coerce")

    unique_stops = (
        stops.sort_values(["route_id","urutan"])
        .drop_duplicates(subset=["store_id"], keep="first")
        .reset_index(drop=True)
    )
    active_customers = unique_stops[
        ["store_id","id_toko","nama_toko","alamat","longitude","latitude","zona","demand"]
    ].copy()
    active_customers["cluster"] = active_customers["zona"].astype(int)
    index_by_store = {int(row["store_id"]): idx for idx, row in active_customers.iterrows()}

    vehicle_lookup = vehicles.set_index("id").to_dict("index") if not vehicles.empty else {}
    assigned_rows = []
    for _, route in routes.iterrows():
        route_stops = stops[stops["route_id"].astype(int) == int(route["id"])].sort_values("urutan")
        vehicle = vehicle_lookup.get(int(route["vehicle_id"]), {})
        node_indices = [index_by_store[int(store_id)] for store_id in route_stops["store_id"].tolist()]
        assigned_rows.append(
            {
                "route_id": int(route["nomor_rute"]),
                "cluster": int(route["zona"]),
                "node_indices": node_indices,
                "jumlah_toko": int(route["jumlah_toko"]),
                "total_demand": float(route["total_demand"]),
                "total_jarak_km": float(route["total_jarak_km"]),
                "vehicle_id": int(route["vehicle_id"]),
                "kode_mobil": vehicle.get("kode_mobil", "-"),
                "no_mobil": vehicle.get("no_mobil", "-"),
                "supir": vehicle.get("supir", "-"),
                "tipe_mobil": vehicle.get("tipe_mobil", "-"),
                "maks_kapasitas": float(vehicle.get("maks_kapasitas") or 0),
                "utilisasi_persen": float(route["utilisasi_persen"]),
                "status_armada": "Teralokasi",
            }
        )

    return {
        "routes": routes,
        "stops": stops,
        "stores": stores,
        "vehicles": vehicles,
        "depot": depot,
        "active_customers": active_customers,
        "assigned_routes": pd.DataFrame(assigned_rows),
    }


def make_route_table(bundle: dict) -> pd.DataFrame:
    assigned = bundle["assigned_routes"]
    if assigned.empty:
        return pd.DataFrame()
    table = assigned[[
        "route_id","cluster","no_mobil","supir","tipe_mobil","jumlah_toko",
        "total_demand","maks_kapasitas","utilisasi_persen","total_jarak_km"
    ]].copy()
    table.columns = [
        "Rute","Zona","No. Polisi","Driver","Tipe Mobil","Jumlah Toko",
        "Total Demand","Kapasitas","Utilisasi (%)","Jarak (km)"
    ]
    table["Utilisasi (%)"] = table["Utilisasi (%)"].round(2)
    table["Jarak (km)"] = table["Jarak (km)"].round(2)
    return table


def make_excel_result(recommendation: dict, bundle: dict) -> bytes:
    output = io.BytesIO()
    route_table = make_route_table(bundle)
    stops = bundle["stops"].copy()
    if not stops.empty:
        stops = stops[["route_id","urutan","id_toko","nama_toko","alamat","demand"]].copy()
        route_no_map = bundle["routes"].set_index("id")["nomor_rute"].to_dict()
        stops["Rute"] = stops["route_id"].map(route_no_map)
        stops = stops[["Rute","urutan","id_toko","nama_toko","alamat","demand"]]
        stops.columns = ["Rute","Urutan","ID Toko","Nama Toko","Alamat","Demand"]

    summary = pd.DataFrame([
        ["Tanggal", recommendation.get("tanggal")],
        ["Jumlah toko", recommendation.get("jumlah_toko")],
        ["Total demand", recommendation.get("total_demand")],
        ["Armada tersedia", recommendation.get("armada_tersedia")],
        ["Armada digunakan", recommendation.get("armada_digunakan")],
        ["Jumlah rute", recommendation.get("jumlah_rute")],
        ["Jarak sebelum optimasi (km)", recommendation.get("jarak_sebelum_km")],
        ["Jarak rekomendasi (km)", recommendation.get("jarak_rekomendasi_km")],
        ["Reduksi jarak (%)", recommendation.get("reduksi_jarak_persen")],
        ["Rata-rata utilisasi (%)", recommendation.get("rata_utilisasi_persen")],
        ["Status", recommendation.get("status")],
    ], columns=["Keterangan","Nilai"])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Ringkasan", index=False)
        route_table.to_excel(writer, sheet_name="Rute", index=False)
        if not stops.empty:
            stops.to_excel(writer, sheet_name="Urutan Kunjungan", index=False)
    output.seek(0)
    return output.getvalue()


# ============================================================
# SUPER ADMIN
# ============================================================
def render_super_admin_home(profile: dict) -> None:
    st.subheader("Beranda Super Admin")
    st.write(f"Selamat datang, **{profile.get('nama', 'Super Admin')}**.")
    st.caption("Gunakan menu di sebelah kiri untuk mengelola akun pengguna dan data master sistem.")


def render_user_management(client: Client, current_profile: dict) -> None:
    st.subheader("Data Pengguna")
    profiles = pd.DataFrame(fetch_all(client, "profiles", "id,username,nama,role,vehicle_id,status", "username"))
    vehicles = get_vehicles_df(client)

    if profiles.empty:
        st.info("Belum ada data pengguna.")
    else:
        vehicle_no = vehicles.set_index("id")["no_mobil"].to_dict() if not vehicles.empty else {}
        display = profiles.copy()
        display["Armada"] = display["vehicle_id"].map(vehicle_no).fillna("-")
        display["Status"] = display["status"].map({True:"Aktif", False:"Nonaktif"})
        display["Role"] = display["role"].map({"super_admin":"Super Admin","staff":"Staff Transportasi","driver":"Driver"}).fillna(display["role"])
        st.dataframe(
            display[["username","nama","Role","Armada","Status"]].rename(columns={"username":"Username","nama":"Nama"}),
            use_container_width=True,
            hide_index=True,
        )

    tab_add, tab_edit, tab_password = st.tabs(["Tambah Pengguna", "Edit Pengguna", "Reset Password"])

    with tab_add:
        try:
            admin_client = make_admin_client()
        except Exception as exc:
            st.error(str(exc))
            admin_client = None

        role_label = st.selectbox("Role akun baru", ["Staff Transportasi", "Driver"], key="new_user_role")
        role = "staff" if role_label == "Staff Transportasi" else "driver"

        assigned_vehicle_ids = set(
            pd.to_numeric(profiles.get("vehicle_id", pd.Series(dtype=float)), errors="coerce").dropna().astype(int).tolist()
        ) if not profiles.empty else set()
        available_for_account = vehicles[
            (~vehicles["id"].astype(int).isin(assigned_vehicle_ids)) & (vehicles["status"] == True)
        ].copy() if not vehicles.empty else pd.DataFrame()

        selected_vehicle_id = None
        vehicle_label = None
        vehicle_options = {}
        if role == "driver":
            if available_for_account.empty:
                st.warning("Tidak ada armada aktif yang belum memiliki akun Driver.")
            else:
                vehicle_options = {
                    f"{row['no_mobil']} — {row['supir']}": int(row["id"])
                    for _, row in available_for_account.iterrows()
                }
                vehicle_label = st.selectbox("Armada / Driver", list(vehicle_options.keys()), key="new_user_vehicle")
                selected_vehicle_id = vehicle_options[vehicle_label]

        with st.form("add_user_form"):
            username = st.text_input("Username baru").strip().lower()
            if role == "driver" and selected_vehicle_id is not None:
                selected_row = available_for_account[available_for_account["id"].astype(int) == selected_vehicle_id].iloc[0]
                nama = str(selected_row["supir"])
                st.text_input("Nama", value=nama, disabled=True)
            elif role == "driver":
                nama = ""
            else:
                nama = st.text_input("Nama").strip()

            password = st.text_input("Password awal", type="password")
            confirm_password = st.text_input("Ulangi password", type="password")
            submitted = st.form_submit_button("Buat Akun", type="primary")

        if submitted:
            if admin_client is None:
                st.error("Secret key belum tersedia.")
            elif not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
                st.error("Username hanya boleh memakai huruf kecil, angka, titik, garis bawah, atau tanda minus (3–40 karakter).")
            elif not nama:
                st.error("Nama pengguna harus diisi.")
            elif role == "driver" and selected_vehicle_id is None:
                st.error("Pilih armada untuk Driver.")
            elif len(password) < 8:
                st.error("Password awal minimal 8 karakter.")
            elif password != confirm_password:
                st.error("Konfirmasi password tidak sama.")
            elif not profiles.empty and username in profiles["username"].astype(str).str.lower().tolist():
                st.error("Username sudah digunakan.")
            else:
                auth_user_id = None
                try:
                    auth_response = admin_client.auth.admin.create_user(
                        {
                            "email": username_to_email(username),
                            "password": password,
                            "email_confirm": True,
                            "user_metadata": {"username": username, "nama": nama},
                        }
                    )
                    auth_user_id = str(auth_response.user.id)
                    client.table("profiles").insert(
                        {
                            "id": auth_user_id,
                            "username": username,
                            "nama": nama,
                            "role": role,
                            "vehicle_id": selected_vehicle_id,
                            "status": True,
                        }
                    ).execute()
                    st.success(f"Akun {username} berhasil dibuat.")
                    st.rerun()
                except Exception as exc:
                    if auth_user_id:
                        try:
                            admin_client.auth.admin.delete_user(auth_user_id)
                        except Exception:
                            pass
                    st.error(f"Akun belum berhasil dibuat: {exc}")

    with tab_edit:
        if profiles.empty:
            st.info("Belum ada pengguna yang dapat diedit.")
        else:
            options = {
                f"{row['username']} — {row['nama']}": str(row["id"])
                for _, row in profiles.iterrows()
            }
            selected_label = st.selectbox("Pilih pengguna", list(options.keys()), key="edit_user_select")
            selected_id = options[selected_label]
            row = profiles[profiles["id"].astype(str) == selected_id].iloc[0]

            with st.form("edit_user_form"):
                st.text_input("Username", value=str(row["username"]), disabled=True)
                st.text_input("Role", value=str(row["role"]), disabled=True)
                nama_edit = st.text_input("Nama", value=str(row["nama"] or ""))
                status_edit = st.toggle("Akun aktif", value=bool(row["status"]))

                vehicle_id_edit = None
                if row["role"] == "driver":
                    current_vehicle = int(row["vehicle_id"]) if pd.notna(row["vehicle_id"]) else None
                    used_by_others = set(
                        pd.to_numeric(
                            profiles.loc[profiles["id"].astype(str) != selected_id, "vehicle_id"],
                            errors="coerce",
                        ).dropna().astype(int).tolist()
                    )
                    choices = vehicles[~vehicles["id"].astype(int).isin(used_by_others)].copy()
                    labels = {
                        f"{v['no_mobil']} — {v['supir']}": int(v["id"])
                        for _, v in choices.iterrows()
                    }
                    if labels:
                        current_label = next((k for k,v in labels.items() if v == current_vehicle), list(labels.keys())[0])
                        selected_vehicle_label = st.selectbox(
                            "Armada",
                            list(labels.keys()),
                            index=list(labels.keys()).index(current_label),
                        )
                        vehicle_id_edit = labels[selected_vehicle_label]
                submitted_edit = st.form_submit_button("Simpan Perubahan", type="primary")

            if submitted_edit:
                if selected_id == str(current_profile.get("id")) and not status_edit:
                    st.error("Akun Super Admin yang sedang digunakan tidak dapat dinonaktifkan.")
                else:
                    payload = {"nama": nama_edit.strip(), "status": bool(status_edit)}
                    if row["role"] == "driver":
                        payload["vehicle_id"] = vehicle_id_edit
                    try:
                        client.table("profiles").update(payload).eq("id", selected_id).execute()
                        st.success("Data pengguna berhasil diperbarui.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Perubahan belum berhasil disimpan: {exc}")

    with tab_password:
        if profiles.empty:
            st.info("Belum ada pengguna.")
        else:
            options = {
                f"{row['username']} — {row['nama']}": str(row["id"])
                for _, row in profiles.iterrows()
            }
            selected_label = st.selectbox("Pilih pengguna", list(options.keys()), key="reset_password_select")
            selected_id = options[selected_label]
            new_password = st.text_input("Password baru", type="password", key="new_password_admin")
            confirm_new = st.text_input("Ulangi password baru", type="password", key="confirm_password_admin")
            if st.button("Reset Password", type="primary"):
                if len(new_password) < 8:
                    st.error("Password minimal 8 karakter.")
                elif new_password != confirm_new:
                    st.error("Konfirmasi password tidak sama.")
                else:
                    try:
                        admin_client = make_admin_client()
                        admin_client.auth.admin.update_user_by_id(selected_id, {"password": new_password})
                        st.success("Password berhasil diperbarui.")
                    except Exception as exc:
                        st.error(f"Password belum berhasil diperbarui: {exc}")


def render_store_management(client: Client) -> None:
    st.subheader("Master Data Toko")
    stores = get_stores_df(client)
    if stores.empty:
        st.warning("Master Toko belum tersedia.")
        return

    depot, customers = split_depot_and_customers(stores)
    active_customers = customers[customers["status"] == True]
    c1, c2, c3 = st.columns(3)
    c1.metric("Master Toko", len(customers))
    c2.metric("Toko Aktif", len(active_customers))
    c3.metric("Zona", int(active_customers["zona"].dropna().nunique()))

    display = stores.copy()
    display["Status"] = display["status"].map({True:"Aktif", False:"Nonaktif"})
    display["zona"] = display["zona"].where(display["zona"].notna(), "-")
    st.dataframe(
        display[["id_toko","nama_toko","alamat","longitude","latitude","zona","Status"]].rename(
            columns={"id_toko":"ID Toko","nama_toko":"Nama Toko","alamat":"Alamat","longitude":"Longitude","latitude":"Latitude","zona":"Zona"}
        ),
        use_container_width=True,
        hide_index=True,
        height=430,
    )

    tab_add, tab_edit, tab_kmeans = st.tabs(["Tambah Toko", "Edit Toko", "Pembagian Wilayah K-Means"])

    with tab_add:
        with st.form("add_store_form"):
            id_toko = st.text_input("ID Toko").strip()
            nama = st.text_input("Nama Toko").strip()
            alamat = st.text_area("Alamat").strip()
            lon = st.number_input("Longitude", format="%.8f")
            lat = st.number_input("Latitude", format="%.8f")
            add_store = st.form_submit_button("Tambah Toko", type="primary")
        if add_store:
            if not id_toko or id_toko == "0" or not nama:
                st.error("ID Toko dan Nama Toko harus diisi. ID 0 khusus depot.")
            else:
                try:
                    client.table("stores").insert({
                        "id_toko": id_toko,
                        "nama_toko": nama,
                        "alamat": alamat,
                        "longitude": float(lon),
                        "latitude": float(lat),
                        "zona": None,
                        "status": True,
                    }).execute()
                    st.success("Toko berhasil ditambahkan. Jalankan pembaruan K-Means untuk menentukan zonanya.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Toko belum berhasil ditambahkan: {exc}")

    with tab_edit:
        options = {f"{row['id_toko']} — {row['nama_toko']}": int(row["id"]) for _, row in stores.iterrows()}
        label = st.selectbox("Pilih toko", list(options.keys()), key="store_edit_select")
        store_id = options[label]
        row = stores[stores["id"].astype(int) == store_id].iloc[0]
        with st.form("edit_store_form"):
            st.text_input("ID Toko", value=str(row["id_toko"]), disabled=True)
            nama = st.text_input("Nama Toko", value=str(row["nama_toko"] or ""))
            alamat = st.text_area("Alamat", value=str(row["alamat"] or ""))
            lon = st.number_input("Longitude", value=float(row["longitude"]), format="%.8f")
            lat = st.number_input("Latitude", value=float(row["latitude"]), format="%.8f")
            status = st.toggle("Aktif", value=bool(row["status"]), disabled=str(row["id_toko"]) == "0")
            save_store = st.form_submit_button("Simpan Perubahan", type="primary")
        if save_store:
            try:
                client.table("stores").update({
                    "nama_toko": nama.strip(),
                    "alamat": alamat.strip(),
                    "longitude": float(lon),
                    "latitude": float(lat),
                    "status": True if str(row["id_toko"]) == "0" else bool(status),
                }).eq("id", store_id).execute()
                st.success("Master Toko berhasil diperbarui. Jika koordinat berubah, jalankan pembaruan K-Means.")
                st.rerun()
            except Exception as exc:
                st.error(f"Perubahan belum berhasil disimpan: {exc}")

    with tab_kmeans:
        st.write("K-Means digunakan untuk memperbarui pembagian **4 zona distribusi** berdasarkan koordinat toko aktif. Depot tidak ikut clustering.")
        if not active_customers.empty:
            zone_counts = active_customers.groupby("zona", dropna=False).size().reset_index(name="Jumlah Toko")
            st.dataframe(zone_counts, use_container_width=True, hide_index=True)
        if st.button("Perbarui Pembagian Wilayah", type="primary"):
            current = get_stores_df(client)
            depot_row, all_customers = split_depot_and_customers(current)
            active = all_customers[all_customers["status"] == True].copy()
            if len(active) < N_CLUSTERS:
                st.error("Jumlah toko aktif belum cukup untuk membentuk 4 zona.")
            elif active[["longitude","latitude"]].isna().any().any():
                st.error("Terdapat koordinat toko aktif yang kosong.")
            else:
                with st.spinner("Memperbarui pembagian wilayah..."):
                    x = active[["longitude","latitude"]].to_numpy(dtype=float)
                    model = KMeans(n_clusters=N_CLUSTERS, random_state=RANDOM_STATE, n_init=10)
                    active["zona_baru"] = model.fit_predict(x) + 1
                    zone_by_id = active.set_index("id")["zona_baru"].to_dict()
                    payloads = []
                    for _, s in current.iterrows():
                        zona = None
                        if str(s["id_toko"]) != "0" and bool(s["status"]):
                            zona = int(zone_by_id[int(s["id"])])
                        payloads.append({
                            "id": int(s["id"]),
                            "id_toko": str(s["id_toko"]),
                            "nama_toko": s["nama_toko"],
                            "alamat": s["alamat"],
                            "longitude": float(s["longitude"]) if pd.notna(s["longitude"]) else None,
                            "latitude": float(s["latitude"]) if pd.notna(s["latitude"]) else None,
                            "zona": zona,
                            "status": bool(s["status"]),
                        })
                    for start in range(0, len(payloads), 100):
                        client.table("stores").upsert(payloads[start:start+100], on_conflict="id").execute()
                st.success("Pembagian wilayah K-Means berhasil diperbarui menjadi 4 zona.")
                st.rerun()


def render_vehicle_management(client: Client) -> None:
    st.subheader("Master Data Armada & Driver")
    vehicles = get_vehicles_df(client)
    profiles = pd.DataFrame(fetch_all(client, "profiles", "id,username,nama,role,vehicle_id,status", "username"))

    account_map = {}
    if not profiles.empty:
        for _, p in profiles[profiles["role"] == "driver"].iterrows():
            if pd.notna(p["vehicle_id"]):
                account_map[int(p["vehicle_id"])] = str(p["username"])

    display = vehicles.copy()
    display["Akun"] = display["id"].astype(int).map(account_map).fillna("Belum memiliki akun")
    display["Status"] = display["status"].map({True:"Aktif", False:"Nonaktif"})
    st.dataframe(
        display[["kode_mobil","no_mobil","supir","tipe_mobil","maks_kapasitas","Akun","Status"]].rename(
            columns={"kode_mobil":"Kode Mobil","no_mobil":"No. Polisi","supir":"Driver","tipe_mobil":"Tipe Mobil","maks_kapasitas":"Kapasitas"}
        ),
        use_container_width=True,
        hide_index=True,
        height=430,
    )

    tab_add, tab_edit = st.tabs(["Tambah Armada", "Edit Armada"])
    with tab_add:
        with st.form("add_vehicle_form"):
            kode = st.text_input("Kode Mobil").strip()
            no_mobil = st.text_input("No. Polisi").strip().upper()
            supir = st.text_input("Nama Driver").strip()
            tipe = st.text_input("Tipe Mobil").strip()
            kapasitas = st.number_input("Maks. Kapasitas", min_value=0.0, step=50.0)
            submit = st.form_submit_button("Tambah Armada", type="primary")
        if submit:
            if not kode or not no_mobil or not supir or not tipe or kapasitas <= 0:
                st.error("Seluruh data armada harus diisi dengan benar.")
            else:
                try:
                    client.table("vehicles").insert({
                        "kode_mobil": kode,
                        "no_mobil": no_mobil,
                        "supir": supir,
                        "tipe_mobil": tipe,
                        "maks_kapasitas": float(kapasitas),
                        "status": True,
                    }).execute()
                    st.success("Armada berhasil ditambahkan.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Armada belum berhasil ditambahkan: {exc}")

    with tab_edit:
        if vehicles.empty:
            st.info("Belum ada armada.")
        else:
            options = {f"{v['no_mobil']} — {v['supir']}": int(v["id"]) for _, v in vehicles.iterrows()}
            label = st.selectbox("Pilih armada", list(options.keys()), key="vehicle_edit_select")
            vehicle_id = options[label]
            row = vehicles[vehicles["id"].astype(int) == vehicle_id].iloc[0]
            with st.form("edit_vehicle_form"):
                st.text_input("Kode Mobil", value=str(row["kode_mobil"]), disabled=True)
                no_mobil = st.text_input("No. Polisi", value=str(row["no_mobil"])).strip().upper()
                supir = st.text_input("Nama Driver", value=str(row["supir"])).strip()
                tipe = st.text_input("Tipe Mobil", value=str(row["tipe_mobil"])).strip()
                kapasitas = st.number_input("Maks. Kapasitas", value=float(row["maks_kapasitas"]), min_value=0.0, step=50.0)
                status = st.toggle("Armada aktif", value=bool(row["status"]))
                submit = st.form_submit_button("Simpan Perubahan", type="primary")
            if submit:
                try:
                    client.table("vehicles").update({
                        "no_mobil": no_mobil,
                        "supir": supir,
                        "tipe_mobil": tipe,
                        "maks_kapasitas": float(kapasitas),
                        "status": bool(status),
                    }).eq("id", vehicle_id).execute()
                    linked = profiles[
                        (profiles["role"] == "driver") &
                        (pd.to_numeric(profiles["vehicle_id"], errors="coerce") == vehicle_id)
                    ] if not profiles.empty else pd.DataFrame()
                    if not linked.empty:
                        client.table("profiles").update({"nama": supir}).eq("id", str(linked.iloc[0]["id"])).execute()
                    st.success("Master Armada berhasil diperbarui.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Perubahan belum berhasil disimpan: {exc}")


# ============================================================
# STAFF TRANSPORTASI
# ============================================================
def get_daily_orders_df(client: Client) -> pd.DataFrame:
    # Hanya ambil kolom inti yang benar-benar digunakan oleh aplikasi.
    # created_at bersifat opsional dan tidak diperlukan untuk proses rekomendasi.
    rows = fetch_all(client, "daily_orders", "id,tanggal,store_id,demand", "tanggal")
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["id","tanggal","store_id","demand"])
    df["tanggal"] = pd.to_datetime(df["tanggal"], errors="coerce").dt.date
    df["store_id"] = pd.to_numeric(df["store_id"], errors="coerce").astype("Int64")
    df["demand"] = pd.to_numeric(df["demand"], errors="coerce")
    return df


def render_staff_dashboard(client: Client) -> None:
    st.subheader("Dashboard")
    stores = get_stores_df(client)
    vehicles = get_vehicles_df(client)
    orders = get_daily_orders_df(client)
    depot, customers = split_depot_and_customers(stores)
    active_stores = customers[customers["status"] == True].copy()
    active_vehicles = vehicles[vehicles["status"] == True].copy()
    today = today_jakarta()
    today_orders = orders[orders["tanggal"] == today] if not orders.empty else pd.DataFrame()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Master Toko", len(active_stores))
    c2.metric("Armada Aktif", len(active_vehicles))
    c3.metric("Driver", len(active_vehicles))
    c4.metric("Pesanan Hari Ini", int(today_orders["store_id"].nunique()) if not today_orders.empty else 0)

    st.markdown("### Peta Wilayah Distribusi")
    try:
        depot_map, zone_customers = prepare_zone_map_data(stores)
        if zone_customers.empty:
            st.info("Zona toko belum tersedia.")
        else:
            st_folium(plot_zone_map(zone_customers, depot_map), width=1100, height=520)
    except Exception as exc:
        st.warning(str(exc))

    st.markdown("### Distribusi Hari Ini")
    rec = get_recommendation_for_date(client, today)
    if today_orders.empty:
        st.info("Belum ada data penjualan hari ini. Buka menu **Data Penjualan** untuk mengunggah data.")
    elif rec and rec.get("status") == "ditetapkan":
        st.success(
            f"Rute hari ini sudah ditetapkan: {rec.get('jumlah_toko',0)} toko, "
            f"{rec.get('jumlah_rute',0)} rute, {rec.get('armada_digunakan',0)} armada."
        )
    elif rec:
        st.warning("Rekomendasi hari ini sudah tersedia tetapi belum ditetapkan.")
    else:
        st.success(f"{today_orders['store_id'].nunique()} toko memiliki pesanan dan siap diproses.")
        st.caption("Buka menu **Proses Rekomendasi** untuk menghasilkan rekomendasi rute.")


def validate_daily_order_upload(uploaded_file, stores: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    errors: list[str] = []
    try:
        df = read_excel(uploaded_file)
    except Exception as exc:
        return None, [f"File Excel tidak dapat dibaca: {exc}"]

    if "demand" not in df.columns:
        alias = next((c for c in DAILY_DEMAND_ALIASES if c in df.columns), None)
        if alias:
            df = df.rename(columns={alias: "demand"})

    missing = [c for c in REQUIRED_DAILY_ORDER_COLUMNS if c not in df.columns]
    if missing:
        return None, [f"Kolom wajib tidak ditemukan: {', '.join(missing)}"]

    df = df[REQUIRED_DAILY_ORDER_COLUMNS].copy()
    df["id_toko"] = df["id_toko"].apply(normalize_store_id)
    df["nama_toko"] = df["nama_toko"].astype(str).str.strip()
    df["demand"] = pd.to_numeric(df["demand"], errors="coerce")

    if df["id_toko"].eq("").any():
        errors.append("Terdapat ID toko kosong.")
    if (df["id_toko"] == "0").any():
        errors.append("Depot (id_toko = 0) tidak boleh terdapat pada data penjualan.")
    if df["id_toko"].duplicated().any():
        dup = df.loc[df["id_toko"].duplicated(keep=False), "id_toko"].unique().tolist()
        errors.append(f"ID toko duplikat ditemukan: {', '.join(map(str, dup[:10]))}")
    if df["demand"].isna().any() or (df["demand"] <= 0).any():
        errors.append("Demand harus berupa angka dan lebih dari 0.")

    master = stores[(stores["id_toko"] != "0") & (stores["status"] == True)].copy()
    master_lookup = {str(r["id_toko"]): r for _, r in master.iterrows()}
    unknown = sorted([store_id for store_id in df["id_toko"].tolist() if store_id not in master_lookup])
    if unknown:
        errors.append(f"ID toko tidak ditemukan/aktif pada Master Toko: {', '.join(unknown[:10])}")

    mismatches = []
    for _, row in df.iterrows():
        master_row = master_lookup.get(row["id_toko"])
        if master_row is not None and normalize_text(row["nama_toko"]) != normalize_text(master_row["nama_toko"]):
            mismatches.append(f"{row['id_toko']} ({row['nama_toko']} ≠ {master_row['nama_toko']})")
    if mismatches:
        errors.append("Nama toko tidak sesuai Master Toko: " + "; ".join(mismatches[:8]))

    if errors:
        return None, errors

    master_for_merge = master[["id","id_toko","nama_toko","alamat","zona"]].rename(columns={"id":"store_id","nama_toko":"nama_master"})
    df = df.merge(master_for_merge, on="id_toko", how="left", validate="one_to_one")
    df["nama_toko"] = df["nama_master"]
    return df[["store_id","id_toko","nama_toko","alamat","zona","demand"]].copy(), []


def render_daily_orders(client: Client) -> None:
    st.subheader("Data Penjualan Harian")
    stores = get_stores_df(client)
    selected_date = st.date_input("Tanggal Data Penjualan", value=today_jakarta())
    locked, reason = date_is_locked(client, selected_date)
    if locked:
        st.warning(reason)

    uploaded = st.file_uploader("Upload Data Penjualan (.xlsx)", type=["xlsx"], key="daily_order_upload")
    preview = None
    errors = []
    if uploaded is not None:
        preview, errors = validate_daily_order_upload(uploaded, stores)
        if errors:
            for err in errors:
                st.error(err)
        elif preview is not None:
            c1, c2 = st.columns(2)
            c1.metric("Toko Valid", len(preview))
            c2.metric("Total Demand", format_qty(float(preview["demand"].sum())))
            st.dataframe(preview[["id_toko","nama_toko","demand"]], use_container_width=True, hide_index=True)

            if st.button("Simpan Data Penjualan", type="primary", disabled=locked):
                try:
                    # Perubahan data input membatalkan rekomendasi sementara pada tanggal yang sama.
                    delete_unfinalized_recommendation(client, selected_date)
                    client.table("daily_orders").delete().eq("tanggal", selected_date.isoformat()).execute()
                    payloads = [
                        {
                            "tanggal": selected_date.isoformat(),
                            "store_id": int(row["store_id"]),
                            "demand": float(row["demand"]),
                        }
                        for _, row in preview.iterrows()
                    ]
                    for start in range(0, len(payloads), 250):
                        client.table("daily_orders").insert(payloads[start:start+250]).execute()
                    st.success(f"Data penjualan {selected_date.strftime('%d-%m-%Y')} berhasil disimpan.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Data belum berhasil disimpan: {exc}")

    st.divider()
    st.markdown("### Riwayat Data Penjualan")
    orders = get_daily_orders_df(client)
    if orders.empty:
        st.info("Belum ada data penjualan yang tersimpan.")
    else:
        recs = pd.DataFrame(fetch_all(client, "recommendations", "id,tanggal,status", "tanggal"))
        summary = orders.groupby("tanggal").agg(Jumlah_Toko=("store_id","nunique"), Total_Demand=("demand","sum")).reset_index()
        status_map = {}
        if not recs.empty:
            status_map = {pd.to_datetime(r["tanggal"]).date(): r["status"] for _, r in recs.iterrows()}
        summary["Status"] = summary["tanggal"].apply(
            lambda d: "Ditetapkan" if status_map.get(d) == "ditetapkan" else ("Rekomendasi" if status_map.get(d) else "Tersimpan")
        )
        summary = summary.sort_values("tanggal", ascending=False)
        summary["Tanggal"] = summary["tanggal"].apply(lambda d: d.strftime("%d-%m-%Y"))
        summary["Total Demand"] = summary["Total_Demand"].round(2)
        st.dataframe(summary[["Tanggal","Jumlah_Toko","Total Demand","Status"]].rename(columns={"Jumlah_Toko":"Jumlah Toko"}), use_container_width=True, hide_index=True)


def render_process_recommendation(client: Client) -> None:
    st.subheader("Proses Rekomendasi")
    orders = get_daily_orders_df(client)
    if orders.empty:
        st.info("Belum ada data penjualan yang dapat diproses.")
        return

    dates = sorted(orders["tanggal"].dropna().unique().tolist(), reverse=True)
    editable_dates = [d for d in dates if d >= today_jakarta()]
    if not editable_dates:
        st.info("Tidak ada data penjualan hari ini atau tanggal mendatang yang dapat diproses.")
        return

    selected_date = st.selectbox(
        "Pilih Data Penjualan",
        editable_dates,
        format_func=lambda d: d.strftime("%d-%m-%Y"),
    )
    rec = get_recommendation_for_date(client, selected_date)
    if rec and rec.get("status") == "ditetapkan":
        st.success("Rute tanggal tersebut sudah ditetapkan.")
        return

    stores = get_stores_df(client)
    vehicles = get_vehicles_df(client)
    selected_orders = orders[orders["tanggal"] == selected_date][["store_id","demand"]].copy()
    try:
        depot, active_customers = build_active_customers_from_orders(selected_orders, stores)
    except Exception as exc:
        st.error(str(exc))
        return

    active_vehicles = vehicles[vehicles["status"] == True].copy().reset_index(drop=True)
    if active_vehicles.empty:
        st.error("Tidak ada armada aktif pada Master Armada.")
        return

    vehicle_labels = {
        f"{row['no_mobil']} — {row['supir']} ({format_qty(row['maks_kapasitas'])})": int(row["id"])
        for _, row in active_vehicles.iterrows()
    }
    unavailable_labels = st.multiselect(
        "Armada tidak tersedia hari ini (opsional)",
        list(vehicle_labels.keys()),
        help="Gunakan pilihan ini jika ada armada aktif pada master yang tidak beroperasi pada tanggal distribusi.",
    )
    unavailable_ids = {vehicle_labels[label] for label in unavailable_labels}
    available = active_vehicles[~active_vehicles["id"].astype(int).isin(unavailable_ids)].copy().reset_index(drop=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toko dengan Pesanan", len(active_customers))
    c2.metric("Total Demand", format_qty(float(active_customers["demand"].sum())))
    c3.metric("Zona Aktif", int(active_customers["cluster"].nunique()))
    c4.metric("Armada Tersedia", len(available))

    st.markdown("### Toko Aktif pada Tanggal Distribusi")
    st_folium(plot_zone_map(active_customers, depot), width=1100, height=480)

    if st.button("Proses Rekomendasi Distribusi", type="primary", use_container_width=True, disabled=available.empty):
        with st.spinner("Sistem sedang menyusun rekomendasi rute..."):
            try:
                start_time = time.perf_counter()
                total_distance_before = float(
                    sum(2 * distance_depot_to_customer(depot, row) for _, row in active_customers.iterrows())
                )
                allocated = allocate_customers_to_fleet(active_customers, available)
                assigned_routes = build_routes_from_allocation(allocated, available, depot)
                total_distance_after = float(assigned_routes["total_jarak_km"].sum()) if not assigned_routes.empty else 0.0
                distance_saved = total_distance_before - total_distance_after
                reduction = (distance_saved / total_distance_before * 100) if total_distance_before > 0 else 0.0
                avg_util = float(assigned_routes["utilisasi_persen"].mean()) if not assigned_routes.empty else 0.0
                save_recommendation_to_database(
                    client,
                    selected_date,
                    active_customers,
                    available,
                    assigned_routes,
                    total_distance_before,
                    total_distance_after,
                    reduction,
                    avg_util,
                )
                elapsed = time.perf_counter() - start_time
                st.success(
                    f"Rekomendasi berhasil dibuat: {len(assigned_routes)} rute menggunakan "
                    f"{len(assigned_routes)} armada dalam {elapsed:.2f} detik."
                )
                st.info("Buka menu **Hasil & Penetapan Rute** untuk meninjau dan menetapkan hasil.")
            except Exception as exc:
                st.error(f"Rekomendasi belum berhasil dibentuk: {exc}")


def render_recommendation_content(client: Client, recommendation: dict, allow_finalize: bool = True) -> None:
    bundle = load_saved_bundle(client, recommendation)
    assigned = bundle["assigned_routes"]
    stops = bundle["stops"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Toko Dilayani", int(recommendation.get("jumlah_toko") or 0))
    c2.metric("Rute", int(recommendation.get("jumlah_rute") or 0))
    c3.metric("Armada Digunakan", int(recommendation.get("armada_digunakan") or 0))
    c4.metric("Total Jarak", f"{format_distance_km(recommendation.get('jarak_rekomendasi_km') or 0)} km")
    c5.metric("Reduksi Jarak", f"{float(recommendation.get('reduksi_jarak_persen') or 0):.2f}%")

    st.info(
        f"Sistem merekomendasikan penggunaan **{int(recommendation.get('armada_digunakan') or 0)} armada** "
        f"untuk melayani **{int(recommendation.get('jumlah_toko') or 0)} toko** pada tanggal "
        f"**{pd.to_datetime(recommendation['tanggal']).strftime('%d-%m-%Y')}**."
    )

    tab_summary, tab_routes, tab_map = st.tabs(["Ringkasan", "Daftar Rute", "Visualisasi Peta"])
    with tab_summary:
        summary = pd.DataFrame([
            ["Tanggal Distribusi", pd.to_datetime(recommendation["tanggal"]).strftime("%d-%m-%Y")],
            ["Jumlah toko aktif", int(recommendation.get("jumlah_toko") or 0)],
            ["Total demand", format_qty(float(recommendation.get("total_demand") or 0))],
            ["Armada tersedia", int(recommendation.get("armada_tersedia") or 0)],
            ["Armada direkomendasikan", int(recommendation.get("armada_digunakan") or 0)],
            ["Armada tidak digunakan", int(recommendation.get("armada_tersedia") or 0) - int(recommendation.get("armada_digunakan") or 0)],
            ["Jumlah rute", int(recommendation.get("jumlah_rute") or 0)],
            ["Jarak sebelum optimasi", f"{format_distance_km(recommendation.get('jarak_sebelum_km') or 0)} km"],
            ["Jarak rekomendasi", f"{format_distance_km(recommendation.get('jarak_rekomendasi_km') or 0)} km"],
            ["Reduksi jarak", f"{float(recommendation.get('reduksi_jarak_persen') or 0):.2f}%"],
            ["Rata-rata utilisasi", f"{float(recommendation.get('rata_utilisasi_persen') or 0):.2f}%"],
            ["Status", "Ditetapkan" if recommendation.get("status") == "ditetapkan" else "Belum Ditetapkan"],
        ], columns=["Keterangan","Nilai"])
        st.dataframe(summary, use_container_width=True, hide_index=True)
        st.caption("Jarak sebelum optimasi digunakan sebagai skenario pembanding ketika setiap toko dilayani melalui perjalanan depot–toko–depot secara terpisah.")

    with tab_routes:
        route_table = make_route_table(bundle)
        if route_table.empty:
            st.warning("Detail rute belum tersedia.")
        else:
            st.dataframe(route_table, use_container_width=True, hide_index=True)
            route_options = {f"R{int(r['route_id']):02d} — {r['no_mobil']} — {r['supir']}": int(r["route_id"]) for _, r in assigned.iterrows()}
            selected = st.selectbox("Detail rute", list(route_options.keys()))
            route_no = route_options[selected]
            route_row = assigned[assigned["route_id"].astype(int) == route_no].iloc[0]
            db_route_row = bundle["routes"][bundle["routes"]["nomor_rute"].astype(int) == route_no].iloc[0]
            detail_stops = stops[stops["route_id"].astype(int) == int(db_route_row["id"])].sort_values("urutan").copy()

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("No. Polisi", str(route_row["no_mobil"]))
            d2.metric("Driver", str(route_row["supir"]))
            d3.metric("Zona", int(route_row["cluster"]))
            d4.metric("Jarak", f"{format_distance_km(route_row['total_jarak_km'])} km")
            detail_display = detail_stops[["urutan","nama_toko","alamat","demand"]].copy()
            detail_display.columns = ["Urutan","Nama Toko","Alamat","Demand"]
            st.dataframe(detail_display, use_container_width=True, hide_index=True)
            sequence = " → ".join(["Depot"] + detail_stops["nama_toko"].astype(str).tolist() + ["Depot"])
            st.write("**Urutan kunjungan:**")
            st.write(sequence)

    with tab_map:
        if assigned.empty or bundle["active_customers"].empty:
            st.warning("Visualisasi rute belum tersedia.")
        else:
            st.caption("Klik salah satu jalur untuk menonjolkannya. Klik area kosong untuk menampilkan semua jalur kembali.")
            st_folium(
                plot_after_optimization_map(assigned, bundle["active_customers"], bundle["depot"]),
                width=1100,
                height=560,
            )

    if not assigned.empty:
        excel = make_excel_result(recommendation, bundle)
        st.download_button(
            "Download Hasil (.xlsx)",
            data=excel,
            file_name=f"hasil_rute_{recommendation['tanggal']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    rec_date = pd.to_datetime(recommendation["tanggal"]).date()
    if allow_finalize:
        if recommendation.get("status") == "ditetapkan":
            st.success("Status: Rute Distribusi Ditetapkan")
        elif rec_date < today_jakarta():
            st.warning("Status: Terkunci karena tanggal distribusi sudah lewat. Rute belum pernah ditetapkan.")
        else:
            st.warning("Status: Rekomendasi Belum Ditetapkan")
            if st.button("Tetapkan Rute Distribusi", type="primary", use_container_width=True):
                try:
                    client.table("recommendations").update({"status":"ditetapkan"}).eq("id", int(recommendation["id"])).execute()
                    st.success("Rute distribusi telah ditetapkan dan sekarang dapat dilihat oleh Driver terkait.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Rute belum berhasil ditetapkan: {exc}")


def render_staff_results(client: Client) -> None:
    st.subheader("Hasil & Penetapan Rute")
    recs = pd.DataFrame(fetch_all(client, "recommendations", "*", "tanggal"))
    if recs.empty:
        st.info("Belum ada hasil rekomendasi.")
        return
    recs["tanggal_date"] = pd.to_datetime(recs["tanggal"]).dt.date
    recs = recs.sort_values("tanggal_date", ascending=False)
    options = {d.strftime("%d-%m-%Y"): d for d in recs["tanggal_date"].tolist()}
    label = st.selectbox("Tanggal rekomendasi", list(options.keys()))
    selected_date = options[label]
    rec = recs[recs["tanggal_date"] == selected_date].iloc[0].to_dict()
    render_recommendation_content(client, rec, allow_finalize=True)


def render_staff_history(client: Client) -> None:
    st.subheader("Riwayat Distribusi")
    recs = pd.DataFrame(fetch_all(client, "recommendations", "*", "tanggal"))
    if recs.empty:
        st.info("Belum ada riwayat distribusi.")
        return
    recs["Tanggal"] = pd.to_datetime(recs["tanggal"]).dt.strftime("%d-%m-%Y")
    recs["Status"] = recs.apply(
        lambda r: "Ditetapkan" if r["status"] == "ditetapkan" else ("Terkunci" if pd.to_datetime(r["tanggal"]).date() < today_jakarta() else "Belum Ditetapkan"),
        axis=1,
    )
    display = recs[["Tanggal","jumlah_toko","armada_digunakan","jumlah_rute","jarak_rekomendasi_km","reduksi_jarak_persen","Status"]].copy()
    display.columns = ["Tanggal","Toko","Armada","Rute","Jarak (km)","Reduksi Jarak (%)","Status"]
    display = display.sort_values("Tanggal", ascending=False)
    st.dataframe(display, use_container_width=True, hide_index=True)

    date_options = sorted(pd.to_datetime(recs["tanggal"]).dt.date.tolist(), reverse=True)
    selected_date = st.selectbox("Lihat detail riwayat", date_options, format_func=lambda d: d.strftime("%d-%m-%Y"))
    rec = recs[pd.to_datetime(recs["tanggal"]).dt.date == selected_date].iloc[0].to_dict()
    render_recommendation_content(client, rec, allow_finalize=False)


# ============================================================
# DRIVER
# ============================================================
def render_driver_route(client: Client, recommendation: dict, profile: dict) -> None:
    bundle = load_saved_bundle(client, recommendation)
    assigned = bundle["assigned_routes"]
    if assigned.empty:
        st.info("Tidak ada rute yang ditugaskan pada armada Anda.")
        return

    # RLS memastikan Driver hanya memperoleh rute milik armadanya.
    route = assigned.iloc[0]
    db_route = bundle["routes"].iloc[0]
    stops = bundle["stops"][bundle["stops"]["route_id"].astype(int) == int(db_route["id"])].sort_values("urutan").copy()

    st.subheader("Tugas Distribusi")
    st.write(f"**Tanggal:** {pd.to_datetime(recommendation['tanggal']).strftime('%d-%m-%Y')}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Driver", str(route["supir"]))
    c2.metric("No. Polisi", str(route["no_mobil"]))
    c3.metric("Zona", int(route["cluster"]))

    c4, c5, c6, c7 = st.columns(4)
    c4.metric("Jumlah Toko", int(route["jumlah_toko"]))
    c5.metric("Total Demand", format_qty(route["total_demand"]))
    c6.metric("Utilisasi", f"{float(route['utilisasi_persen']):.2f}%")
    c7.metric("Total Jarak", f"{format_distance_km(route['total_jarak_km'])} km")

    st.markdown("### Urutan Kunjungan")
    display = stops[["urutan","nama_toko","alamat","demand"]].copy()
    display.columns = ["Urutan","Nama Toko","Alamat","Demand"]
    st.dataframe(display, use_container_width=True, hide_index=True)
    sequence = " → ".join(["Depot"] + stops["nama_toko"].astype(str).tolist() + ["Depot"])
    st.write(sequence)

    st.markdown("### Visualisasi Peta")
    st_folium(
        plot_after_optimization_map(assigned, bundle["active_customers"], bundle["depot"]),
        width=1100,
        height=560,
    )


def render_driver_today(client: Client, profile: dict) -> None:
    st.subheader("Rute Hari Ini")
    today = today_jakarta()
    response = (
        client.table("recommendations")
        .select("*")
        .eq("tanggal", today.isoformat())
        .execute()
    )
    data = response.data or []
    if not data:
        st.info("Belum ada rute distribusi yang ditetapkan untuk hari ini.")
        return
    render_driver_route(client, data[0], profile)


def render_driver_history(client: Client, profile: dict) -> None:
    st.subheader("Riwayat Rute")
    recs = pd.DataFrame(fetch_all(client, "recommendations", "*", "tanggal"))
    if recs.empty:
        st.info("Belum ada riwayat rute yang ditetapkan untuk Anda.")
        return
    recs["tanggal_date"] = pd.to_datetime(recs["tanggal"]).dt.date
    recs = recs.sort_values("tanggal_date", ascending=False)
    options = {d.strftime("%d-%m-%Y"): d for d in recs["tanggal_date"].tolist()}
    label = st.selectbox("Pilih tanggal", list(options.keys()))
    selected = options[label]
    rec = recs[recs["tanggal_date"] == selected].iloc[0].to_dict()
    render_driver_route(client, rec, profile)


# ============================================================
# NAVIGASI BERDASARKAN ROLE
# ============================================================
def render_sidebar_and_get_menu(client: Client, profile: dict) -> str:
    role = profile.get("role")
    role_label = {
        "super_admin": "Super Admin",
        "staff": "Staff Transportasi",
        "driver": "Driver",
    }.get(role, role)

    with st.sidebar:
        if LOGO_PATH.exists():
            try:
                st.image(str(LOGO_PATH), width=65)
            except Exception:
                pass
        st.markdown(f"### {html.escape(str(profile.get('nama') or '-'))}")
        st.caption(role_label)

        if role == "driver" and profile.get("vehicle_id") is not None:
            try:
                vehicle = (
                    client.table("vehicles")
                    .select("no_mobil")
                    .eq("id", int(profile["vehicle_id"]))
                    .single()
                    .execute()
                ).data
                if vehicle:
                    st.caption(f"🚚 {vehicle.get('no_mobil','-')}")
            except Exception:
                pass

        st.divider()
        if role == "super_admin":
            menu = st.radio(
                "Menu",
                ["Beranda", "Data Pengguna", "Data Toko", "Data Armada & Driver"],
                key="menu_super_admin",
                label_visibility="collapsed",
            )
        elif role == "staff":
            menu = st.radio(
                "Menu",
                ["Dashboard", "Data Penjualan", "Proses Rekomendasi", "Hasil & Penetapan Rute", "Riwayat Distribusi"],
                key="menu_staff",
                label_visibility="collapsed",
            )
        else:
            menu = st.radio(
                "Menu",
                ["Rute Hari Ini", "Riwayat Rute"],
                key="menu_driver",
                label_visibility="collapsed",
            )

        st.divider()
        if st.button("Keluar", type="primary", use_container_width=True):
            perform_logout(client)
    return menu


def main() -> None:
    client = make_user_client()
    authenticated = bool(st.session_state.get("authenticated"))
    if authenticated:
        authenticated = restore_session(client)

    if not authenticated:
        render_login(client)
        st.stop()

    profile = load_current_profile(client)
    if not profile or not bool(profile.get("status", False)):
        perform_logout(client)
        st.stop()
    st.session_state.profile = profile

    role_label = {
        "super_admin": "Super Admin",
        "staff": "Staff Transportasi",
        "driver": "Driver",
    }.get(profile.get("role"), str(profile.get("role")))
    render_app_header(role_label)
    menu = render_sidebar_and_get_menu(client, profile)

    role = profile.get("role")
    if role == "super_admin":
        if menu == "Beranda":
            render_super_admin_home(profile)
        elif menu == "Data Pengguna":
            render_user_management(client, profile)
        elif menu == "Data Toko":
            render_store_management(client)
        elif menu == "Data Armada & Driver":
            render_vehicle_management(client)
    elif role == "staff":
        if menu == "Dashboard":
            render_staff_dashboard(client)
        elif menu == "Data Penjualan":
            render_daily_orders(client)
        elif menu == "Proses Rekomendasi":
            render_process_recommendation(client)
        elif menu == "Hasil & Penetapan Rute":
            render_staff_results(client)
        elif menu == "Riwayat Distribusi":
            render_staff_history(client)
    elif role == "driver":
        if menu == "Rute Hari Ini":
            render_driver_today(client, profile)
        elif menu == "Riwayat Rute":
            render_driver_history(client, profile)
    else:
        st.error("Role pengguna tidak dikenali.")


if __name__ == "__main__":
    main()
