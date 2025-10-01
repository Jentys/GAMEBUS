# GAME BUS MTY - Streamlit App
# FullCalendar + Map Picker + Orden meses + Casillas + Editor
# FIX v7.5 — dfs en session_state (consistencia), reload tras guardar, parsers robustos, IDs estables

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, time, timedelta
import json
import io
import os
from urllib.parse import quote_plus

# --- mapa opcional ---
HAS_MAP = True
try:
    from streamlit_folium import st_folium
    import folium, requests
except Exception:
    HAS_MAP = False

print(">> GAME BUS MTY app - FIX v7.5")

st.set_page_config(page_title="GAME BUS MTY", page_icon="🎮", layout="wide")

DB_PATH = "GameBus_DB.xlsx"

SPANISH_MONTHS = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
MONTH_NAME_MAP = {i+1: m for i, m in enumerate(SPANISH_MONTHS)}
APPLY_FIXED_FROM_MONTH = 10  # Octubre

# ---------- Helpers ----------
def normalize_df_for_streamlit(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if s.dtype == "O" and s.apply(lambda x: isinstance(x, (pd.Timestamp, datetime, date, np.datetime64))).any():
            out[col] = pd.to_datetime(s, errors="coerce")
        elif s.dtype == "O" and s.apply(lambda x: isinstance(x, (time,))).any():
            out[col] = s.astype(str)
    return out

def month_to_num(mes_str: str) -> int:
    try:
        return SPANISH_MONTHS.index(mes_str) + 1
    except Exception:
        return 0

# --- Parsers robustos para editor/agenda ---
def parse_date_any(x):
    if x is None or (isinstance(x, str) and not x.strip()):
        return None
    try:
        d = pd.to_datetime(x, errors="coerce")
        return d.date() if pd.notna(d) else None
    except Exception:
        return None

def parse_time_any(x):
    if x is None or (isinstance(x, str) and not x.strip()):
        return None
    if isinstance(x, time):
        return x
    try:
        t = pd.to_datetime(str(x), errors="coerce")
        return t.time() if pd.notna(t) else None
    except Exception:
        return None

def ensure_eventlog_columns(df: pd.DataFrame) -> pd.DataFrame:
    need_cols = [
        "ID","Fecha","Hora","Hora fin","Nombre","Dirección","Teléfono",
        "Colonia/Zona","Paquete","Precio (MXN)","Add-on Pizza (Sí/No)",
        "Margen Pizza (MXN)","Retro exterior (Sí/No)","Costo variable (MXN)","Notas","Estatus"
    ]
    for c in need_cols:
        if c not in df.columns:
            df[c] = np.nan

    # IDs estables (no reordenar ni reenumerar todo)
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce")
    if df["ID"].isna().all():
        df["ID"] = range(1, len(df)+1)
    else:
        max_id = int((df["ID"].max() or 0))
        # rellenar NaN con nuevos IDs
        nan_mask = df["ID"].isna()
        if nan_mask.any():
            new_ids = list(range(max_id+1, max_id+1+nan_mask.sum()))
            df.loc[nan_mask, "ID"] = new_ids
            max_id += nan_mask.sum()
        # duplicados: reasignar solo a los duplicados (excepto el primero)
        dups = df["ID"].duplicated(keep="first")
        if dups.any():
            for idx in np.where(dups)[0]:
                max_id += 1
                df.iat[idx, df.columns.get_loc("ID")] = max_id

    df["ID"] = df["ID"].astype(int)
    df["Estatus"] = df["Estatus"].fillna("Pendiente").replace({"": "Pendiente"})
    return df

def load_db(path=DB_PATH):
    if not os.path.exists(path):
        st.error("No se encontró la base de datos. Sube tu archivo o reinicia la app.")
        st.stop()
    xls = pd.ExcelFile(path)
    dfs = {name: pd.read_excel(path, sheet_name=name) for name in xls.sheet_names}
    for needed in ["Assumptions","Monthly","Ads","Funnel","Event_Log","Summary"]:
        if needed not in dfs:
            dfs[needed] = pd.DataFrame()
    dfs["Event_Log"] = ensure_eventlog_columns(dfs.get("Event_Log", pd.DataFrame()))
    return dfs

def save_db(dfs, path=DB_PATH):
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        for name, df in dfs.items():
            df.to_excel(writer, index=False, sheet_name=name)

def get_dfs():
    if "dfs" not in st.session_state:
        st.session_state["dfs"] = load_db()
    return st.session_state["dfs"]

def set_dfs(dfs):
    st.session_state["dfs"] = dfs

def reload_from_disk():
    set_dfs(load_db())

def get_assumption(dfs, var_name, default=0.0):
    df = dfs["Assumptions"]
    if "Variable" in df.columns and "Valor" in df.columns:
        match = df.loc[df["Variable"]==var_name, "Valor"]
        if not match.empty:
            try:
                return float(match.iloc[0])
            except:
                return default
    return default

def compute_ads_metrics(row):
    gasto = row.get("Gasto Ads (MXN)", 0) or 0
    impresiones = row.get("Impresiones", 0) or 0
    clicks = row.get("Clics", 0) or 0
    mensajes = row.get("Mensajes", 0) or 0
    row["Costo por mensaje (MXN)"] = (gasto / mensajes) if mensajes else 0
    row["CTR (%)"] = (clicks/impresiones*100) if impresiones else 0
    return row

def compute_funnel_metrics(row):
    mensajes = row.get("Mensajes", 0) or 0
    citas = row.get("Citas ofrecidas", 0) or 0
    reservas = row.get("Reservas confirmadas", 0) or 0
    row["Tasa de cierre (%)"] = (reservas / citas * 100) if citas else 0
    return row

def _combine_dt(fecha_val, hora_val, fallback="10:00"):
    f = pd.to_datetime(fecha_val, errors="coerce")
    if pd.isna(f):
        return None
    h_str = fallback
    if pd.notna(hora_val) and str(hora_val).strip():
        try:
            h_dt = pd.to_datetime(str(hora_val), errors="coerce")
            if pd.notna(h_dt):
                h_str = h_dt.strftime("%H:%M")
        except Exception:
            pass
    return datetime.combine(f.date(), datetime.strptime(h_str, "%H:%M").time())

def to_ics(df_events):
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//GAME BUS MTY//Agenda//ES"]
    for _, r in df_events.iterrows():
        dtstart = _combine_dt(r.get("Fecha"), r.get("Hora"), "10:00")
        if not dtstart:
            continue
        dtend = _combine_dt(r.get("Fecha"), r.get("Hora fin"), dtstart.strftime("%H:%M"))
        if not dtend or dtend <= dtstart:
            dtend = dtstart + timedelta(hours=2)

        uid = f"{dtstart.strftime('%Y%m%dT%H%M%S')}-gamebus@agenda"
        title = f"Evento: {r.get('Nombre','Cliente')} - ${r.get('Precio (MXN)',0):,.0f}"
        loc = r.get("Dirección","")
        desc_parts = []
        for key in ["Colonia/Zona","Paquete","Notas","Teléfono","Dirección"]:
            val = r.get(key, "")
            if pd.notna(val) and str(val).strip():
                desc_parts.append(f"{key}: {val}")
        desc = " | ".join(desc_parts)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{title}",
            f"LOCATION:{loc}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT"
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")

# ---------- Map Picker ----------
def reverse_geocode(lat: float, lon: float) -> str:
    try:
        headers = {"User-Agent": "GAMEBUS-MTY/1.0 (streamlit)"}
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1}
        r = requests.get(url, params=params, headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json().get("display_name", "")
    except Exception:
        pass
    return ""

# ---------- Cálculos ----------
def compute_monthly(dfs):
    base = pd.DataFrame({"Mes": SPANISH_MONTHS})
    for c in ["Eventos","Precio promedio (MXN)","Ingresos (MXN)","Costo variable (MXN)",
              "Gastos fijos (MXN)","Add-ons Pizza (#)","Margen Pizza (MXN)",
              "Utilidad neta (MXN)","ARPU real (MXN)","Reservas/Meta (%)","Adopción Retro (%)","Reseñas nuevas (#)"]:
        if c != "Mes":
            base[c] = 0.0
    base["Eventos"] = np.nan
    base["Precio promedio (MXN)"] = np.nan
    base["Add-ons Pizza (#)"] = np.nan

    costo_var_default = get_assumption(dfs, "Costo variable por evento (MXN)", 0)
    gasto_fijo_mensual = get_assumption(dfs, "Gastos fijos mensuales (MXN)", 0)

    ev_all = dfs["Event_Log"].copy()
    ev = ev_all[ev_all["Estatus"].str.lower() == "efectuado"].copy()

    if not ev.empty and "Fecha" in ev.columns:
        ev["Fecha"] = pd.to_datetime(ev["Fecha"], errors="coerce")
        ev["Mes"] = ev["Fecha"].dt.month.map(MONTH_NAME_MAP)
        addon = ev.get("Add-on Pizza (Sí/No)", pd.Series([False]*len(ev))).fillna(False)
        addon = addon.astype(str).str.strip().str.lower().isin(["si","sí","true","1","x","yes"])
        ev["Add-on Pizza (Sí/No)"] = addon
        retro = ev.get("Retro exterior (Sí/No)", pd.Series([False]*len(ev))).fillna(False)
        retro = retro.astype(str).str.strip().str.lower().isin(["si","sí","true","1","x","yes"])
        ev["Retro exterior (Sí/No)"] = retro

        grp = ev.groupby("Mes", dropna=False)
        agg = grp.agg({
            "Precio (MXN)": ["count","mean","sum"],
            "Costo variable (MXN)": "sum",
            "Add-on Pizza (Sí/No)": "sum",
            "Margen Pizza (MXN)": "sum",
            "Retro exterior (Sí/No)": "mean"
        })
        agg.columns = ["Eventos","Precio promedio (MXN)","Ingresos (MXN)",
                       "Costo variable (MXN)","Add-ons Pizza (#)","Margen Pizza (MXN)",
                       "Adopción Retro (%)"]
        agg = agg.reset_index()

        if "Costo variable (MXN)" in ev.columns:
            ev["_cv_missing"] = ev["Costo variable (MXN)"].isna().astype(int)
            miss = ev.groupby("Mes")["_cv_missing"].sum().reindex(SPANISH_MONTHS).fillna(0).values
            for i, m in enumerate(SPANISH_MONTHS):
                if m in list(agg["Mes"]):
                    idx = agg.index[agg["Mes"]==m][0]
                    agg.loc[idx, "Costo variable (MXN)"] = float(agg.loc[idx, "Costo variable (MXN)"] or 0) + miss[i]*costo_var_default

        if "Adopción Retro (%)" in agg.columns:
            agg["Adopción Retro (%)"] = (agg["Adopción Retro (%)"]*100).round(2)

        overlap_cols = ["Eventos","Precio promedio (MXN)","Ingresos (MXN)","Costo variable (MXN)",
                        "Add-ons Pizza (#)","Margen Pizza (MXN)","Adopción Retro (%)"]
        base = base.drop(columns=[c for c in overlap_cols if c in base.columns], errors="ignore")
        base = base.merge(agg, on="Mes", how="left")

    for c in ["Eventos","Precio promedio (MXN)","Ingresos (MXN)","Costo variable (MXN)",
              "Add-ons Pizza (#)","Margen Pizza (MXN)","Adopción Retro (%)"]:
        if c not in base.columns:
            base[c] = 0
        base[c] = base[c].fillna(0)

    base["Gastos fijos (MXN)"] = 0.0
    base["_num"] = base["Mes"].apply(month_to_num)
    base.loc[base["_num"] >= APPLY_FIXED_FROM_MONTH, "Gastos fijos (MXN)"] = float(gasto_fijo_mensual)

    base["Utilidad neta (MXN)"] = base["Ingresos (MXN)"] - base["Costo variable (MXN)"] - base["Gastos fijos (MXN)"] + base["Margen Pizza (MXN)"]
    base["ARPU real (MXN)"] = np.where(base["Eventos"]>0, base["Ingresos (MXN)"]/base["Eventos"], 0)

    funnel = dfs.get("Funnel", pd.DataFrame())
    if not funnel.empty and "Mes" in funnel.columns and "Reservas confirmadas" in funnel.columns:
        tmp = funnel[["Mes","Reservas confirmadas"]].copy()
        tmp.rename(columns={"Reservas confirmadas":"_Reservas"}, inplace=True)
        base = base.merge(tmp, on="Mes", how="left")
        base["Reservas/Meta (%)"] = np.where(base["Eventos"]>0, (base["_Reservas"]/base["Eventos"]*100), 0)
        base.drop(columns=["_Reservas"], inplace=True)
    else:
        base["Reservas/Meta (%)"] = 0

    if "Monthly" in dfs and not dfs["Monthly"].empty and "Reseñas nuevas (#)" in dfs["Monthly"].columns:
        rese_map = dfs["Monthly"].set_index("Mes")["Reseñas nuevas (#)"]
        base["Reseñas nuevas (#)"] = base["Mes"].map(rese_map).fillna(base.get("Reseñas nuevas (#)", 0)).fillna(0)
    else:
        if "Reseñas nuevas (#)" not in base.columns:
            base["Reseñas nuevas (#)"] = 0

    for c in ["Precio promedio (MXN)","Ingresos (MXN)","Costo variable (MXN)","Gastos fijos (MXN)","Margen Pizza (MXN)","Utilidad neta (MXN)","ARPU real (MXN)"]:
        base[c] = base[c].round(2)
    for c in ["Reservas/Meta (%)","Adopción Retro (%)","Reseñas nuevas (#)"]:
        base[c] = base[c].round(2)

    base["Mes"] = pd.Categorical(base["Mes"], categories=SPANISH_MONTHS, ordered=True)
    base = base.sort_values("Mes")
    ordered = ["Mes","Eventos","Precio promedio (MXN)","Ingresos (MXN)","Costo variable (MXN)",
               "Gastos fijos (MXN)","Add-ons Pizza (#)","Margen Pizza (MXN)","Utilidad neta (MXN)",
               "ARPU real (MXN)","Reservas/Meta (%)","Adopción Retro (%)","Reseñas nuevas (#)"]
    base = base[[c for c in ordered if c in base.columns]]
    return base

def kpi_summary(monthly_df):
    cur_m = datetime.now().month
    df = monthly_df.copy()
    df["_num"] = df["Mes"].apply(month_to_num)
    df = df[df["_num"] <= cur_m]
    eventos = df["Eventos"].sum()
    ingresos = df["Ingresos (MXN)"].sum()
    utilidad = df["Utilidad neta (MXN)"].sum()
    return eventos, ingresos, utilidad

# ---------- FullCalendar ----------
def build_fullcalendar_html(events_json, initial_date=None):
    init_date_js = f"initialDate: '{initial_date}'," if initial_date else ""
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
  <style>
    html, body {{ margin:0; padding:0; }}
    body {{ font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }}
    #calendar {{ max-width: 1100px; margin: 0 auto; }}
    .fc .fc-toolbar-title {{ font-weight: 700; }}
    .fc .fc-event {{ border: none; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
    #popover {{
      position: absolute; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.25); padding: 14px; width: 420px; z-index: 999999;
      display:none;
    }}
    #popover h4 {{ margin: 0 0 6px 0; font-size: 16px; }}
    #popover p {{ margin: 4px 0; font-size: 13px; color: #374151; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; background:#eee; }}
    .mapbox {{ margin-top: 8px; width: 100%; height: 220px; border:0; border-radius: 10px; }}
    .btns a {{ margin-right: 8px; font-size: 12px; text-decoration:none; }}
  </style>
