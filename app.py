import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Finanzas KOVA", page_icon="💰", layout="wide")

# --- 2. SISTEMA DE LOGIN PRIVADO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.title("🔒 Acceso Seguro")
    st.write("Ingresá tu PIN para acceder al gestor de gastos.")
    
    pin_ingresado = st.text_input("PIN de seguridad", type="password")
    if st.button("Entrar", type="primary"):
        # Compara lo ingresado con el PIN guardado en los Secrets (por defecto '1234')
        if pin_ingresado == str(st.secrets.get("APP_PIN", "1234")):
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.error("PIN incorrecto.")
            
    # El st.stop() es clave: frena la carga del resto del código si no estás logueado
    st.stop() 

# --- A PARTIR DE ACÁ, LA APP SOLO SE EJECUTA SI INICIASTE SESIÓN ---

# --- 3. CONFIGURACIÓN DE BASE DE DATOS SQLITE ---
def init_db():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS gastos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, monto REAL, categoria TEXT)''')
    conn.commit()
    conn.close()

def cargar_gastos():
    conn = sqlite3.connect('mis_gastos.db')
    df = pd.read_sql_query("SELECT item, monto, categoria FROM gastos", conn)
    conn.close()
    return df

def guardar_gastos(gastos_lista):
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    for g in gastos_lista:
        c.execute("INSERT INTO gastos (item, monto, categoria) VALUES (?, ?, ?)", (g['item'], g['monto'], g['categoria']))
    conn.commit()
    conn.close()

def limpiar_bd():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("DELETE FROM gastos")
    conn.commit()
    conn.close()

init_db()

# --- 4. ESQUEMA ESTRUCTURADO PARA GEMINI ---
class Gasto(BaseModel):
    item: str
    monto: float
    categoria: str

class ListaGastos(BaseModel):
    gastos: list[Gasto]

# --- 5. INTERFAZ PRINCIPAL ---
st.title("💰 Gestor de Gastos Diarios")

# Panel lateral simplificado (Sin API Key)
st.sidebar.header("Tus Finanzas")
ingreso_mensual = st.sidebar.number_input(
    "Ingreso Mensual ($)", min_value=0.0, value=0.0, step=10000.0, format="%f"
)

st.sidebar.markdown("---")
if st.sidebar.button("Limpiar todos los gastos"):
    limpiar_bd()
    st.rerun()
    
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.autenticado = False
    st.rerun()

gastos_texto = st.text_area(
    "Escribí tus gastos del día:",
    placeholder="Ej: Gasté $15.000 en el súper, $3.200 en transporte y $8.500 en una cena.",
    height=100,
)

if st.button("Procesar Gastos", type="primary"):
    if not gastos_texto.strip():
        st.warning("Escribí al menos un gasto para analizar.")
    else:
        try:
            # Lee la API Key oculta directamente desde Streamlit Secrets
            api_key = st.secrets["GEMINI_API_KEY"]
            client = genai.Client(api_key=api_key)
            
            prompt = f"""
            Analiza el siguiente texto e identifica todos los gastos realizados.
            Extrae el nombre del ítem/concepto, el monto numérico en formato flotante, 
            y clasifícalo en una categoría lógica (ej: Alimentos, Transporte, Salidas/Ocio, Servicios, Impuestos, Otros).
            Texto a analizar: "{gastos_texto}"
            """
            
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ListaGastos,
                    temperature=0.1,
                ),
            )
            
            texto_respuesta = str(response.text) if response.text else "{}"
            datos_gemini = ListaGastos.model_validate_json(texto_respuesta)
            nuevos_gastos = [gasto.model_dump() for gasto in datos_gemini.gastos]
            
            guardar_gastos(nuevos_gastos)
            st.success("¡Gastos procesados y guardados en la base de datos!")
            
        except Exception as e:
            st.error(f"Error al procesar con Gemini: {e}")

# --- 6. VISUALIZACIÓN DE RESULTADOS ---
df = cargar_gastos()
monto_total_gastos = float(df["monto"].sum()) if not df.empty else 0.0
saldo_restante = float(ingreso_mensual) - monto_total_gastos

st.markdown("---")
st.subheader("💵 Balance Actual")

col_met1, col_met2, col_met3 = st.columns(3)
col_met1.metric(label="Ingreso Mensual", value=f"${ingreso_mensual:,.2f}")
col_met2.metric(label="Total Gastado", value=f"${monto_total_gastos:,.2f}")

color_saldo = "normal" if saldo_restante >= 0 else "inverse"
col_met3.metric(
    label="Saldo Disponible", value=f"${saldo_restante:,.2f}", 
    delta=f"${saldo_restante:,.2f}", delta_color=color_saldo
)

if not df.empty:
    st.markdown("---")
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📊 Distribución por Categoría")
        df_agrupado = df.groupby("categoria", as_index=False)["monto"].sum()
        df_agrupado = df_agrupado.sort_values(by=["monto"], ascending=False)
        fig = px.pie(
            df_agrupado, values="monto", names="categoria", hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig.update_traces(
            textposition="inside", textinfo="percent+label",
            hovertemplate="%{label}: $%{value:,.2f}<br>%{percent}",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📋 Detalle de Gastos")
        st.dataframe(
            df,
            column_config={
                "item": "Concepto",
                "monto": st.column_config.NumberColumn("Monto ($)", format="$%.2f"),
                "categoria": "Categoría",
            },
            hide_index=True, use_container_width=True,
        )