import streamlit as st
import requests
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from datetime import date, timedelta
import json

# =============================================================
# CONFIGURAZIONE PAGINA
# =============================================================
st.set_page_config(page_title="Analisi Eventi Climatici", layout="wide")
st.title("⛈️ Monitoraggio Meteo nei Comuni Italiani")
st.write("Dati storici e previsioni a 7 giorni tramite API Open-Meteo.")


# =============================================================
# GEOCODIFICA — Open-Meteo Geocoding API
# =============================================================
@st.cache_data(show_spinner=False, ttl=86400)  # cache 1 giorno
def cerca_comuni(nome_comune):
    """Restituisce una lista di comuni italiani candidati per il nome dato."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    parametri = {
        "name": nome_comune,
        "count": 10,
        "language": "it",
        "countryCode": "IT",
        "format": "json",
    }
    try:
        r = requests.get(url, params=parametri, timeout=10)
        r.raise_for_status()
        risultati = r.json().get("results", []) or []
    except Exception:
        return []

    # Preferisci i "populated place" (PPL*): comuni, paesi, frazioni abitate
    comuni = [x for x in risultati if str(x.get("feature_code", "")).startswith("PPL")]
    if not comuni:
        comuni = risultati
    # Ordina per popolazione decrescente (più probabile che sia quello giusto)
    comuni.sort(key=lambda x: x.get("population", 0), reverse=True)
    return comuni


def etichetta_candidato(x):
    """Testo da mostrare nella selectbox per ogni candidato."""
    nome = x.get("name", "?")
    prov = x.get("admin2", "?")
    reg = x.get("admin1", "?")
    pop = x.get("population")
    pop_str = f" · pop. {pop:,}" if pop else ""
    return f"{nome} — {prov} ({reg}){pop_str}"


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
        "wind_speed_unit": "kmh",
    }
    try:
        r = requests.get(url, params=parametri, timeout=25)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# =============================================================
# OPEN-METEO — PREVISIONI 7 GIORNI
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
    try:
        r = requests.get(url, params=parametri, timeout=25)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# =============================================================
# UTILITÀ — costruzione DataFrame da risposta Open-Meteo
# =============================================================
def costruisci_dataframe(testo_json):
    """Trasforma la risposta daily di Open-Meteo in DataFrame.
    I valori None diventano NaN (non 0.0) per non falsare i grafici."""
    daily = testo_json.get("daily", {})
    dates = daily.get("time", [])
    if not dates:
        return None

    def colonna(chiave):
        seq = daily.get(chiave, [])
        # allinea lunghezza
        seq = list(seq) + [None] * (len(dates) - len(seq))
        return pd.to_numeric(pd.Series(seq), errors="coerce")  # None -> NaN

    df = pd.DataFrame({
        "Data": pd.to_datetime(dates, errors="coerce"),
        "Pioggia (mm)": colonna("precipitation_sum"),
        "Raffica Vento (km/h)": colonna("wind_gusts_10m_max"),
        "Temp Max (°C)": colonna("temperature_2m_max"),
        "Temp Min (°C)": colonna("temperature_2m_min"),
        "Pressione (hPa)": colonna("pressure_msl_mean"),
        "Umidità (%)": colonna("relative_humidity_2m_mean"),
        "Radiazione (MJ/m²)": colonna("shortwave_radiation_sum"),
    })
    df = df.dropna(subset=["Data"]).reset_index(drop=True)
    return df


def evidenzia_eventi(df, soglia_pioggia, soglia_vento):
    """Aggiunge una colonna 'Tipo' con l'elenco dei superamenti soglia."""
    tipi = []
    for _, row in df.iterrows():
        motivi = []
        if pd.notna(row["Pioggia (mm)"]) and row["Pioggia (mm)"] > soglia_pioggia:
            motivi.append(f"🌧️ {row['Pioggia (mm)']:.1f} mm")
        if pd.notna(row["Raffica Vento (km/h)"]) and row["Raffica Vento (km/h)"] > soglia_vento:
            motivi.append(f"💨 {row['Raffica Vento (km/h)']:.1f} km/h")
        tipi.append(" + ".join(motivi) if motivi else "")
    df = df.copy()
    df["Tipo"] = tipi
    return df


