import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
import re
import io
from datetime import datetime, timedelta

st.set_page_config(page_title="Finanzas KOVA", page_icon="💰", layout="wide")

# --- CSS: ESTILO UI/UX ---
st.markdown("""
    <style>
        div[data-testid="stVerticalBlock"] > div[style*="border"] {
            border-radius: 16px !important;
            border: 1px solid #E5E7EB !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
            padding: 16px;
            background-color: #FFFFFF;
        }
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
    
    # --- TABLA DE GASTOS ---
    c.execute('''CREATE TABLE IF NOT EXISTS gastos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, monto REAL, categoria TEXT)''')
    
    c.execute("PRAGMA table_info(gastos)")
    columnas_gastos = [columna[1] for columna in c.fetchall()]
    if 'fecha' not in columnas_gastos:
        c.execute("ALTER TABLE gastos ADD COLUMN fecha TEXT DEFAULT ''")
    if 'descripcion' not in columnas_gastos:
        c.execute("ALTER TABLE gastos ADD COLUMN descripcion TEXT DEFAULT ''")
    # Nueva columna para gastos innecesarios
    if 'innecesario' not in columnas_gastos:
        c.execute("ALTER TABLE gastos ADD COLUMN innecesario INTEGER DEFAULT 0")
        
    # --- TABLA DE CONFIGURACIÓN (Ingreso y Ahorro) ---
    c.execute('''CREATE TABLE IF NOT EXISTS configuracion
                 (id INTEGER PRIMARY KEY, ingreso_mensual REAL)''')
                 
    c.execute("PRAGMA table_info(configuracion)")
    columnas_conf = [columna[1] for columna in c.fetchall()]
    if 'ahorro_mensual' not in columnas_conf:
        c.execute("ALTER TABLE configuracion ADD COLUMN ahorro_mensual REAL DEFAULT 0.0")
    
    c.execute("SELECT COUNT(*) FROM configuracion")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO configuracion (id, ingreso_mensual, ahorro_mensual) VALUES (1, 0.0, 0.0)")
        
    conn.commit()
    conn.close()

def cargar_configuracion():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("SELECT ingreso_mensual, ahorro_mensual FROM configuracion WHERE id=1")
    resultado = c.fetchone()
    conn.close()
    if resultado:
        return resultado[0] if resultado[0] else 0.0, resultado[1] if resultado[1] else 0.0
    return 0.0, 0.0

def guardar_configuracion(ingreso, ahorro):
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("UPDATE configuracion SET ingreso_mensual = ?, ahorro_mensual = ? WHERE id=1", (ingreso, ahorro))
    conn.commit()
    conn.close()

def cargar_gastos():
    conn = sqlite3.connect('mis_gastos.db')
    df = pd.read_sql_query("SELECT fecha, item, descripcion, monto, categoria, innecesario FROM gastos", conn)
    conn.close()
    return df

def guardar_gastos(gastos_lista):
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    fecha_actual = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y")
    
    for g in gastos_lista:
        c.execute("INSERT INTO gastos (item, monto, categoria, fecha, descripcion, innecesario) VALUES (?, ?, ?, ?, ?, ?)", 
                  (g['item'], g['monto'], g['categoria'], fecha_actual, g['descripcion'], g['innecesario']))
    conn.commit()
    conn.close()

def limpiar_bd():
    conn = sqlite3.connect('mis_gastos.db')
    c = conn.cursor()
    c.execute("DELETE FROM gastos")
    conn.commit()
    conn.close()

init_db()

# --- PROCESAMIENTO MÚLTIPLE CON ETIQUETA "INNECESARIO" ---
def procesar_texto_local(texto_multilinea):
    gastos_procesados = []
    lineas = texto_multilinea.split('\n')
    
    for linea in lineas:
        if not linea.strip():
            continue
            
        # Detecta si se escribió la palabra clave (ignora mayúsculas/minúsculas)
        es_innecesario = 1 if re.search(r'innecesari[oa]s?', linea, re.IGNORECASE) else 0
        
        # Limpia la palabra del texto original para que no ensucie la tabla
        linea_limpia = re.sub(r'innecesari[oa]s?', '', linea, flags=re.IGNORECASE).replace('  ', ' ').strip()
            
        partes = linea_limpia.split('-', 1)
        texto_principal = partes[0].strip()
        descripcion = partes[1].strip().capitalize() if len(partes) > 1 else ""
        
        texto_min = texto_principal.lower()
        texto_sin_puntos = texto_min.replace('.', '')
        numeros = re.findall(r'\d+', texto_sin_puntos)
        
        if not numeros:
            continue
            
        monto = float(numeros[0])
        item = re.sub(r'[\d\.]+', '', texto_principal).strip().capitalize()
        if not item:
            item = "Gasto general"
        
        categorias = {
            "Alimentos": ["super", "supermercado", "comida", "chino", "coto", "carrefour", "dia", "verduleria", "carniceria", "kiosco", "panaderia", "almuerzo", "chori"],
            "Transporte": ["uber", "sube", "taxi", "bondi", "colectivo", "tren", "nafta", "peaje", "viaje"],
            "Salidas/Ocio": ["boliche", "cine", "bar", "cerveza", "cena", "salida", "joda", "entrada", "recital", "juego", "steam", "partido"],
            "Servicios": ["luz", "gas", "agua", "internet", "telefono", "celular", "edenor", "edesur", "aysa", "netflix", "spotify"],
            "Educación": ["facultad", "fadu", "uba", "apuntes", "materiales", "cuota", "maqueta"],
            "Impuestos": ["afip", "monotributo", "impuesto", "abl"]
        }
        
        categoria_asignada = "Otros"
        for cat, palabras in categorias.items():
            if any(palabra in texto_min for palabra in palabras):
                categoria_asignada = cat
                break
                
        gastos_procesados.append({
            "item": item, 
            "monto": monto, 
            "categoria": categoria_asignada,
            "descripcion": descripcion,
            "innecesario": es_innecesario
        })
        
    return gastos_procesados

# --- INTERFAZ PRINCIPAL ---
st.title("💰 Gestor de Gastos Diarios")

st.sidebar.header("Tus Finanzas")

ingreso_guardado, ahorro_guardado = cargar_configuracion()

ingreso_mensual = st.sidebar.number_input(
    "Ingreso Mensual ($)", 
    min_value=0.0, 
    value=float(ingreso_guardado), 
    step=10000.0, 
    format="%f"
)

ahorro_mensual = st.sidebar.number_input(
    "Ahorro Destinado ($)", 
    min_value=0.0, 
    value=float(ahorro_guardado), 
    step=5000.0, 
    format="%f",
    help="Dinero que separás y no querés tener disponible para gastar."
)

if ingreso_mensual != ingreso_guardado or ahorro_mensual != ahorro_guardado:
    guardar_configuracion(ingreso_mensual, ahorro_mensual)

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
    
    # Adaptar la columna de innecesarios para el excel
    df_excel = df_mostrar.copy()
    df_excel['innecesario'] = df_excel['innecesario'].apply(lambda x: "Sí" if x == 1 else "No")
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_excel[['fecha', 'item', 'descripcion', 'categoria', 'monto', 'innecesario']].to_excel(writer, index=False, sheet_name='Gastos')
    
    st.sidebar.download_button(
        label="📥 Exportar mes a Excel",
        data=buffer.getvalue(),
        file_name=f"Gastos_{mes_seleccionado.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.sidebar.markdown("---")
if st.sidebar.button("Limpiar todos los gastos"):
    limpiar_bd()
    st.rerun()
    
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.autenticado = False
    st.rerun()

gastos_texto = st.text_area(
    "Escribí tus gastos (un renglón por gasto):",
    placeholder="Ej:\n5000 chori en Lanús - innecesario\n15000 materiales fadu - cartones",
    height=120,
)

if st.button("Procesar Gastos", type="primary"):
    if not gastos_texto.strip():
        st.warning("Escribí al menos un gasto para analizar.")
    else:
        nuevos_gastos = procesar_texto_local(gastos_texto)
        
        if len(nuevos_gastos) > 0:
            guardar_gastos(nuevos_gastos)
            st.success(f"¡{len(nuevos_gastos)} gasto(s) procesado(s) y guardado(s) al instante!")
            st.rerun()
        else:
            st.error("No se detectó ningún monto numérico válido en el texto.")

monto_total_gastos = float(df_mostrar["monto"].sum()) if not df_mostrar.empty else 0.0
saldo_restante = float(ingreso_mensual) - float(ahorro_mensual) - monto_total_gastos

st.markdown("---")
if not df.empty:
    st.subheader(f"💵 Balance: {mes_seleccionado}")
else:
    st.subheader("💵 Balance Actual")

# Alerta roja si hay gastos innecesarios
if not df_mostrar.empty:
    df_innecesarios = df_mostrar[df_mostrar['innecesario'] == 1]
    total_innecesario = float(df_innecesarios['monto'].sum()) if not df_innecesarios.empty else 0.0
    
    if total_innecesario > 0:
        st.error(f"🚨 Atención: Este mes llevás tirados **${total_innecesario:,.2f}** en gastos innecesarios.")

with st.container(border=True):
    col_met1, col_met2, col_met3, col_met4 = st.columns(4)
    col_met1.metric(label="Ingreso", value=f"${ingreso_mensual:,.2f}")
    col_met2.metric(label="Ahorro Destinado", value=f"${ahorro_mensual:,.2f}")
    col_met3.metric(label="Total Gastado", value=f"${monto_total_gastos:,.2f}")
    
    color_saldo = "normal" if saldo_restante >= 0 else "inverse"
    col_met4.metric(
        label="Saldo Real Disponible", value=f"${saldo_restante:,.2f}", 
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
            # Cambiamos visualmente el 1 y 0 por algo más amigable para leer en la tabla
            df_mostrar['Alerta'] = df_mostrar['innecesario'].apply(lambda x: "⚠️ Sí" if x == 1 else "")
            
            st.dataframe(
                df_mostrar[['fecha', 'item', 'descripcion', 'monto', 'categoria', 'Alerta']],
                column_config={
                    "fecha": "Fecha",
                    "item": "Concepto",
                    "descripcion": "Descripción",
                    "monto": st.column_config.NumberColumn("Monto ($)", format="$%.2f"),
                    "categoria": "Categoría",
                    "Alerta": "Innecesario"
                },
                hide_index=True, 
                use_container_width=True,
            )
