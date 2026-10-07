import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from datetime import date, timedelta
import json

# =============================================================
# CONFIGURAZIONE PAGINA
# =============================================================
st.set_page_config(page_title="Analisi Eventi Climatici", layout="wide")
st.title("⛈️ Monitoraggio Meteo nei Comuni Italiani")
st.write("Dati storici e previsioni a 7 giorni tramite API Open-Meteo.")


# =============================================================
# GEOCODIFICA
# =============================================================
@st.cache_data(show_spinner=False)
def ottieni_coordinate(nome_comune):
    geolocator = Nominatim(user_agent="app_eventi_meteo_2026")
    try:
        location = geolocator.geocode(f"{nome_comune}, Italia")
        if location:
            return round(location.latitude, 4), round(location.longitude, 4)
    except Exception:
        pass
    return None, None


# =============================================================
# OPEN-METEO — DATI STORICI
# =============================================================
@st.cache_data(show_spinner=False, ttl=3600)
def scarica_dati_storici(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    parametri = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": [
            "precipitation_sum",
            "wind_gusts_10m_max",
            "temperature_2m_max",
            "temperature_2m_min",
            "pressure_msl_mean",
            "relative_humidity_2m_mean",
            "shortwave_radiation_sum",
        ],
        "timezone": "Europe/Rome",
        "wind_speed_unit": "kmh"
    }
    r = requests.get(url, params=parametri, timeout=20)
    return r.status_code, r.text


# =============================================================
# OPEN-METEO — PREVISIONI 7 GIORNI (aggiornamento automatico)
# =============================================================
@st.cache_data(show_spinner=False, ttl=600)  # cache 10 minuti
def scarica_previsioni_7giorni(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    parametri = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "precipitation_sum",
            "wind_gusts_10m_max",
            "temperature_2m_max",
            "temperature_2m_min",
            "pressure_msl_mean",
            "relative_humidity_2m_mean",
            "shortwave_radiation_sum",
        ],
        "timezone": "Europe/Rome",
        "wind_speed_unit": "kmh",
        "forecast_days": 7,
    }
    r = requests.get(url, params=parametri, timeout=20)
    return r.status_code, r.text


# =============================================================
# INTERFACCIA
# =============================================================
comune = st.text_input("Nome del comune (es. Milano, Palermo):", "Milano")

