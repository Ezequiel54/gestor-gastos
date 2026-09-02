import pandas as pd
import plotly.express as px
import streamlit as st
import sqlalchemy
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

# --- CONEXIÓN A SUPABASE (PostgreSQL) ---
@st.cache_resource
def get_engine():
    db_url = st.secrets["SUPABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return sqlalchemy.create_engine(db_url)

engine = get_engine()

# Nombres de meses en español para todo el sistema
NOMBRES_MESES = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
                 7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

def init_db():
    with engine.connect() as conn:
        # Tabla de gastos
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY,
                item TEXT,
                monto REAL,
                categoria TEXT,
                fecha TEXT DEFAULT '',
                descripcion TEXT DEFAULT '',
                innecesario INTEGER DEFAULT 0
            )
        '''))
        # Nueva Tabla: Presupuestos Históricos (por mes)
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS presupuestos_mensuales (
                mes_anio TEXT PRIMARY KEY,
                ingreso REAL DEFAULT 0.0,
                ahorro REAL DEFAULT 0.0
            )
        '''))
        # Nueva Tabla: Diccionario de Categorías
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS diccionario_categorias (
                id SERIAL PRIMARY KEY,
                categoria TEXT,
                palabra TEXT
            )
        '''))
        conn.commit()
        
        # Insertar diccionario por defecto si está vacío
        res = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM diccionario_categorias")).fetchone()
        if res[0] == 0:
            categorias_default = {
                "Alimentos": ["super", "supermercado", "comida", "chino", "coto", "carrefour", "dia", "verduleria", "carniceria", "kiosco", "panaderia", "almuerzo", "chori"],
                "Transporte": ["uber", "sube", "taxi", "bondi", "colectivo", "tren", "nafta", "peaje", "viaje"],
                "Salidas/Ocio": ["boliche", "cine", "bar", "cerveza", "cena", "salida", "joda", "entrada", "recital", "juego", "steam", "partido"],
                "Servicios": ["luz", "gas", "agua", "internet", "telefono", "celular", "edenor", "edesur", "aysa", "netflix", "spotify", "hosting"],
                "Educación": ["facultad", "fadu", "uba", "apuntes", "materiales", "cuota", "maqueta"],
                "Impuestos": ["afip", "monotributo", "impuesto", "abl"]
            }
            for cat, palabras in categorias_default.items():
                for palabra in palabras:
                    conn.execute(sqlalchemy.text(
                        "INSERT INTO diccionario_categorias (categoria, palabra) VALUES (:cat, :pal)"
                    ), {"cat": cat, "pal": palabra})
            conn.commit()

init_db()

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_presupuesto(mes_anio):
    with engine.connect() as conn:
        res = conn.execute(sqlalchemy.text(
            "SELECT ingreso, ahorro FROM presupuestos_mensuales WHERE mes_anio = :ma"
        ), {"ma": mes_anio}).fetchone()
        if res:
            return float(res[0]), float(res[1])
    return 0.0, 0.0

def guardar_presupuesto(mes_anio, ingreso, ahorro):
    with engine.connect() as conn:
        # Intenta insertar o actualizar (Upsert)
        conn.execute(sqlalchemy.text('''
            INSERT INTO presupuestos_mensuales (mes_anio, ingreso, ahorro)
            VALUES (:ma, :ing, :aho)
            ON CONFLICT (mes_anio) 
            DO UPDATE SET ingreso = EXCLUDED.ingreso, ahorro = EXCLUDED.ahorro
        '''), {"ma": mes_anio, "ing": ingreso, "aho": ahorro})
        conn.commit()

def cargar_gastos():
    return pd.read_sql("SELECT id, fecha, item, descripcion, monto, categoria, innecesario FROM gastos", con=engine)

def guardar_gastos(gastos_lista):
    fecha_actual = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y")
    with engine.connect() as conn:
        for g in gastos_lista:
            conn.execute(sqlalchemy.text("""
                INSERT INTO gastos (item, monto, categoria, fecha, descripcion, innecesario) 
                VALUES (:item, :monto, :categoria, :fecha, :descripcion, :innecesario)
            """), {
                "item": g['item'], "monto": g['monto'], "categoria": g['categoria'], 
                "fecha": fecha_actual, "descripcion": g['descripcion'], "innecesario": g['innecesario']
            })
        conn.commit()

def eliminar_gasto(id_gasto):
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM gastos WHERE id = :id"), {"id": id_gasto})
        conn.commit()

def limpiar_bd():
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM gastos"))
        conn.commit()

def cargar_diccionario():
    df_dic = pd.read_sql("SELECT categoria, palabra FROM diccionario_categorias", con=engine)
    diccionario = {}
    for _, row in df_dic.iterrows():
        cat = row['categoria']
        if cat not in diccionario:
            diccionario[cat] = []
        diccionario[cat].append(row['palabra'])
    return diccionario

def agregar_palabra_diccionario(categoria, palabra):
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(
            "INSERT INTO diccionario_categorias (categoria, palabra) VALUES (:cat, :pal)"
        ), {"cat": categoria, "pal": palabra.lower().strip()})
        conn.commit()

# --- PROCESAMIENTO INTELIGENTE CON DICCIONARIO DINÁMICO ---
def procesar_texto_local(texto_multilinea, categorias_dinamicas):
    gastos_procesados = []
    lineas = texto_multilinea.split('\n')
    
    for linea in lineas:
        if not linea.strip():
            continue
            
        es_innecesario = 1 if re.search(r'innecesari[oa]s?', linea, re.IGNORECASE) else 0
        linea_limpia = re.sub(r'innecesari[oa]s?', '', linea, flags=re.IGNORECASE).replace('  ', ' ').strip()
            
        partes = linea_limpia.split('-', 1)
        texto_principal = partes[0].strip()
        descripcion = partes[1].strip().capitalize() if len(partes) > 1 else ""
        
        texto_min = texto_principal.lower()
        numeros = re.findall(r'\d+', texto_min.replace('.', ''))
        if not numeros:
            continue
            
        monto = float(numeros[0])
        item = re.sub(r'[\d\.]+', '', texto_principal).strip().capitalize()
        if not item:
            item = "Gasto general"
        
        categoria_asignada = "Otros"
        for cat, palabras in categorias_dinamicas.items():
            if any(palabra in texto_min for palabra in palabras):
                categoria_asignada = cat
                break
                
        gastos_procesados.append({
            "item": item, "monto": monto, "categoria": categoria_asignada,
            "descripcion": descripcion, "innecesario": es_innecesario
        })
    return gastos_procesados

# --- LÓGICA DE FECHAS Y DATOS ---
fecha_hoy = datetime.utcnow() - timedelta(hours=3)
mes_actual_str = f"{NOMBRES_MESES[fecha_hoy.month]} {fecha_hoy.year}"

df = cargar_gastos()

if not df.empty:
    df['fecha_dt'] = pd.to_datetime(df['fecha'], format='%d/%m/%Y', errors='coerce')
    df['fecha_dt'] = df['fecha_dt'].fillna(fecha_hoy)
    df['Mes_Anio'] = df['fecha_dt'].dt.month.map(NOMBRES_MESES) + " " + df['fecha_dt'].dt.year.astype(str)
    df = df.sort_values(by='fecha_dt', ascending=False)
    meses_disponibles = df['Mes_Anio'].unique().tolist()
    if mes_actual_str not in meses_disponibles:
        meses_disponibles.insert(0, mes_actual_str)
else:
    meses_disponibles = [mes_actual_str]
    df['Mes_Anio'] = pd.Series(dtype='str')

# --- INTERFAZ PRINCIPAL ---
st.title("💰 Gestor de Gastos Diarios")

# --- SIDEBAR: HISTORIAL Y EXCEL MAESTRO ---
st.sidebar.header("Tus Finanzas")

mes_seleccionado = st.sidebar.selectbox("📅 Seleccionar Mes:", meses_disponibles)

# Cargar presupuesto específico de este mes
ingreso_guardado, ahorro_guardado = cargar_presupuesto(mes_seleccionado)

ingreso_mensual = st.sidebar.number_input(
    f"Ingreso de {mes_seleccionado} ($)", min_value=0.0, 
    value=float(ingreso_guardado), step=10000.0, format="%f"
)
ahorro_mensual = st.sidebar.number_input(
    f"Ahorro de {mes_seleccionado} ($)", min_value=0.0, 
    value=float(ahorro_guardado), step=5000.0, format="%f"
)

if ingreso_mensual != ingreso_guardado or ahorro_mensual != ahorro_guardado:
    guardar_presupuesto(mes_seleccionado, ingreso_mensual, ahorro_mensual)

st.sidebar.markdown("---")

# Excel Maestro (Un archivo, múltiples hojas por mes)
if not df.empty:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for mes_hoja in df['Mes_Anio'].unique():
            df_hoja = df[df['Mes_Anio'] == mes_hoja].copy()
            df_hoja['Innecesario'] = df_hoja['innecesario'].apply(lambda x: "Sí" if x == 1 else "No")
            # Nombre de hoja no puede superar 31 caracteres en Excel
            nombre_limpio = str(mes_hoja)[:31]
            df_hoja[['fecha', 'item', 'descripcion', 'categoria', 'monto', 'Innecesario']].to_excel(writer, index=False, sheet_name=nombre_limpio)
            
    st.sidebar.download_button(
        label="📥 Descargar Excel Maestro",
        data=buffer.getvalue(),
        file_name=f"Mis_Finanzas_Master.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Descarga todos tus meses organizados en pestañas dentro de un solo archivo Excel."
    )

st.sidebar.markdown("---")
if st.sidebar.button("🚨 Limpiar toda la base de datos"):
    limpiar_bd()
    st.rerun()

# --- ÁREA PRINCIPAL: CARGA Y HERRAMIENTAS ---
df_mostrar = df[df['Mes_Anio'] == mes_seleccionado] if not df.empty else df.copy()

gastos_texto = st.text_area(
    "Escribí tus gastos (un renglón por gasto):",
    placeholder="Ej:\n5000 chori en Lanús - innecesario\n15000 materiales fadu - cartones para la maqueta",
    height=120,
)

if st.button("Procesar Gastos", type="primary"):
    if not gastos_texto.strip():
        st.warning("Escribí al menos un gasto para analizar.")
    else:
        categorias_db = cargar_diccionario()
        nuevos_gastos = procesar_texto_local(gastos_texto, categorias_db)
        if len(nuevos_gastos) > 0:
            guardar_gastos(nuevos_gastos)
            st.success(f"¡{len(nuevos_gastos)} gasto(s) guardado(s) en {mes_actual_str}!")
            st.rerun()
        else:
            st.error("No se detectó ningún monto numérico válido en el texto.")

# --- HERRAMIENTAS AVANZADAS (EXPANDERS) ---
col_tool1, col_tool2 = st.columns(2)
with col_tool1:
    with st.expander("⚙️ Enseñar nueva palabra a una categoría"):
        cat_elegida = st.selectbox("Categoría:", ["Alimentos", "Transporte", "Salidas/Ocio", "Servicios", "Educación", "Impuestos", "Otros"])
        nueva_palabra = st.text_input("Nueva palabra clave (ej: mcdonalds):")
        if st.button("Agregar palabra al sistema"):
            if nueva_palabra:
                agregar_palabra_diccionario(cat_elegida, nueva_palabra)
                st.success(f"Palabra '{nueva_palabra}' asignada a {cat_elegida}.")
            else:
                st.warning("Escribí una palabra válida.")

with col_tool2:
    with st.expander("🗑️ Borrar un gasto mal cargado"):
        if not df_mostrar.empty:
            id_a_borrar = st.selectbox("Seleccioná el gasto a eliminar:", df_mostrar['id'].tolist(), 
                                     format_func=lambda x: f"ID {x} - {df_mostrar[df_mostrar['id']==x]['item'].values[0]} (${df_mostrar[df_mostrar['id']==x]['monto'].values[0]:,.0f})")
            if st.button("Eliminar permanentemente"):
                eliminar_gasto(id_a_borrar)
                st.success("Gasto eliminado.")
                st.rerun()
        else:
            st.info("No hay gastos en este mes para borrar.")

# --- CÁLCULOS DEL MES SELECCIONADO ---
monto_total_gastos = float(df_mostrar["monto"].sum()) if not df_mostrar.empty else 0.0
presupuesto_gastos = float(ingreso_mensual) - float(ahorro_mensual)
saldo_restante_raw = presupuesto_gastos - monto_total_gastos

if saldo_restante_raw < 0:
    saldo_restante = 0.0
    exceso_ahorros = abs(saldo_restante_raw)
else:
    saldo_restante = saldo_restante_raw
    exceso_ahorros = 0.0

st.markdown("---")
st.subheader(f"💵 Balance: {mes_seleccionado}")

if not df_mostrar.empty:
    if exceso_ahorros > 0:
        st.error(f"⚠️ **¡Alerta de Ahorros!** Te pasaste por **${exceso_ahorros:,.2f}** de tu presupuesto disponible y tuviste que consumir parte del dinero que ibas a ahorrar.")
    
    df_innecesarios = df_mostrar[df_mostrar['innecesario'] == 1]
    total_innecesario = float(df_innecesarios['monto'].sum()) if not df_innecesarios.empty else 0.0
    if total_innecesario > 0:
        st.warning(f"🚨 **Atención:** Este mes llevás tirados **${total_innecesario:,.2f}** en gastos innecesarios.")

with st.container(border=True):
    col_met1, col_met2, col_met3, col_met4 = st.columns(4)
    col_met1.metric(label="Ingreso", value=f"${ingreso_mensual:,.2f}")
    col_met2.metric(label="Ahorro Destinado", value=f"${ahorro_mensual:,.2f}")
    col_met3.metric(label="Total Gastado", value=f"${monto_total_gastos:,.2f}")
    col_met4.metric(label="Saldo Real Disponible", value=f"${saldo_restante:,.2f}")

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
            df_mostrar['Alerta'] = df_mostrar['innecesario'].apply(lambda x: "⚠️ Sí" if x == 1 else "")
            
            # Formateo visual limpio sin el ID en la tabla principal
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
