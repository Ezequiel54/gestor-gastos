import pandas as pd
import plotly.express as px
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel


# 1. Definición del esquema estructurado para Gemini
class Gasto(BaseModel):
    item: str
    monto: float
    categoria: str


class ListaGastos(BaseModel):
    gastos: list[Gasto]


# 2. Configuración de la página
st.set_page_config(
    page_title="Gestor de Gastos IA", page_icon="💰", layout="wide"
)

st.title("💰 Gestor de Gastos Diarios con Gemini")
st.write(
    "Ingresá tus gastos en texto libre y la IA los clasificará automáticamente."
)

# 3. Sidebar para Configuración e Ingresos
st.sidebar.header("Configuración")
api_key = st.sidebar.text_input("Gemini API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.subheader("Tus Finanzas")
ingreso_mensual = st.sidebar.number_input(
    "Ingreso Mensual ($)", 
    min_value=0.0, 
    value=0.0, 
    step=10000.0,
    format="%f"
)

if "tabla_gastos" not in st.session_state:
    st.session_state.tabla_gastos = pd.DataFrame(
        columns=["item", "monto", "categoria"]
    )

if st.sidebar.button("Limpiar todos los gastos"):
    st.session_state.tabla_gastos = pd.DataFrame(
        columns=["item", "monto", "categoria"]
    )
    st.rerun()

# 4. Formulario de ingreso de texto
gastos_texto = st.text_area(
    "Escribí tus gastos del día:",
    placeholder="Ej: Cobré y gasté $15.000 en el súper, $3.200 en la SUBE y $8.500 comiendo una pizza.",
    height=100,
)

if st.button("Procesar Gastos", type="primary"):
    if not api_key:
        st.error("Por favor ingresá tu Gemini API Key en el menú lateral.")
    elif not gastos_texto.strip():
        st.warning("Escribí al menos un gasto para analizar.")
    else:
        try:
            client = genai.Client(api_key=api_key)

            prompt = f"""
            Analiza el siguiente texto e identifica todos los gastos realizados.
            Extrae el nombre del ítem/concepto, el monto numérico en formato flotante, 
            y clasifícalo en una categoría lógica (ej: Alimentos, Transporte, Salidas/Ocio, Servicios, Salud, Impuestos, Otros).

            Texto a analizar:
            "{gastos_texto}"
            """

            response = client.models.generate_content(
               model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ListaGastos,
                    temperature=0.1,
                ),
            )

            # Corrección para Pylance: asegurar que el texto sea un string
            texto_respuesta = str(response.text) if response.text else "{}"
            datos_gemini = ListaGastos.model_validate_json(texto_respuesta)
            
            nuevos_gastos = [gasto.model_dump() for gasto in datos_gemini.gastos]
            df_nuevos = pd.DataFrame(nuevos_gastos)

            st.session_state.tabla_gastos = pd.concat(
                [st.session_state.tabla_gastos, df_nuevos], ignore_index=True
            )
            st.success("¡Gastos procesados e incorporados con éxito!")

        except Exception as e:
            st.error(f"Error al procesar con Gemini: {e}")

# 5. Visualización de Balances y Resultados
df = st.session_state.tabla_gastos
monto_total_gastos = float(df["monto"].sum()) if not df.empty else 0.0
saldo_restante = float(ingreso_mensual) - monto_total_gastos

st.markdown("---")
st.subheader("💵 Balance Actual")

col_met1, col_met2, col_met3 = st.columns(3)
col_met1.metric(label="Ingreso Mensual", value=f"${ingreso_mensual:,.2f}")
col_met2.metric(label="Total Gastado", value=f"${monto_total_gastos:,.2f}")

color_saldo = "normal" if saldo_restante >= 0 else "inverse"
col_met3.metric(
    label="Saldo Disponible", 
    value=f"${saldo_restante:,.2f}", 
    delta=f"${saldo_restante:,.2f}", 
    delta_color=color_saldo
)

st.markdown("---")

if not df.empty:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📊 Distribución por Categoría")
        # Corrección para Pylance: usar lista en el parámetro 'by'
        df_agrupado = df.groupby("categoria", as_index=False)["monto"].sum()
        df_agrupado = df_agrupado.sort_values(by=["monto"], ascending=False)

        fig = px.pie(
            df_agrupado,
            values="monto",
            names="categoria",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent+label",
            hovertemplate="%{label}: $%{value:,.2f}<br>%{percent}",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📋 Detalle de Gastos")
        st.dataframe(
            df,
            column_config={
                "item": "Concepto",
                "monto": st.column_config.NumberColumn(
                    "Monto ($)", format="$%.2f"
                ),
                "categoria": "Categoría",
            },
            hide_index=True,
            use_container_width=True,
        )