if comune:
    lat, lon = ottieni_coordinate(comune)

    if lat is None:
        st.error("Comune non trovato. Controlla l'ortografia e riprova.")
    else:
        st.success(f"Coordinate di {comune.upper()}: Lat {lat}, Lon {lon}")

        # Pulsante di aggiornamento manuale
        if st.button("🔄 Aggiorna previsioni"):
            st.cache_data.clear()
            st.rerun()

        # --- Selettore date per lo storico ---
        oggi = date.today()
        un_mese_fa = oggi - timedelta(days=30)

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            data_inizio = st.date_input(
                "Data inizio (storico)",
                value=un_mese_fa,
                max_value=oggi - timedelta(days=1)
            )
        with col_d2:
            data_fine = st.date_input(
                "Data fine (storico)",
                value=oggi - timedelta(days=1),
                max_value=oggi - timedelta(days=1)
            )

        if data_inizio >= data_fine:
            st.warning("La data di inizio deve essere precedente alla data di fine.")
            st.stop()

        # --- Soglie di allerta ---
        st.sidebar.header("⚙️ Soglie di Allerta")
        soglia_pioggia = st.sidebar.slider("Pioggia giornaliera (mm)", 10.0, 100.0, 30.0, step=5.0)
        soglia_vento = st.sidebar.slider("Raffiche di vento (km/h)", 30.0, 120.0, 50.0, step=5.0)

        # =============================================================
        # DUE TAB: STORICO | PREVISIONI 7 GIORNI
        # =============================================================
        tab_storico, tab_previsioni = st.tabs(["📅 Storico", "🔮 Previsioni 7 giorni"])

        # -------------------------------------------------------------
        # TAB 1: STORICO
        # -------------------------------------------------------------
        with tab_storico:
            try:
                with st.spinner("Recupero dati storici..."):
                    status_code, testo = scarica_dati_storici(
                        lat, lon,
                        data_inizio.strftime("%Y-%m-%d"),
                        data_fine.strftime("%Y-%m-%d")
                    )

                if status_code != 200:
                    st.error(f"Errore storico (HTTP {status_code}).")
                else:
                    data_json = json.loads(testo)
                    daily = data_json.get("daily", {})
                    dates = daily.get("time", [])

                    if dates:
                        precips = daily.get("precipitation_sum", [0]*len(dates))
                        gusts = daily.get("wind_gusts_10m_max", [0]*len(dates))
                        tmax = daily.get("temperature_2m_max", [0]*len(dates))
                        tmin = daily.get("temperature_2m_min", [0]*len(dates))
                        press = daily.get("pressure_msl_mean", [0]*len(dates))
                        umid = daily.get("relative_humidity_2m_mean", [0]*len(dates))
                        rad = daily.get("shortwave_radiation_sum", [0]*len(dates))

                        def val(seq, i):
                            v = seq[i] if i < len(seq) else None
                            return v if v is not None else 0.0

                        df = pd.DataFrame({
                            "Data": pd.to_datetime(dates),
                            "Pioggia (mm)": [val(precips, i) for i in range(len(dates))],
                            "Raffica Vento (km/h)": [val(gusts, i) for i in range(len(dates))],
                            "Temp Max (°C)": [val(tmax, i) for i in range(len(dates))],
                            "Temp Min (°C)": [val(tmin, i) for i in range(len(dates))],
                            "Pressione (hPa)": [val(press, i) for i in range(len(dates))],
                            "Umidità (%)": [val(umid, i) for i in range(len(dates))],
                            "Radiazione (MJ/m²)": [val(rad, i) for i in range(len(dates))],
                        })

                        # Eventi estremi
                        cond = (df["Pioggia (mm)"] > soglia_pioggia) | (df["Raffica Vento (km/h)"] > soglia_vento)
                        estremi = df[cond].copy()

                        col1, col2 = st.columns(2)
                        with col1:
                            st.subheader("📍 Posizione")
                            m = folium.Map(location=[lat, lon], zoom_start=11)
                            folium.Marker(
                                [lat, lon],
                                popup=f"{comune}: {len(estremi)} eventi",
                                icon=folium.Icon(color="red" if not estremi.empty else "green")
                            ).add_to(m)
                            st_folium(m, width=500, height=400, key="mappa_storico")

                        with col2:
                            st.subheader("📊 Eventi Estremi")
                            if not estremi.empty:
                                note = []
                                for _, row in estremi.iterrows():
                                    motivi = []
                                    if row["Pioggia (mm)"] > soglia_pioggia:
                                        motivi.append(f"🌧️ {row['Pioggia (mm)']:.1f} mm")
                                    if row["Raffica Vento (km/h)"] > soglia_vento:
                                        motivi.append(f"💨 {row['Raffica Vento (km/h)']:.1f} km/h")
                                    note.append(" + ".join(motivi))
                                estremi["Tipo"] = note
                                vista = estremi.copy()
                                vista["Data"] = vista["Data"].dt.strftime("%d-%m-%Y")
                                st.dataframe(vista[["Data", "Pioggia (mm)", "Raffica Vento (km/h)", "Tipo"]], use_container_width=True)
                            else:
                                st.info("Nessun evento sopra soglia.")

                        # Tabella completa
                        st.subheader("📅 Dati completi (storico)")
                        vista_full = df.copy()
                        vista_full["Data"] = vista_full["Data"].dt.strftime("%d-%m-%Y")
                        st.dataframe(vista_full, use_container_width=True)

                        # Grafici
                        with st.expander("📈 Grafici di tendenza (storico)", expanded=False):
                            df_plot = df.set_index("Data")
                            st.markdown("**Temperature**")
                            st.line_chart(df_plot[["Temp Max (°C)", "Temp Min (°C)"]])
                            st.markdown("**Pioggia e Vento**")
                            st.line_chart(df_plot[["Pioggia (mm)", "Raffica Vento (km/h)"]])
                            st.markdown("**Pressione**")
                            st.line_chart(df_plot[["Pressione (hPa)"]])
                            st.markdown("**Umidità**")
                            st.line_chart(df_plot[["Umidità (%)"]])
                            st.markdown("**Radiazione solare**")
                            st.line_chart(df_plot[["Radiazione (MJ/m²)"]])
                    else:
                        st.warning("Nessun dato storico disponibile.")
            except Exception as e:
                st.error(f"Errore tecnico nello storico: {e}")

        # -------------------------------------------------------------
        # TAB 2: PREVISIONI 7 GIORNI
        # -------------------------------------------------------------
        with tab_previsioni:
            try:
                with st.spinner("Recupero previsioni a 7 giorni..."):
                    status_fc, testo_fc = scarica_previsioni_7giorni(lat, lon)

                if status_fc != 200:
                    st.error(f"Errore previsioni (HTTP {status_fc}).")
                else:
                    dati_fc = json.loads(testo_fc)
                    daily_fc = dati_fc.get("daily", {})
                    dates_fc = daily_fc.get("time", [])

                    if dates_fc:
                        precips_fc = daily_fc.get("precipitation_sum", [0]*len(dates_fc))
                        gusts_fc = daily_fc.get("wind_gusts_10m_max", [0]*len(dates_fc))
                        tmax_fc = daily_fc.get("temperature_2m_max", [0]*len(dates_fc))
                        tmin_fc = daily_fc.get("temperature_2m_min", [0]*len(dates_fc))
                        press_fc = daily_fc.get("pressure_msl_mean", [0]*len(dates_fc))
                        umid_fc = daily_fc.get("relative_humidity_2m_mean", [0]*len(dates_fc))
                        rad_fc = daily_fc.get("shortwave_radiation_sum", [0]*len(dates_fc))

                        def val_fc(seq, i):
                            v = seq[i] if i < len(seq) else None
                            return v if v is not None else 0.0

                        df_fc = pd.DataFrame({
                            "Data": pd.to_datetime(dates_fc),
                            "Pioggia (mm)": [val_fc(precips_fc, i) for i in range(len(dates_fc))],
                            "Raffica Vento (km/h)": [val_fc(gusts_fc, i) for i in range(len(dates_fc))],
                            "Temp Max (°C)": [val_fc(tmax_fc, i) for i in range(len(dates_fc))],
                            "Temp Min (°C)": [val_fc(tmin_fc, i) for i in range(len(dates_fc))],
                            "Pressione (hPa)": [val_fc(press_fc, i) for i in range(len(dates_fc))],
                            "Umidità (%)": [val_fc(umid_fc, i) for i in range(len(dates_fc))],
                            "Radiazione (MJ/m²)": [val_fc(rad_fc, i) for i in range(len(dates_fc))],
                        })

                        # Tabella previsioni
                        st.subheader("📋 Tabella previsioni (7 giorni)")
                        vista_fc = df_fc.copy()
                        vista_fc["Data"] = vista_fc["Data"].dt.strftime("%d-%m-%Y (%A)")
                        st.dataframe(vista_fc, use_container_width=True)

                        # Grafici previsioni
                        st.subheader("📈 Grafici di tendenza (previsioni)")
                        df_fc_plot = df_fc.set_index("Data")

                        st.markdown("**Temperature previste**")
                        st.line_chart(df_fc_plot[["Temp Max (°C)", "Temp Min (°C)"]])

                        st.markdown("**Pioggia e Vento previsti**")
                        st.line_chart(df_fc_plot[["Pioggia (mm)", "Raffica Vento (km/h)"]])

                        st.markdown("**Pressione prevista**")
                        st.line_chart(df_fc_plot[["Pressione (hPa)"]])

                        st.markdown("**Umidità prevista**")
                        st.line_chart(df_fc_plot[["Umidità (%)"]])

                        st.markdown("**Radiazione solare prevista**")
                        st.line_chart(df_fc_plot[["Radiazione (MJ/m²)"]])

                        # Download CSV previsioni
                        csv_fc = df_fc.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="📥 Scarica previsioni in CSV",
                            data=csv_fc,
                            file_name=f"previsioni_{comune}.csv",
                            mime="text/csv",
                        )
                    else:
                        st.warning("Nessun dato di previsione disponibile.")
            except Exception as e:
                st.error(f"Errore tecnico nelle previsioni: {e}")