</head>
<body>
  <div id="calendar"></div>
  <div id="popover"></div>

  <script>
    const events = {events_json};

    function hidePopover() {{
      const p = document.getElementById('popover');
      p.style.display = 'none';
    }}

    document.addEventListener('click', function(e) {{
      const p = document.getElementById('popover');
      if (!p.contains(e.target)) hidePopover();
    }});

    document.addEventListener('DOMContentLoaded', function() {{
      const calendarEl = document.getElementById('calendar');
      const calendar = new FullCalendar.Calendar(calendarEl, {{
        {init_date_js}
        headerToolbar: {{
          left: 'prev,next today',
          center: 'title',
          right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek'
        }},
        initialView: 'dayGridMonth',
        navLinks: true,
        selectable: false,
        nowIndicator: true,
        firstDay: 1,
        businessHours: {{
          daysOfWeek: [ 1, 2, 3, 4, 5, 6, 0 ],
          startTime: '08:00',
          endTime: '22:00'
        }},
        height: 740,
        eventTimeFormat: {{ hour: '2-digit', minute: '2-digit', hour12: false }},
        events: events,
        eventClick: function(info) {{
          const e = info.event;
          const p = document.getElementById('popover');
          const props = e.extendedProps || {{}};
          const hora = e.start ? e.start.toLocaleTimeString('es-MX', {{hour:'2-digit', minute:'2-digit'}}) : '';
          const horaFin = e.end ? e.end.toLocaleTimeString('es-MX', {{hour:'2-digit', minute:'2-digit'}}) : '';
          const paquete = props.paquete || '';
          const dir = props.direccion || '';
          const mapSrc = dir ? 'https://www.google.com/maps?q=' + encodeURIComponent(dir) + '&output=embed' : '';
          const tel = props.telefono || '';
          const telHref = tel ? 'tel:' + tel : null;
          const mapsHref = dir ? 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(dir) : null;

          p.innerHTML = `
            <h4>${{e.title}}</h4>
            <p><strong>Tipo de servicio:</strong> <span class="badge">${{paquete}}</span></p>
            <p><strong>Hora del servicio:</strong> ${{hora}} ${{horaFin ? '— ' + horaFin : ''}}</p>
            ${{ dir ? `<p><strong>Dirección:</strong> ${{dir}}</p>` : '' }}
            ${{ mapSrc ? `<iframe class="mapbox" loading="lazy" referrerpolicy="no-referrer-when-downgrade" src="${{mapSrc}}"></iframe>` : '' }}
            <div class="btns" style="margin-top:8px;">
              ${{ mapsHref ? `<a href="${{mapsHref}}" target="_blank">🗺️ Abrir en Maps</a>` : '' }}
              ${{ telHref ? `<a href="${{telHref}}">📞 Llamar</a>` : '' }}
            </div>
          `;
          const x = info.jsEvent.clientX + window.scrollX + 16;
          const y = info.jsEvent.clientY + window.scrollY + 16;
          p.style.left = x + 'px';
          p.style.top = y + 'px';
          p.style.display = 'block';
          info.jsEvent.preventDefault();
          info.jsEvent.stopPropagation();
        }},
        dateClick: function() {{ hidePopover(); }}
      }});
      calendar.render();
    }});
  </script>
