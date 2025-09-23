
# 🎮 GAME BUS MTY — App de Operación & KPIs (Streamlit)

Esta app de **Streamlit** te permite operar y medir tu negocio *GAME BUS MTY* con las variables de tu Excel, además de una **Agenda** para tus eventos (nombre de la persona, dirección, costo, etc.).

## ¿Qué incluye?
- **Dashboard**: KPIs anuales, gráficas y tabla mensual calculada a partir de tu *Event_Log*, **Assumptions** y (si capturas) **Funnel** y **Ads**.
- **Eventos (captura)**: Formulario para registrar cada evento con precio, add-on de pizza, retro exterior, costo variable y notas. Se guarda en **Event_Log**.
- **Ads & Funnel**: Captura mensual con métricas derivadas automáticas (CTR, costo por mensaje; tasa de cierre).
- **Agenda**: Administra tus eventos con **Nombre, Dirección, Fecha, Hora y Costo**. Exporta a **.ics** para tu calendario y a **CSV**.
- **Configuración**: Edita tus **Assumptions** (precio promedio, costo variable por evento, gastos fijos mensuales, etc.).
- **Datos**: Visualiza y exporta cualquier hoja en Excel.

## Archivos
- `app.py`: la app de Streamlit lista para correr.
- `GameBus_DB.xlsx`: base de datos inicial (puedes seguir usándola y reemplazarla cuando quieras).
- `requirements.txt`: dependencias mínimas.
- Este README.

## Cómo correrla
1. Instala dependencias (recomendado entorno virtual):
   ```bash
   pip install -r requirements.txt
   ```
2. Ejecuta Streamlit:
   ```bash
   streamlit run app.py
   ```
3. La app usará el archivo `GameBus_DB.xlsx` en la misma carpeta. Puedes subir otro desde la **barra lateral** si así lo prefieres.

## Notas de cálculo
- **Monthly** se **calcula** a partir de *Event_Log* (conteo de eventos, ingresos, costos variables, adopción Retro, etc.) y de **Assumptions** (gastos fijos mensuales, costo variable default si falta capturarlo en algún evento).
- **Utilidad neta** = Ingresos − Costo variable − Gastos fijos + Margen Pizza.
- **ARPU real** = Ingresos / Eventos.
- **Reservas/Meta (%)** se aproxima como **Reservas confirmadas / Eventos** para tener referencia operativa; si prefieres usar una meta fija mensual, podemos ajustar.
- **Ads**: *Costo por mensaje* = Gasto Ads / Mensajes; *CTR* = Clics / Impresiones.
- **Funnel**: *Tasa de cierre* = Reservas confirmadas / Citas ofrecidas.

## Personalización
- ¿Quieres agregar más campos a la **Agenda** (ej. anticipo, tipo de paquete, ubicación GPS)? Se puede.
- ¿Te gustaría un **calendario visual** en la Agenda o recordatorios por WhatsApp/Email? Podemos integrarlo.
- Si prefieres que **Monthly** guarde también los valores calculados dentro del Excel, se puede habilitar un botón de “consolidar mes” para congelar cifras.

¡Lista para usarse! Si quieres que la deje corriendo en un servidor o la subamos a Streamlit Community Cloud, te paso los pasos.
