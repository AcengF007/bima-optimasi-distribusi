import base64
import hashlib
import hmac
import html
import math
import time
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

import folium
import numpy as np
import pandas as pd
import streamlit as st
from branca.element import MacroElement, Template
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from PIL import Image
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from sklearn.cluster import KMeans
from streamlit_folium import st_folium


# VERSI FINAL: basis V8 + interaksi jalur Hasil Optimasi dari V6

# ============================================================
# KONFIGURASI HALAMAN DAN LOGO
# Letakkan file logo.jpg di folder yang sama dengan file aplikasi.
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "logo.jpg"

# Kredensial login aplikasi. Password disimpan sebagai hash agar tidak ditulis
# dalam bentuk teks biasa pada source code.
APP_USERNAME = "bks_transportasi"
APP_PASSWORD_SHA256 = "0b0e2f524b5ea95db979da4960653a94eebe105c99a7b0e9ae514a4022cc6129"

try:
    PAGE_ICON = Image.open(LOGO_PATH) if LOGO_PATH.exists() else "📦"
except OSError:
    PAGE_ICON = "📦"

st.set_page_config(
    page_title="Optimasi Distribusi PT BIMA",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


def image_to_data_uri(image_path: Path) -> str:
    """Mengubah logo lokal menjadi data URI agar dapat dipakai pada header HTML."""
    suffix = image_path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_image}"


