import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel
from datetime import datetime, timedelta

st.set_page_config(page_title="Finanzas KOVA", page_icon="💰", layout="wide")

# --- CSS: ESTILO UI/UX "VICTOR GAS" ---
st.markdown("""
    <style>
        /* Tarjetas con bordes redondeados y sombras suaves */
        div[data-testid="stVerticalBlock"] > div[style*="border"] {
            border-radius: 16px !important;
            border: 1px solid #E5E7EB !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
            padding: 16px;
            background-color: #FFFFFF;
        }
        /* Botones principales estilo marca */
        .stButton>button {
            border-radius: 12px;
            font-weight: 600;
            background-color: #FFC700;
            color: #1A1A1A;
            border: none;
        }
        .stButton>button:hover {
            background-color: #E5B200;
            color: #000000;
        }
    </style>
""", unsafe_allow_html=True)

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.title("🔒 Acceso Seguro")
    st.write("Ingresá tu PIN para acceder al gestor de gastos.")
    
    pin_ingresado = st.text_input("PIN de seguridad", type="password")
    if st.button("Entrar", type="primary"):
        if pin_ingresado == str(st.secrets.get("APP_PIN", "1234")):
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.error("PIN incorrecto.")
    st.stop() 

def init_db():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS gastos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, monto REAL, categoria TEXT)''')
    
    c.execute("PRAGMA table_info(gastos)")
    columnas = [columna[1] for columna in c.fetchall()]
    if 'fecha' not in columnas:
        c.execute("ALTER TABLE gastos ADD COLUMN fecha TEXT DEFAULT ''")
        
    c.execute('''CREATE TABLE IF NOT EXISTS configuracion
                 (id INTEGER PRIMARY KEY, ingreso_mensual REAL)''')
    
    c.execute("SELECT COUNT(*) FROM configuracion")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO configuracion (id, ingreso_mensual) VALUES (1, 0.0)")
        
    conn.commit()
    conn.close()

def cargar_ingreso():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("SELECT ingreso_mensual FROM configuracion WHERE id=1")
    resultado = c.fetchone()
    conn.close()
    return resultado[0] if resultado else 0.0

def guardar_ingreso(monto):
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("UPDATE configuracion SET ingreso_mensual = ? WHERE id=1", (monto,))
    conn.commit()
    conn.close()

def cargar_gastos():
    conn = sqlite3.connect('mis_gastos.db')
    df = pd.read_sql_query("SELECT fecha, item, monto, categoria FROM gastos", conn)
    conn.close()
    return df

def guardar_gastos(gastos_lista):
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    fecha_actual = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y")
    
    for g in gastos_lista:
        c.execute("INSERT INTO gastos (item, monto, categoria, fecha) VALUES (?, ?, ?, ?)", 
                  (g['item'], g['monto'], g['categoria'], fecha_actual))
    conn.commit()
    conn.close()

def limpiar_bd():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("DELETE FROM gastos")
    conn.commit()
    conn.close()

init_db()

class Gasto(BaseModel):
    item: str
    monto: float
    categoria: str

class ListaGastos(BaseModel):
    gastos: list[Gasto]

st.title("💰 Gestor de Gastos Diarios")

st.sidebar.header("Tus Finanzas")

ingreso_guardado = cargar_ingreso()
ingreso_mensual = st.sidebar.number_input(
    "Ingreso Mensual ($)", 
    min_value=0.0, 
    value=float(ingreso_guardado), 
    step=10000.0, 
    format="%f"
)

if ingreso_mensual != ingreso_guardado:
    guardar_ingreso(ingreso_mensual)

st.sidebar.markdown("---")

df = cargar_gastos()
df_mostrar = df.copy()

if not df.empty:
    df['fecha_dt'] = pd.to_datetime(df['fecha'], format='%d/%m/%Y', errors='coerce')
    df['fecha_dt'] = df['fecha_dt'].fillna(datetime.utcnow() - timedelta(hours=3))
    
    nombres_meses = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
                     7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}
    
    df['Mes_Anio'] = df['fecha_dt'].dt.month.map(nombres_meses) + " " + df['fecha_dt'].dt.year.astype(str)
    df = df.sort_values(by='fecha_dt', ascending=False)
    meses_disponibles = df['Mes_Anio'].unique().tolist()
    
    mes_seleccionado = st.sidebar.selectbox("📅 Historial de gastos:", meses_disponibles)
    df_mostrar = df[df['Mes_Anio'] == mes_seleccionado]

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
            # Volvemos a usar la API Key de Gemini que ya tenías en Streamlit Secrets
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
            st.success("¡Gastos procesados y guardados con éxito!")
            st.rerun()
            
        except Exception as e:
            st.error(f"Error al procesar con Gemini. Si dice 503, tocá procesar de nuevo. Detalle: {e}")

monto_total_gastos = float(df_mostrar["monto"].sum()) if not df_mostrar.empty else 0.0
saldo_restante = float(ingreso_mensual) - monto_total_gastos

st.markdown("---")
if not df.empty:
    st.subheader(f"💵 Balance: {mes_seleccionado}")
else:
    st.subheader("💵 Balance Actual")

# Implementación de las tarjetas UI
with st.container(border=True):
    col_met1, col_met2, col_met3 = st.columns(3)
    col_met1.metric(label="Ingreso Mensual", value=f"${ingreso_mensual:,.2f}")
    col_met2.metric(label="Total Gastado", value=f"${monto_total_gastos:,.2f}")
    
    color_saldo = "normal" if saldo_restante >= 0 else "inverse"
    col_met3.metric(
        label="Saldo Disponible", value=f"${saldo_restante:,.2f}", 
        delta=f"${saldo_restante:,.2f}", delta_color=color_saldo
    )

if not df_mostrar.empty:
    st.markdown("---")
    col1, col2 = st.columns([1, 1])

    with col1:
        with st.container(border=True):
            st.subheader("📊 Distribución")
            df_agrupado = df_mostrar.groupby("categoria", as_index=False)["monto"].sum()
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
        with st.container(border=True):
            st.subheader("📋 Detalle de Gastos")
            st.dataframe(
                df_mostrar[['fecha', 'item', 'monto', 'categoria']],
                column_config={
                    "fecha": "Fecha",
                    "item": "Concepto",
                    "monto": st.column_config.NumberColumn("Monto ($)", format="$%.2f"),
                    "categoria": "Categoría",
                },
                hide_index=True, 
                use_container_width=True,
            )