</body>
</html>
"""
    return html

def events_to_fullcalendar(ev_df):
    if ev_df.empty:
        return []
    df = ev_df.copy()
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

    def build_iso(row):
        d = row["Fecha"]
        if pd.isna(d):
            return None, None
        start_dt = _combine_dt(d, row.get("Hora"), "10:00")
        if not start_dt:
            return None, None
        end_dt = _combine_dt(d, row.get("Hora fin"), start_dt.strftime("%H:%M"))
        if (not end_dt) or end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=2)
        return start_dt.strftime("%Y-%m-%dT%H:%M:%S"), end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    events = []
    for _, r in df.iterrows():
        start, end = build_iso(r)
        if not start:
            continue
        title = r.get("Nombre") or r.get("Colonia/Zona") or "Evento"
        def color_for(paquete, estatus):
            p = str(paquete or "").strip().lower()
            if str(estatus).lower() == "pendiente":
                return "#3b82f6"
            if "retro" in p and "clásico" in p: return "#7c3aed"
            if "retro" in p: return "#ef4444"
            if "clásico" in p: return "#10b981"
            return "#6b7280"

        events.append({
            "title": f"{title} ({r.get('Estatus','Pendiente')})",
            "start": start,
            "end": end,
            "color": color_for(r.get("Paquete"), r.get("Estatus")),
            "extendedProps": {
                "paquete": r.get("Paquete", ""),
                "direccion": r.get("Dirección", ""),
                "telefono": r.get("Teléfono", ""),
                "notas": r.get("Notas", "")
            }
        })
    return events

# ---------- UI ----------
st.title("🎮 GAME BUS MTY - PERFORMANCE APP")

# Sidebar
with st.sidebar:
    st.header("Base de datos")
    uploaded = st.file_uploader("Subir base (GameBus_DB.xlsx)", type=["xlsx"], accept_multiple_files=False)
    if uploaded:
        with open(DB_PATH, "wb") as f:
            f.write(uploaded.read())
        st.success("Base actualizada desde archivo subido.")
        reload_from_disk()

    dfs = get_dfs()
    if st.button("💾 Guardar ahora"):
        save_db(dfs); st.success("Base guardada.")

    if st.button("⬇️ Exportar Excel completo"):
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
            for name, df in dfs.items():
                df.to_excel(writer, index=False, sheet_name=name)
        st.download_button("Descargar GameBus_DB.xlsx", data=bio.getvalue(),
                           file_name="GameBus_DB.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

tabs = st.tabs(["📊 Dashboard","📒 Eventos (captura)","🗓️ Agenda (calendario)","📣 Ads & Funnel","⚙️ Configuración","🗃️ Datos"])

# --- Dashboard ---
with tabs[0]:
    dfs = get_dfs()
    st.subheader("KPIs del año (hasta mes actual, solo Efectuados)")
    monthly = compute_monthly(dfs)
    monthly["Mes"] = pd.Categorical(monthly["Mes"], categories=SPANISH_MONTHS, ordered=True)
    monthly = monthly.sort_values("Mes")
    e,i,u = kpi_summary(monthly)
    c1,c2,c3 = st.columns(3)
    c1.metric("Eventos totales", int(e))
    c2.metric("Ingresos totales (MXN)", f"{i:,.0f}")
    c3.metric("Utilidad neta (MXN)", f"{u:,.0f}")

    st.markdown("---")
    idx = monthly.set_index("Mes").reindex(SPANISH_MONTHS).fillna(0)
    st.bar_chart(idx[["Eventos"]])
    st.bar_chart(idx[["Ingresos (MXN)"]])
    st.bar_chart(idx[["Utilidad neta (MXN)"]])

    st.markdown("### Tabla mensual (calculada)")
    st.dataframe(normalize_df_for_streamlit(monthly), use_container_width=True)

# --- Eventos (captura) ---
with tabs[1]:
    dfs = get_dfs()
    st.subheader("Captura de evento (única fuente de verdad)")
    st.caption("Esto alimenta KPIs (solo cuando marques 'Efectuado') y también la Agenda.")

    # Buffers
    if "direccion_input" not in st.session_state:
        st.session_state["direccion_input"] = ""
    if "last_map_center" not in st.session_state:
        st.session_state["last_map_center"] = [25.6866, -100.3161]  # Monterrey

    c1,c2,c3 = st.columns(3)
    with c1:
        fecha = st.date_input("Fecha", value=date.today())
        hora = st.time_input("Hora", value=time(10,0))
        default_fin = (datetime.combine(date.today(), hora) + timedelta(hours=2)).time()
        hora_fin = st.time_input("Hora fin", value=default_fin)
        nombre = st.text_input("Nombre de la persona/cliente")
        colonia = st.text_input("Colonia/Zona")
    with c2:
        with st.expander("📍 Seleccionar en mapa (click para autollenar Dirección)", expanded=False):
            if HAS_MAP:
                m = folium.Map(location=st.session_state["last_map_center"], zoom_start=11, control_scale=True)
                folium.LatLngPopup().add_to(m)
                out = st_folium(m, height=380, width=None)
                if out and out.get("last_clicked"):
                    lat = out["last_clicked"]["lat"]; lon = out["last_clicked"]["lng"]
                    st.session_state["last_map_center"] = [lat, lon]
                    st.info(f"Coordenadas: {lat:.6f}, {lon:.6f}")
                    addr = reverse_geocode(lat, lon)
                    if addr:
                        st.session_state["direccion_input"] = addr
                        st.success("Dirección autollenada desde el mapa ✅")
                        st.rerun()
                    else:
                        st.warning("No se pudo obtener la dirección (sin internet o servicio ocupado).")
            else:
                st.warning("Para usar el selector de mapa instala: pip install streamlit-folium folium requests")

        direccion_default = st.session_state.get("direccion_input", "")
        direccion = st.text_input("Dirección", value=direccion_default)

        if direccion.strip():
            maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(direccion.strip())}"
            st.markdown(f"[🗺️ Abrir en Google Maps]({maps_url})", unsafe_allow_html=True)

        telefono = st.text_input("Teléfono (opcional)")
        paquete = st.selectbox("Paquete", ["Clásico","Retro","Clásico + Retro","Otro"])
        retroext = st.checkbox("Retro exterior (Sí)")
    with c3:
        precio = st.number_input("Precio (MXN)", min_value=0, step=50)
        add_on = st.checkbox("Add-on Pizza (Sí)")
        margen_pizza = st.number_input("Margen Pizza (MXN)", min_value=0, step=10)
        costo_var_default = get_assumption(dfs, "Costo variable por evento (MXN)", 0)
        costo_var = st.number_input("Costo variable (MXN)", min_value=0, step=10, value=int(costo_var_default))
        notas = st.text_area("Notas")
        estatus_new = st.selectbox("Estatus del evento", ["Pendiente","Efectuado"], index=0)

    if st.button("➕ Guardar evento"):
        next_id = int(dfs["Event_Log"]["ID"].max()) + 1 if len(dfs["Event_Log"]) else 1
        new_row = {
            "ID": next_id,
            "Fecha": fecha, "Hora": hora, "Hora fin": hora_fin,
            "Nombre": nombre, "Dirección": direccion, "Teléfono": telefono,
            "Colonia/Zona": colonia, "Paquete": paquete,
            "Precio (MXN)": precio, "Add-on Pizza (Sí/No)": "Sí" if add_on else "No",
            "Margen Pizza (MXN)": margen_pizza, "Retro exterior (Sí/No)": "Sí" if retroext else "No",
            "Costo variable (MXN)": costo_var, "Notas": notas,
            "Estatus": estatus_new
        }
        # Actualiza session + disco
        dfs["Event_Log"] = pd.concat([dfs["Event_Log"], pd.DataFrame([new_row])], ignore_index=True)
        dfs["Event_Log"] = ensure_eventlog_columns(dfs["Event_Log"])
        save_db(dfs)
        set_dfs(dfs)
        st.success("Evento guardado.")
        st.session_state["direccion_input"] = ""
        # Recarga desde disco para evitar cualquier incoherencia de tipos
        reload_from_disk()
        st.rerun()

    st.markdown("### Historial / Lista de eventos (con casillas)")
    dfs = get_dfs()
    listado = dfs["Event_Log"].copy()
    if not listado.empty:
        listado["Fecha"]    = listado["Fecha"].apply(parse_date_any)
        listado["Hora"]     = listado["Hora"].apply(parse_time_any)
        listado["Hora fin"] = listado["Hora fin"].apply(parse_time_any)
        listado["Mes"] = pd.Series(listado["Fecha"]).apply(lambda d: MONTH_NAME_MAP.get(d.month, "") if d else "")

        colf1, colf2 = st.columns([2,1])
        with colf1:
            month_filter = st.multiselect("Mes", SPANISH_MONTHS, default=SPANISH_MONTHS)
        with colf2:
            est_filter = st.multiselect("Estatus", ["Pendiente","Efectuado"], default=["Pendiente","Efectuado"])

        listado = listado[listado["Mes"].isin(month_filter) & listado["Estatus"].isin(est_filter)]
        listado = listado.sort_values(["Fecha","Hora"], ascending=True, na_position="last")

        listado = listado[[
            "ID","Fecha","Hora","Hora fin","Estatus","Nombre","Dirección","Teléfono","Colonia/Zona","Paquete",
            "Precio (MXN)","Add-on Pizza (Sí/No)","Retro exterior (Sí/No)","Costo variable (MXN)","Notas"
        ]].copy()
        listado["Seleccionar"] = False

        edited = st.data_editor(
            listado,
            use_container_width=True,
            num_rows="fixed",
            column_config={
                "Seleccionar": st.column_config.CheckboxColumn("✓"),
                "Fecha": st.column_config.DateColumn("Fecha"),
                "Hora": st.column_config.TimeColumn("Hora", step=60),
                "Hora fin": st.column_config.TimeColumn("Hora fin", step=60),
            },
            hide_index=True
        )

        sel_ids = edited.loc[edited["Seleccionar"] == True, "ID"].astype(int).tolist()

        ac1, ac2, ac3, ac4 = st.columns(4)
        with ac1:
            if st.button("✅ Marcar como Efectuado"):
                if sel_ids:
                    dfs["Event_Log"].loc[dfs["Event_Log"]["ID"].isin(sel_ids), "Estatus"] = "Efectuado"
                    save_db(dfs); set_dfs(dfs); st.success("Marcado como Efectuado.")
                    reload_from_disk(); st.rerun()
                else:
                    st.warning("Selecciona al menos un evento.")
        with ac2:
            if st.button("⏳ Marcar como Pendiente"):
                if sel_ids:
                    dfs["Event_Log"].loc[dfs["Event_Log"]["ID"].isin(sel_ids), "Estatus"] = "Pendiente"
                    save_db(dfs); set_dfs(dfs); st.success("Marcado como Pendiente.")
                    reload_from_disk(); st.rerun()
                else:
                    st.warning("Selecciona al menos un evento.")
        with ac3:
            if st.button("🗑️ Borrar seleccionados"):
                if sel_ids:
                    dfs["Event_Log"] = dfs["Event_Log"][~dfs["Event_Log"]["ID"].isin(sel_ids)].reset_index(drop=True)
                    save_db(dfs); set_dfs(dfs); st.success("Evento(s) borrado(s).")
                    reload_from_disk(); st.rerun()
                else:
                    st.warning("Selecciona al menos un evento.")
        with ac4:
            if st.button("✏️ Editar seleccionado"):
                if len(sel_ids) == 1:
                    st.session_state["edit_id"] = sel_ids[0]
                else:
                    st.warning("Selecciona exactamente 1 evento para editar.")

        if "edit_id" in st.session_state:
            eid = st.session_state["edit_id"]
            st.markdown("---")
            st.subheader(f"Editar evento ID #{eid}")
            row = dfs["Event_Log"].loc[dfs["Event_Log"]["ID"]==eid].iloc[0]
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                e_fecha = st.date_input("Fecha (edit)", value=parse_date_any(row["Fecha"]) or date.today(), key="e_fecha")
                e_hora  = st.time_input("Hora (edit)",  value=parse_time_any(row["Hora"]) or time(10,0), key="e_hora")
                raw_fin = parse_time_any(row.get("Hora fin"))
                e_hora_fin = st.time_input("Hora fin (edit)", value=raw_fin or (datetime.combine(date.today(), e_hora)+timedelta(hours=2)).time(), key="e_hora_fin")
                e_nombre = st.text_input("Nombre (edit)", value=row.get("Nombre",""), key="e_nombre")
                e_colonia = st.text_input("Colonia/Zona (edit)", value=row.get("Colonia/Zona",""), key="e_colonia")
            with ec2:
                e_dir = st.text_input("Dirección (edit)", value=row.get("Dirección",""), key="e_dir")
                e_tel = st.text_input("Teléfono (edit)", value=row.get("Teléfono","") if pd.notna(row.get("Teléfono","")) else "", key="e_tel")
                e_paquete = st.selectbox("Paquete (edit)", ["Clásico","Retro","Clásico + Retro","Otro"],
                                         index=0 if str(row.get("Paquete",""))=="" else ["Clásico","Retro","Clásico + Retro","Otro"].index(str(row.get("Paquete",""))), key="e_paquete")
                e_retro = st.checkbox("Retro exterior (Sí) (edit)",
                                      value=str(row.get("Retro exterior (Sí/No)","No")).lower() in ["si","sí","true","1","x","yes"], key="e_retro")
            with ec3:
                e_precio = st.number_input("Precio (MXN) (edit)", min_value=0, step=50, value=int(row.get("Precio (MXN)",0) or 0), key="e_precio")
                e_addon = st.checkbox("Add-on Pizza (Sí) (edit)", value=str(row.get("Add-on Pizza (Sí/No)","No")).lower() in ["si","sí","true","1","x","yes"], key="e_addon")
                e_margen = st.number_input("Margen Pizza (MXN) (edit)", min_value=0, step=10, value=int(row.get("Margen Pizza (MXN)",0) or 0), key="e_margen")
                e_cv = st.number_input("Costo variable (MXN) (edit)", min_value=0, step=10, value=int(row.get("Costo variable (MXN)",0) or 0), key="e_cv")
                e_notas = st.text_area("Notas (edit)", value=row.get("Notas",""), key="e_notas")
                e_status = st.selectbox("Estatus (edit)", ["Pendiente","Efectuado"],
                                        index=0 if str(row.get("Estatus","Pendiente"))=="Pendiente" else 1, key="e_status")

            if st.button("💾 Guardar cambios"):
                mask = dfs["Event_Log"]["ID"]==eid
                dfs["Event_Log"].loc[mask, ["Fecha","Hora","Hora fin","Nombre","Dirección","Teléfono","Colonia/Zona","Paquete","Precio (MXN)",
                                             "Add-on Pizza (Sí/No)","Margen Pizza (MXN)","Retro exterior (Sí/No)",
                                             "Costo variable (MXN)","Notas","Estatus"]] = [
                    e_fecha, e_hora, e_hora_fin, e_nombre, e_dir, e_tel, e_colonia, e_paquete, e_precio,
                    "Sí" if e_addon else "No", e_margen, "Sí" if e_retro else "No",
                    e_cv, e_notas, e_status
                ]
                save_db(dfs); set_dfs(dfs)
                st.success("Cambios guardados.")
                del st.session_state["edit_id"]
                reload_from_disk(); st.rerun()

        # CSV solo lee la vista tipada; NO toca la base
        ev_csv = listado.drop(columns=["Seleccionar"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar CSV de eventos", data=ev_csv, file_name="eventos.csv", mime="text/csv")
    else:
        st.info("Aún no hay eventos registrados.")

# --- Agenda (FullCalendar) ---
with tabs[2]:
    dfs = get_dfs()
    st.subheader("Agenda (estilo Google Calendar)")
    st.caption("Se construye desde 📒 Eventos. Click para ver datos y mapa.")
    ev = dfs["Event_Log"].copy()
    if ev.empty:
        st.info("Sin eventos aún. Captura en la pestaña 📒 Eventos.")
    else:
        fullcal_events = events_to_fullcalendar(ev)
        events_json = json.dumps(fullcal_events, ensure_ascii=False)
        today_str = datetime.now().strftime("%Y-%m-%d")
        html = build_fullcalendar_html(events_json, initial_date=today_str)
        try:
            st.components.v1.html(html, height=860, scrolling=True)
        except Exception:
            st.warning("No se pudo cargar el calendario (CDN de FullCalendar). Mostrando tabla.")
            ev["Fecha"] = pd.to_datetime(ev["Fecha"], errors="coerce")
            st.dataframe(normalize_df_for_streamlit(ev.sort_values(["Fecha","Hora"])), use_container_width=True)

        ics_bytes = to_ics(ev)
        st.download_button("📆 Exportar .ics (todos)", data=ics_bytes, file_name=f"agenda_completa.ics", mime="text/calendar")

# --- Ads & Funnel ---
with tabs[3]:
    dfs = get_dfs()
    st.subheader("Ads & Funnel")
    st.caption("Captura mensual y métricas derivadas.")
    with st.expander("📣 Ads", True):
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            mes_sel = st.selectbox("Mes", SPANISH_MONTHS, index=datetime.now().month-1, key="ads_mes")
            gasto = st.number_input("Gasto Ads (MXN)", min_value=0, step=50)
            impresiones = st.number_input("Impresiones", min_value=0, step=100)
            clicks = st.number_input("Clics", min_value=0, step=10)
            mensajes = st.number_input("Mensajes", min_value=0, step=1)
            if st.button("💾 Guardar Ads"):
                df = dfs["Ads"].copy()
                if "Mes" not in df.columns:
                    df = pd.DataFrame({"Mes": SPANISH_MONTHS})
                row = {"Mes": mes_sel, "Gasto Ads (MXN)": gasto, "Impresiones": impresiones, "Clics": clicks, "Mensajes": mensajes}
                row = compute_ads_metrics(row)
                if "Mes" in df and mes_sel in df["Mes"].values:
                    df.loc[df["Mes"]==mes_sel, list(row.keys())] = list(row.values())
                else:
                    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
                dfs["Ads"] = df
                save_db(dfs); set_dfs(dfs)
                st.success("Ads actualizado.")
        with mcol2:
            df = dfs["Ads"].copy()
            if not df.empty:
                df = df.apply(compute_ads_metrics, axis=1)
                st.dataframe(normalize_df_for_streamlit(df), use_container_width=True)
            else:
                st.info("Sin datos de Ads aún.")

    with st.expander("🔁 Funnel", True):
        fcol1, fcol2 = st.columns(2)
        with fcol1:
            mes_f = st.selectbox("Mes (Funnel)", SPANISH_MONTHS, index=datetime.now().month-1, key="funnel_mes")
            f_mensajes = st.number_input("Mensajes", min_value=0, step=1, key="f_mensajes")
            citas = st.number_input("Citas ofrecidas", min_value=0, step=1)
            reservas = st.number_input("Reservas confirmadas", min_value=0, step=1)
            if st.button("💾 Guardar Funnel"):
                df = dfs["Funnel"].copy()
                if "Mes" not in df.columns:
                    df = pd.DataFrame({"Mes": SPANISH_MONTHS})
                row = {"Mes": mes_f, "Mensajes": f_mensajes, "Citas ofrecidas": citas, "Reservas confirmadas": reservas}
                row = compute_funnel_metrics(row)
                if "Mes" in df and mes_f in df["Mes"].values:
                    df.loc[df["Mes"]==mes_f, list(row.keys())] = list(row.values())
                else:
                    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
                dfs["Funnel"] = df
                save_db(dfs); set_dfs(dfs)
                st.success("Funnel actualizado.")
        with fcol2:
            df = dfs["Funnel"].copy()
            if not df.empty:
                df = df.apply(compute_funnel_metrics, axis=1)
                st.dataframe(normalize_df_for_streamlit(df), use_container_width=True)
            else:
                st.info("Sin datos de Funnel aún.")

# --- Configuración ---
with tabs[4]:
    dfs = get_dfs()
    st.subheader("Assumptions (editar)")
    assum = dfs["Assumptions"].copy()
    st.caption("Edita los valores y presiona Guardar para aplicar.")
    edited = st.data_editor(assum, use_container_width=True, num_rows="dynamic")
    if st.button("💾 Guardar Assumptions"):
        dfs["Assumptions"] = edited
        save_db(dfs); set_dfs(dfs)
        st.success("Assumptions guardado.")

# --- Datos (ver/exportar) ---
with tabs[5]:
    dfs = get_dfs()
    st.subheader("Hojas de la base de datos")
    for name in ["Monthly","Event_Log","Ads","Funnel","Summary"]:
        st.markdown(f"#### {name}")
        if name not in dfs:
            st.info("No existe aún.")
            continue
        df = dfs[name].copy()
        st.dataframe(normalize_df_for_streamlit(df), use_container_width=True)
        xls_bytes = io.BytesIO()
        with pd.ExcelWriter(xls_bytes, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name=name)
        st.download_button(f"⬇️ Descargar {name}.xlsx", data=xls_bytes.getvalue(),
                           file_name=f"{name}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.caption("GAME BUS MTY V.2025 — v7.5 (session_state DFS + reload inmediato)")