# =============================================================
# INTERFACCIA — INPUT COMUNE
# =============================================================
comune = st.text_input("Nome del comune (es. Milano, Palermo):", "Milano")

lat, lon, scelto = None, None, None

if comune:
    candidati = cerca_comuni(comune)

    if not candidati:
        st.error("Comune non trovato. Controlla l'ortografia e riprova.")
    else:
        col_a, col_b = st.columns([4, 1])
        with col_a:
            if len(candidati) == 1:
                scelto = candidati[0]
                st.caption(f"Trovata 1 località per «{comune}».")
            else:
                scelto = st.selectbox(
                    f"Trovate {len(candidati)} località per «{comune}». Quale intendi?",
                    options=candidati,
                    format_func=etichetta_candidato,
                )
        with col_b:
            st.write("")  # spaziatura
            st.write("")
            if st.button("🔄 Cerca di nuovo"):
                cerca_comuni.clear()
                st.rerun()

        if scelto:
            lat = round(scelto["latitude"], 5)
            lon = round(scelto["longitude"], 5)
            st.success(
                f"📍 **{scelto.get('name','?')}** — "
                f"{scelto.get('admin2','?')}, {scelto.get('admin1','?')} "
                f"(lat {lat}, lon {lon})"
            )


# =============================================================
# SE L'UTENTE HA SCELTO UN COMUNE VALIDO
# =============================================================
if lat is not None and lon is not None:

    # --- Soglie di allerta ---
    st.sidebar.header("⚙️ Soglie di Allerta")
    soglia_pioggia = st.sidebar.slider("Pioggia giornaliera (mm)", 10.0, 100.0, 30.0, step=5.0)
    soglia_vento = st.sidebar.slider("Raffiche di vento (km/h)", 30.0, 120.0, 50.0, step=5.0)

    # --- Selettore date per lo storico ---
    oggi = date.today()
    un_mese_fa = oggi - timedelta(days=30)
    limite_min = oggi - timedelta(days=365 * 5)  # 5 anni indietro (Archive API)

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        data_inizio = st.date_input(
            "Data inizio (storico)",
            value=un_mese_fa,
            min_value=limite_min,
            max_value=oggi - timedelta(days=1),
        )
    with col_d2:
        data_fine = st.date_input(
            "Data fine (storico)",
            value=oggi - timedelta(days=1),
            min_value=limite_min,
            max_value=oggi - timedelta(days=1),
        )

    date_ok = data_inizio < data_fine
    if not date_ok:
        st.warning("⚠️ La data di inizio deve essere precedente alla data di fine. Correggi per vedere lo storico.")

    # =========================================================
    # DUE TAB: STORICO | PREVISIONI 7 GIORNI
    # =========================================================
    tab_storico, tab_previsioni = st.tabs(["📅 Storico", "🔮 Previsioni 7 giorni"])

    # ---------------------------------------------------------
    # TAB 1: STORICO
    # ---------------------------------------------------------
    with tab_storico:
        if not date_ok:
            st.info("Correggi le date per caricare lo storico.")
        else:
            try:
                with st.spinner("Recupero dati storici..."):
                    status_code, testo = scarica_dati_storici(
                        lat, lon,
                        data_inizio.strftime("%Y-%m-%d"),
                        data_fine.strftime("%Y-%m-%d"),
                    )

                if status_code != 200:
                    st.error(f"Errore storico (HTTP {status_code}). Dettaglio: {testo[:300]}")
                else:
                    data_json = json.loads(testo)
                    df = costruisci_dataframe(data_json)

                    if df is None or df.empty:
                        st.warning("Nessun dato storico disponibile per il periodo selezionato.")
                    else:
                        df = evidenzia_eventi(df, soglia_pioggia, soglia_vento)
                        estremi = df[df["Tipo"] != ""].copy()

                        col1, col2 = st.columns(2)
                        with col1:
                            st.subheader("📍 Posizione")
                            m = folium.Map(location=[lat, lon], zoom_start=11)
                            folium.Marker(
                                [lat, lon],
                                popup=f"{scelto.get('name','?')}: {len(estremi)} eventi",
                                icon=folium.Icon(color="red" if not estremi.empty else "green"),
                            ).add_to(m)
                            st_folium(m, width=500, height=400, key="mappa_storico")

                        with col2:
                            st.subheader("📊 Eventi Estremi")
                            if not estremi.empty:
                                vista = estremi.copy()
                                vista["Data"] = vista["Data"].dt.strftime("%d-%m-%Y")
                                st.dataframe(
                                    vista[["Data", "Pioggia (mm)", "Raffica Vento (km/h)", "Tipo"]],
                                    use_container_width=True,
                                )
                            else:
                                st.info("Nessun evento sopra soglia.")

                        # Tabella completa
                        st.subheader("📅 Dati completi (storico)")
                        vista_full = df.copy()
                        vista_full["Data"] = vista_full["Data"].dt.strftime("%d-%m-%Y")
                        st.dataframe(vista_full, use_container_width=True)

                        # Download CSV storico
                        csv_st = df.copy()
                        csv_st["Data"] = csv_st["Data"].dt.strftime("%Y-%m-%d")
                        st.download_button(
                            label="📥 Scarica storico in CSV",
                            data=csv_st.to_csv(index=False).encode("utf-8"),
                            file_name=f"storico_{scelto.get('name','comune')}.csv",
                            mime="text/csv",
                        )

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
            except Exception as e:
                st.error(f"Errore tecnico nello storico: {e}")

    # ---------------------------------------------------------
    # TAB 2: PREVISIONI 7 GIORNI
    # ---------------------------------------------------------
    with tab_previsioni:
        try:
            with st.spinner("Recupero previsioni a 7 giorni..."):
                status_fc, testo_fc = scarica_previsioni_7giorni(lat, lon)

            if status_fc != 200:
                st.error(f"Errore previsioni (HTTP {status_fc}). Dettaglio: {testo_fc[:300]}")
            else:
                dati_fc = json.loads(testo_fc)
                df_fc = costruisci_dataframe(dati_fc)

                if df_fc is None or df_fc.empty:
                    st.warning("Nessun dato di previsione disponibile.")
                else:
                    df_fc = evidenzia_eventi(df_fc, soglia_pioggia, soglia_vento)
                    eventi_fc = df_fc[df_fc["Tipo"] != ""]

                    # Avviso sintetico su giorni critici
                    if not eventi_fc.empty:
                        st.warning(
                            f"⚠️ {len(eventi_fc)} giorni sopra soglia nei prossimi 7 giorni."
                        )
                    else:
                        st.success("✅ Nessun giorno sopra soglia nei prossimi 7 giorni.")

                    # Tabella previsioni con tipo evento
                    st.subheader("📋 Tabella previsioni (7 giorni)")
                    vista_fc = df_fc.copy()
                    vista_fc["Data"] = vista_fc["Data"].dt.strftime("%d-%m-%Y (%A)")
                    st.dataframe(vista_fc, use_container_width=True)

                    # Mappa + eventi
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("📍 Posizione")
                        m_fc = folium.Map(location=[lat, lon], zoom_start=11)
                        folium.Marker(
                            [lat, lon],
                            popup=f"{scelto.get('name','?')}: {len(eventi_fc)} giorni critici",
                            icon=folium.Icon(color="red" if not eventi_fc.empty else "green"),
                        ).add_to(m_fc)
                        st_folium(m_fc, width=500, height=400, key="mappa_previsioni")

                    with col2:
                        st.subheader("📊 Giorni critici previsti")
                        if not eventi_fc.empty:
                            vista_ev = eventi_fc.copy()
                            vista_ev["Data"] = vista_ev["Data"].dt.strftime("%d-%m-%Y")
                            st.dataframe(
                                vista_ev[["Data", "Pioggia (mm)", "Raffica Vento (km/h)", "Tipo"]],
                                use_container_width=True,
                            )
                        else:
                            st.info("Nessun giorno sopra soglia.")

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
                    csv_fc = df_fc.copy()
                    csv_fc["Data"] = csv_fc["Data"].dt.strftime("%Y-%m-%d")
                    st.download_button(
                        label="📥 Scarica previsioni in CSV",
                        data=csv_fc.to_csv(index=False).encode("utf-8"),
                        file_name=f"previsioni_{scelto.get('name','comune')}.csv",
                        mime="text/csv",
                    )
        except Exception as e:
            st.error(f"Errore tecnico nelle previsioni: {e}")
