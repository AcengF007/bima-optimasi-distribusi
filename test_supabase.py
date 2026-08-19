import streamlit as st
from supabase import create_client, Client

supabase: Client = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_PUBLISHABLE_KEY"],
)

st.title("Tes Koneksi Supabase")

try:
    response = (
        supabase.table("stores")
        .select("id_toko,nama_toko,zona")
        .limit(5)
        .execute()
    )

    st.success("Koneksi ke Supabase berhasil.")
    st.write(response.data)

except Exception as exc:
    st.error(f"Koneksi gagal: {exc}")