st.markdown(
    """
    <style>
        .bima-header {
            display: flex;
            align-items: center;
            gap: 20px;
            margin: 0 0 1rem 0;
            width: 100%;
        }

        .bima-header-logo {
            width: 78px;
            height: auto;
            object-fit: contain;
            flex: 0 0 auto;
        }

        .bima-header-title {
            margin: 0;
            font-size: clamp(2rem, 3.2vw, 3rem);
            line-height: 1.16;
            font-weight: 700;
            color: var(--text-color, #1f2937);
            letter-spacing: -0.02em;
        }

        /* Sidebar dibuat lebih ringkas agar seluruh kontrol utama dapat terlihat
           tanpa perlu scroll pada tinggi layar desktop yang umum. */
        section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
            padding-top: 0.75rem;
            padding-bottom: 0.45rem;
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.5rem;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploader"] {
            margin-bottom: -0.1rem;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
            min-height: 3.15rem;
            padding: 0.35rem 0.55rem;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] small {
            display: none;
        }

        section[data-testid="stSidebar"] hr {
            margin: 0.2rem 0 0.25rem 0;
        }

        section[data-testid="stSidebar"] .stNumberInput,
        section[data-testid="stSidebar"] .stRadio {
            margin-bottom: 0;
        }

        .bima-login-logo-wrap {
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 0.7rem;
        }

        .bima-login-logo {
            width: 92px;
            height: auto;
            display: block;
        }

        .bima-login-title {
            text-align: center;
            margin-bottom: 0.15rem;
            font-size: 2rem;
            line-height: 1.2;
            font-weight: 700;
            color: var(--text-color, #1f2937);
        }

        .bima-login-subtitle {
            text-align: center;
            opacity: 0.75;
            margin-bottom: 1rem;
        }

        /* Tombol Masuk: hijau. Selector dibuat spesifik agar tidak mengikuti warna tema Streamlit. */
        div[data-testid="stForm"] button,
        div[data-testid="stFormSubmitButton"] button {
            background: #16a34a !important;
            background-color: #16a34a !important;
            border: 1px solid #16a34a !important;
            color: #ffffff !important;
            font-weight: 600 !important;
        }

        div[data-testid="stForm"] button:hover,
        div[data-testid="stFormSubmitButton"] button:hover {
            background: #15803d !important;
            background-color: #15803d !important;
            border-color: #15803d !important;
            color: #ffffff !important;
        }

        /* Tombol Keluar: merah, tetapi dibuat sebagai aksi sekunder yang lebih ringkas. */
        section[data-testid="stSidebar"] .st-key-logout_button {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            padding-top: 0.08rem;
        }

        section[data-testid="stSidebar"] .st-key-logout_button button {
            background: #ef4444 !important;
            background-color: #ef4444 !important;
            border: 1px solid #ef4444 !important;
            color: #ffffff !important;
            font-weight: 600 !important;
            font-size: 0.88rem !important;
            min-height: 2.2rem !important;
            height: 2.2rem !important;
            padding: 0.25rem 0.75rem !important;
            width: auto !important;
            min-width: 4.35rem !important;
        }

        section[data-testid="stSidebar"] .st-key-logout_button button:hover {
            background: #dc2626 !important;
            background-color: #dc2626 !important;
            border-color: #dc2626 !important;
            color: #ffffff !important;
        }

        /* Tombol Proses Optimasi: biru. */
        section[data-testid="stSidebar"] .st-key-proses_optimasi_button button:not(:disabled) {
            background: #2563eb !important;
            background-color: #2563eb !important;
            border: 1px solid #2563eb !important;
            color: #ffffff !important;
            font-weight: 600 !important;
        }

        section[data-testid="stSidebar"] .st-key-proses_optimasi_button button:not(:disabled):hover {
            background: #1d4ed8 !important;
            background-color: #1d4ed8 !important;
            border-color: #1d4ed8 !important;
            color: #ffffff !important;
        }

        @media (max-width: 700px) {
            .bima-header {
                align-items: flex-start;
                gap: 14px;
            }

            .bima-header-logo {
                width: 60px;
            }

            .bima-header-title {
                font-size: 1.75rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# LOGIN APLIKASI
# ============================================================
def validate_login(username: str, password: str) -> bool:
    """Memvalidasi username dan password aplikasi."""
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return (
        hmac.compare_digest(username.strip(), APP_USERNAME)
        and hmac.compare_digest(password_hash, APP_PASSWORD_SHA256)
    )


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    # Sidebar disembunyikan sampai pengguna berhasil login.
    st.markdown(
        """
        <style>
            /* Halaman login dibuat tetap satu layar tanpa scrollbar.
               CSS ini hanya aktif sebelum pengguna berhasil masuk. */
            html,
            body,
            [data-testid="stApp"],
            [data-testid="stAppViewContainer"] {
                height: 100vh !important;
                overflow: hidden !important;
            }

            [data-testid="stMain"] {
                height: 100vh !important;
                overflow: hidden !important;
            }

            [data-testid="stMainBlockContainer"] {
                padding-top: 1.25rem !important;
                padding-bottom: 0.25rem !important;
            }

            section[data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"] {
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    left_login, center_login, right_login = st.columns([1, 1.35, 1])
    with center_login:
        if LOGO_PATH.exists():
            try:
                login_logo_uri = image_to_data_uri(LOGO_PATH)
                st.markdown(
                    f'<div class="bima-login-logo-wrap">'
                    f'<img class="bima-login-logo" src="{login_logo_uri}" '
                    f'alt="Logo PT Bukit Inti Makmur Abadi">'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except OSError:
                pass

        st.markdown(
            '<div class="bima-login-title">Masuk Sistem Optimasi Distribusi</div>'
            '<div class="bima-login-subtitle">PT Bukit Inti Makmur Abadi</div>',
            unsafe_allow_html=True,
        )

        login_card = st.container(border=True)
        with login_card:
            with st.form("login_form", clear_on_submit=False):
                login_username = st.text_input("Nama Pengguna", placeholder="Masukkan nama Pengguna")
                login_password = st.text_input(
                    "Sandi",
                    type="password",
                    placeholder="Masukkan kata sandi",
                )
                login_submitted = st.form_submit_button(
                    "Masuk",
                    type="primary",
                    use_container_width=True,
                )

        if login_submitted:
            if validate_login(login_username, login_password):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Nama user atau sandi tidak sesuai.")

    st.stop()


if LOGO_PATH.exists():
    try:
        logo_uri = image_to_data_uri(LOGO_PATH)
        st.markdown(
            f"""
            <div class="bima-header">
                <img class="bima-header-logo" src="{logo_uri}" alt="Logo PT Bukit Inti Makmur Abadi">
                <div class="bima-header-title">
                    Sistem Optimasi Distribusi Logistik <br>
                    PT Bukit Inti Makmur Abadi
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    except OSError:
        st.markdown(
            '<div class="bima-header-title">Sistem Optimasi Distribusi Logistik PT<br>'
            'Bukit Inti Makmur Abadi</div>',
            unsafe_allow_html=True,
        )
else:
    st.markdown(
        '<div class="bima-header-title">Sistem Optimasi Distribusi Logistik PT<br>'
        'Bukit Inti Makmur Abadi</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# KONFIGURASI INTERNAL
# Tidak ditampilkan kepada pengguna.
# ============================================================
RANDOM_STATE = 42
MAX_K_OTOMATIS = 10
QTY_SKENARIO = 50.0

REQUIRED_STORE_COLUMNS = ["id_toko", "nama_toko", "alamat", "longitude", "latitude"]
REQUIRED_VEHICLE_COLUMNS = ["kode_mobil", "no_mobil", "supir", "tipe_mobil", "maks_kapasitas"]
DEMAND_COLUMN_ALIASES = ["demand", "qty", "qtty", "quantity", "kuantitas", "jumlah_order"]


# ============================================================
# FUNGSI VALIDASI DAN UTILITAS DATA
# ============================================================
def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Menyeragamkan nama kolom agar lebih mudah divalidasi."""
    result = df.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    return result


def normalize_store_id(value) -> str:
    """Menyeragamkan ID toko agar nilai seperti 1 dan 1.0 dianggap sama."""
    if pd.isna(value):
        return ""

    if isinstance(value, (int, np.integer)):
        return str(int(value))

    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))

    text = str(value).strip()
    if text.endswith(".0"):
        numeric_part = text[:-2]
        if numeric_part.replace("-", "", 1).isdigit():
            return numeric_part
    return text


def validate_columns(df: pd.DataFrame, required_cols: List[str], data_name: str) -> None:
    """Memastikan kolom wajib tersedia."""
    missing = [column for column in required_cols if column not in df.columns]
    if missing:
        st.error(f"Data {data_name} belum dapat diproses karena terdapat kolom penting yang tidak ditemukan: {missing}")
        st.stop()


def load_excel(uploaded_file) -> pd.DataFrame:
    """Membaca file Excel."""
    try:
        return normalize_column_names(pd.read_excel(uploaded_file))
    except Exception as exc:
        st.error(f"File Excel tidak dapat dibaca: {exc}")
        st.stop()


def find_demand_column(df: pd.DataFrame) -> str | None:
    """Mencari kolom jumlah pesanan dari beberapa nama yang umum digunakan."""
    for column in DEMAND_COLUMN_ALIASES:
        if column in df.columns:
            return column
    return None


def clean_store_data(df_store: pd.DataFrame) -> pd.DataFrame:
    """Membersihkan data toko tanpa menghapus kolom tambahan."""
    df = df_store.copy()
    validate_columns(df, REQUIRED_STORE_COLUMNS, "toko")

    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["id_toko", "nama_toko", "longitude", "latitude"]).copy()
    after = len(df)

    if after < before:
        st.warning(f"{before - after} baris data toko tidak digunakan karena identitas atau koordinatnya kosong.")

    df["id_toko_key"] = df["id_toko"].apply(normalize_store_id)
    return df.reset_index(drop=True)


def split_depot_customers(df_store: pd.DataFrame) -> Tuple[pd.Series, pd.DataFrame]:
    """Memisahkan depot dengan id_toko = 0 dari toko pelanggan."""
    depot_rows = df_store[df_store["id_toko_key"] == "0"]

    if depot_rows.empty:
        st.error("Lokasi depot tidak ditemukan pada data toko.")
        st.stop()

    if len(depot_rows) > 1:
        st.warning("Ditemukan lebih dari satu baris depot. Sistem menggunakan baris depot pertama.")

    depot = depot_rows.iloc[0]
    customers = df_store[df_store["id_toko_key"] != "0"].copy().reset_index(drop=True)

    if customers.empty:
        st.error("Data toko pelanggan tidak ditemukan.")
        st.stop()

    duplicate_count = int(customers["id_toko_key"].duplicated().sum())
    if duplicate_count > 0:
        st.warning(f"Ditemukan {duplicate_count} ID toko duplikat. Sistem menggunakan baris pertama untuk setiap ID toko.")
        customers = customers.drop_duplicates(subset=["id_toko_key"], keep="first").reset_index(drop=True)

    return depot, customers


def clean_vehicle_data(df_vehicle: pd.DataFrame) -> pd.DataFrame:
    """Membersihkan dan memvalidasi data armada."""
    df = df_vehicle.copy()
    validate_columns(df, REQUIRED_VEHICLE_COLUMNS, "armada")

    df["maks_kapasitas"] = pd.to_numeric(df["maks_kapasitas"], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["kode_mobil", "no_mobil", "tipe_mobil", "maks_kapasitas"]).copy()
    df = df[df["maks_kapasitas"] > 0].copy()

    if len(df) < before:
        st.warning(f"{before - len(df)} baris data armada tidak digunakan karena datanya tidak lengkap atau kapasitasnya tidak valid.")

    if df.empty:
        st.error("Tidak ada data armada valid yang dapat digunakan.")
        st.stop()

    df["maks_kapasitas"] = df["maks_kapasitas"].astype(float)
    return df.reset_index(drop=True)


def prepare_actual_demand(customers: pd.DataFrame) -> pd.DataFrame:
    """Menggunakan demand/qty aktual yang tersedia pada file data toko."""
    demand_column = find_demand_column(customers)
    if demand_column is None:
        st.error(
            "Mode Data Aktual memerlukan kolom jumlah pesanan pada file data toko, "
            "misalnya demand atau qty."
        )
        st.stop()

    active_customers = customers.copy()
    active_customers["demand"] = pd.to_numeric(active_customers[demand_column], errors="coerce").fillna(0)
    active_customers = active_customers[active_customers["demand"] > 0].copy().reset_index(drop=True)

    if active_customers.empty:
        st.error("Tidak ada toko dengan jumlah pesanan lebih dari nol pada data aktual.")
        st.stop()

    return active_customers


# ============================================================
# FUNGSI JARAK, PEMBAGIAN WILAYAH, DAN OPTIMASI RUTE
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
# FUNGSI VISUALISASI PETA
# ============================================================
def format_qty(value: float) -> str:
    """Memformat qty agar bilangan bulat tidak memiliki angka desimal."""
    numeric_value = float(value)
    if numeric_value.is_integer():
        return f"{int(numeric_value):,}".replace(",", ".")
    return f"{numeric_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_distance_km(value: float) -> str:
    """Memformat jarak menggunakan tanda desimal Indonesia."""
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
# FUNGSI OUTPUT EXCEL
# ============================================================
def create_excel_output(
    route_output: pd.DataFrame,
    evaluation_output: pd.DataFrame,
    zone_output: pd.DataFrame,
) -> bytes:
    """Membuat satu file Excel dengan tiga lembar hasil yang rapi."""
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        route_output.to_excel(writer, sheet_name="Hasil Rute", index=False)
        evaluation_output.to_excel(writer, sheet_name="Ringkasan Optimasi", index=False)
        zone_output.to_excel(writer, sheet_name="Pembagian Wilayah", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for cell in worksheet[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")

            for column_cells in worksheet.columns:
                column_number = column_cells[0].column
                max_length = max(
                    len(str(cell.value)) if cell.value is not None else 0
                    for cell in column_cells
                )
                worksheet.column_dimensions[get_column_letter(column_number)].width = min(
                    max(max_length + 2, 12),
                    50,
                )

    output.seek(0)
    return output.getvalue()


# ============================================================
# INPUT PENGGUNA
# ============================================================
def build_input_signature(
    store_file,
    vehicle_file,
    processing_type: str,
    operating_cost_per_km: int,
) -> str | None:
    """Membuat penanda input agar hasil lama tidak tampil untuk data yang berubah."""
    if store_file is None or vehicle_file is None:
        return None

    digest = hashlib.sha256()
    digest.update(store_file.getvalue())
    digest.update(vehicle_file.getvalue())
    digest.update(processing_type.encode("utf-8"))
    digest.update(str(int(operating_cost_per_km)).encode("utf-8"))
    return digest.hexdigest()


if "optimization_result" not in st.session_state:
    st.session_state.optimization_result = None
if "processed_input_signature" not in st.session_state:
    st.session_state.processed_input_signature = None

with st.sidebar:
    sidebar_title_col, sidebar_logout_col = st.columns([4.1, 1.25])
    with sidebar_title_col:
        st.markdown("### 📂 Masukan Data")
    with sidebar_logout_col:
        logout_ditekan = st.button(
            "Keluar",
            type="primary",
            help="Keluar dari sistem",
            key="logout_button",
            use_container_width=False,
        )

if logout_ditekan:
    st.session_state.authenticated = False
    st.session_state.optimization_result = None
    st.session_state.processed_input_signature = None
    st.rerun()

file_toko = st.sidebar.file_uploader("Masukan data toko (.xlsx)", type=["xlsx"])
file_mobil = st.sidebar.file_uploader("Masukan data armada (.xlsx)", type=["xlsx"])

jenis_pengolahan = st.sidebar.radio(
    "Jenis pengolahan",
    options=["Seluruh toko (qty 50)", "Data aktual"],
    index=0,
    horizontal=True,
)

st.sidebar.divider()
biaya_per_km = st.sidebar.number_input(
    "Biaya operasional per km (Rp)",
    min_value=500,
    max_value=50000,
    value=2500,
    step=500,
)

input_lengkap = file_toko is not None and file_mobil is not None
proses_ditekan = st.sidebar.button(
    "▶ Proses Optimasi",
    type="primary",
    key="proses_optimasi_button",
    use_container_width=True,
    disabled=not input_lengkap,
)

current_input_signature = build_input_signature(
    store_file=file_toko,
    vehicle_file=file_mobil,
    processing_type=jenis_pengolahan,
    operating_cost_per_km=int(biaya_per_km),
)


# ============================================================
# PROSES UTAMA
# Proses hanya berjalan setelah tombol Proses Optimasi ditekan.
# ============================================================
if proses_ditekan:
    # Hapus hasil lama lebih dahulu agar hasil sebelumnya tidak tertukar
    # apabila proses baru mengalami kendala validasi.
    st.session_state.optimization_result = None
    st.session_state.processed_input_signature = None

    with st.spinner("Data sedang diproses..."):
        start_time = time.perf_counter()

        # File dibaca dari salinan byte agar aman ketika tombol ditekan kembali.
        df_store_raw = load_excel(BytesIO(file_toko.getvalue()))
        df_vehicle_raw = load_excel(BytesIO(file_mobil.getvalue()))

        df_store = clean_store_data(df_store_raw)
        df_vehicle = clean_vehicle_data(df_vehicle_raw)
        depot, customers = split_depot_customers(df_store)

        # Pembagian wilayah menggunakan seluruh master toko.
        selected_k, k_evaluation = determine_optimal_k(customers)
        clustered_customers, centroid_df = run_kmeans(
            customers,
            n_clusters=selected_k,
        )

        # Menentukan data yang akan dibuatkan rute.
        if jenis_pengolahan == "Seluruh toko (qty 50)":
            active_customers = clustered_customers.copy()
            active_customers["demand"] = QTY_SKENARIO
            scenario_note = (
                f"Seluruh {len(active_customers)} toko diproses dengan jumlah pesanan tetap "
                f"{QTY_SKENARIO:g} untuk setiap toko."
            )
        else:
            actual_customers = prepare_actual_demand(customers)
            active_customers = actual_customers.merge(
                clustered_customers[["id_toko_key", "cluster"]],
                on="id_toko_key",
                how="left",
                validate="one_to_one",
            )
            active_customers = active_customers.reset_index(drop=True)
            scenario_note = (
                f"Sebanyak {len(active_customers)} toko dengan jumlah pesanan aktual "
                "lebih dari nol diproses."
            )

        # Menghitung jarak kondisi awal: setiap toko dilayani secara terpisah.
        active_customers = active_customers.reset_index(drop=True)
        total_distance_before = float(
            sum(
                2 * distance_depot_to_customer(depot, customer)
                for _, customer in active_customers.iterrows()
            )
        )

        # Alokasi toko dan armada dilakukan sebelum penyusunan urutan rute.
        allocated_customers = allocate_customers_to_fleet(
            active_customers=active_customers,
            vehicles_df=df_vehicle,
        )
        assigned_routes = build_routes_from_allocation(
            allocated_customers=allocated_customers,
            vehicles_df=df_vehicle,
            depot=depot,
        )

        if len(assigned_routes) > len(df_vehicle):
            st.error("Jumlah rute melebihi jumlah armada yang tersedia.")
            st.stop()

        total_distance_after = (
            float(assigned_routes["total_jarak_km"].sum())
            if not assigned_routes.empty
            else 0.0
        )
        distance_saved = total_distance_before - total_distance_after
        reduction_percentage = (
            distance_saved / total_distance_before * 100
            if total_distance_before > 0
            else 0.0
        )
        cost_saved = max(distance_saved, 0) * biaya_per_km
        avg_utilization = (
            assigned_routes["utilisasi_persen"].mean(skipna=True)
            if not assigned_routes.empty
            else 0.0
        )
        computational_time = time.perf_counter() - start_time

        st.session_state.optimization_result = {
            "df_vehicle": df_vehicle,
            "depot": depot,
            "customers": customers,
            "clustered_customers": clustered_customers,
            "active_customers": active_customers,
            "assigned_routes": assigned_routes,
            "selected_k": selected_k,
            "k_evaluation": k_evaluation,
            "centroid_df": centroid_df,
            "scenario_note": scenario_note,
            "total_distance_before": total_distance_before,
            "total_distance_after": total_distance_after,
            "reduction_percentage": reduction_percentage,
            "cost_saved": cost_saved,
            "avg_utilization": avg_utilization,
            "computational_time": computational_time,
        }
        st.session_state.processed_input_signature = current_input_signature


# ============================================================
# STATUS SEBELUM HASIL DITAMPILKAN
# ============================================================
if not input_lengkap:
    st.info(
        "Silakan masukan data toko dan data armada melalui panel kiri, "
        "kemudian tekan tombol Proses Optimasi."
    )
    st.stop()

result = st.session_state.optimization_result
processed_signature = st.session_state.processed_input_signature

if result is None:
    st.info("Data sudah siap. Tekan tombol Proses Optimasi untuk menjalankan sistem.")
    st.stop()

if processed_signature != current_input_signature:
    st.warning(
        "Data atau pilihan pengolahan telah berubah. Tekan tombol Proses Optimasi "
        "untuk memperbarui hasil."
    )
    st.stop()

# Mengambil hasil tersimpan. Membuka tab atau mengunduh file tidak akan
# menjalankan perhitungan dari awal.
df_vehicle = result["df_vehicle"]
depot = result["depot"]
customers = result["customers"]
clustered_customers = result["clustered_customers"]
active_customers = result["active_customers"]
assigned_routes = result["assigned_routes"]
selected_k = result["selected_k"]
k_evaluation = result["k_evaluation"]
centroid_df = result["centroid_df"]
scenario_note = result["scenario_note"]
total_distance_before = result["total_distance_before"]
total_distance_after = result["total_distance_after"]
reduction_percentage = result["reduction_percentage"]
cost_saved = result["cost_saved"]
avg_utilization = result["avg_utilization"]
computational_time = result["computational_time"]


# ============================================================
# DASHBOARD HASIL
# ============================================================
metric_1, metric_2, metric_3, metric_4, metric_5 = st.columns(5)
metric_1.metric("Toko diproses", f"{len(active_customers)}")
metric_2.metric("Zona terbentuk", f"{selected_k}")
metric_3.metric("Rute terbentuk", f"{len(assigned_routes)}")
metric_4.metric("Reduksi jarak", f"{reduction_percentage:.2f}%")
metric_5.metric("Estimasi hemat biaya", f"Rp {cost_saved:,.0f}")

st.caption(scenario_note)

if not assigned_routes.empty:
    unused_vehicles = len(df_vehicle) - len(assigned_routes)
    st.success(
        f"Seluruh permintaan berhasil dialokasikan ke {len(assigned_routes)} armada. "
        f"Setiap armada melayani satu rute dan {unused_vehicles} armada tidak digunakan."
    )


tab_results, tab_maps, tab_download = st.tabs(
    ["Hasil Optimasi", "Visualisasi Peta", "Download Output"]
)

with tab_results:
    st.subheader("Hasil Rute Distribusi")

    if assigned_routes.empty:
        st.warning("Rute distribusi belum terbentuk.")
        route_output = pd.DataFrame()
    else:
        # ID toko tetap digunakan pada proses internal, tetapi tidak ditampilkan.
        route_display_columns = [
            "route_id", "cluster", "jumlah_toko", "total_demand", "total_jarak_km",
            "kode_mobil", "no_mobil", "supir", "tipe_mobil", "maks_kapasitas",
            "utilisasi_persen", "status_armada", "nama_toko_sequence",
        ]

        route_output = assigned_routes[route_display_columns].copy()
        route_output = route_output.rename(
            columns={
                "route_id": "rute",
                "cluster": "zona",
                "total_demand": "total_qty",
                "total_jarak_km": "total_jarak_km",
                "maks_kapasitas": "kapasitas_armada",
                "utilisasi_persen": "utilisasi_armada_persen",
                "nama_toko_sequence": "urutan_nama_toko",
            }
        )
        route_output["total_jarak_km"] = route_output["total_jarak_km"].round(3)
        route_output["utilisasi_armada_persen"] = route_output[
            "utilisasi_armada_persen"
        ].round(2)
        st.dataframe(route_output, use_container_width=True, hide_index=True)

        st.write("**Ringkasan hasil**")

    evaluation_df = pd.DataFrame(
        [
            {"Keterangan": "Jumlah toko diproses", "Nilai": len(active_customers)},
            {"Keterangan": "Jumlah zona terbentuk", "Nilai": selected_k},
            {"Keterangan": "Total jarak kondisi awal (km)", "Nilai": round(total_distance_before, 3)},
            {"Keterangan": "Total jarak hasil optimasi (km)", "Nilai": round(total_distance_after, 3)},
            {"Keterangan": "Reduksi jarak (%)", "Nilai": round(reduction_percentage, 3)},
            {"Keterangan": "Estimasi penghematan biaya (Rp)", "Nilai": round(cost_saved, 0)},
            {"Keterangan": "Total permintaan", "Nilai": round(float(active_customers["demand"].sum()), 3)},
            {"Keterangan": "Total kapasitas armada", "Nilai": round(float(df_vehicle["maks_kapasitas"].sum()), 3)},
            {"Keterangan": "Jumlah rute terbentuk", "Nilai": len(assigned_routes)},
            {"Keterangan": "Jumlah armada tersedia", "Nilai": len(df_vehicle)},
            {"Keterangan": "Jumlah armada digunakan", "Nilai": len(assigned_routes)},
            {"Keterangan": "Jumlah armada tidak digunakan", "Nilai": len(df_vehicle) - len(assigned_routes)},
            {"Keterangan": "Rata-rata utilisasi armada (%)", "Nilai": round(avg_utilization, 3)},
            {"Keterangan": "Waktu proses (detik)", "Nilai": round(computational_time, 3)},
        ]
    )

    if not assigned_routes.empty:
        st.dataframe(evaluation_df, use_container_width=True, hide_index=True)

with tab_maps:
    st.subheader("Visualisasi Peta")
    map_tab_1, map_tab_2, map_tab_3 = st.tabs(
        ["Pembagian Wilayah", "Kondisi Awal", "Hasil Optimasi"]
    )

    with map_tab_1:
        st_folium(plot_zone_map(clustered_customers, depot), width=1100, height=550)

    with map_tab_2:
        st.caption(
            "Kondisi awal menggambarkan setiap toko dilayani melalui perjalanan "
            "terpisah dari depot."
        )
        st_folium(
            plot_before_optimization_map(active_customers, depot),
            width=1100,
            height=550,
        )

    with map_tab_3:
        st.caption(
            "Klik salah satu jalur untuk menonjolkannya. Jalur lain akan memudar; "
            "klik area kosong pada peta untuk menampilkan semua jalur kembali."
        )
        st_folium(
            plot_after_optimization_map(assigned_routes, active_customers, depot),
            width=1100,
            height=550,
        )

with tab_download:
    st.subheader("Download Output")

    if assigned_routes.empty:
        st.warning("File hasil belum tersedia karena rute distribusi belum terbentuk.")
    else:
        # File pembagian wilayah tidak menyertakan id_toko maupun kolom ID internal.
        zone_output = clustered_customers.drop(
            columns=["id_toko", "id_toko_key"],
            errors="ignore",
        ).copy()
        zone_output = zone_output.rename(
            columns={
                "nama_toko": "nama_toko",
                "alamat": "alamat",
                "longitude": "longitude",
                "latitude": "latitude",
                "cluster": "zona",
            }
        )

        excel_file = create_excel_output(
            route_output=route_output,
            evaluation_output=evaluation_df,
            zone_output=zone_output,
        )

        st.download_button(
            label="Download hasil optimasi (.xlsx)",
            data=excel_file,
            file_name="hasil_optimasi_distribusi.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.caption(
            "File Excel berisi tiga sheet: Hasil Rute, Ringkasan Optimasi, "
            "dan Pembagian Wilayah. Kolom ID toko tidak disertakan."
        )
