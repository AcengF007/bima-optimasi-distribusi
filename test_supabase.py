import streamlit as st
from supabase import create_client, Client

supabase: Client = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_PUBLISHABLE_KEY"],
)

st.title("Tes Login Supabase")

email = st.text_input("Email")
password = st.text_input("Password", type="password")

if st.button("Login"):
    try:
        auth_response = supabase.auth.sign_in_with_password(
            {
                "email": email,
                "password": password,
            }
        )

        if auth_response.user:
            st.success("Login berhasil.")

            profile = (
                supabase.table("profiles")
                .select("username,nama,role,status")
                .eq("id", auth_response.user.id)
                .single()
                .execute()
            )

            st.write("Profil:")
            st.write(profile.data)

            stores = (
                supabase.table("stores")
                .select("id_toko,nama_toko,zona")
                .limit(5)
                .execute()
            )

            st.write("Contoh Master Toko:")
            st.write(stores.data)

    except Exception as exc:
        st.error(f"Login/koneksi gagal: {exc}")
