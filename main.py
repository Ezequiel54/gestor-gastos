from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlalchemy
import re
import pandas as pd
from datetime import datetime, timedelta

app = FastAPI(title="Finanzas KOVA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URL = "postgresql://postgres:TU_CONTRASENA_REAL@db.jnwhwgzlbbzofizmwsyf.supabase.co:5432/postgres"
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

engine = sqlalchemy.create_engine(DB_URL)

def init_db():
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS public.gastos (
                id SERIAL PRIMARY KEY,
                item TEXT,
                monto REAL,
                categoria TEXT,
                fecha TEXT DEFAULT '',
                descripcion TEXT DEFAULT '',
                innecesario INTEGER DEFAULT 0
            )
        '''))
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS public.presupuestos_mensuales (
                mes_anio TEXT PRIMARY KEY,
                ingreso REAL DEFAULT 0.0,
                ahorro REAL DEFAULT 0.0
            )
        '''))
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS public.diccionario_categorias (
                id SERIAL PRIMARY KEY,
                categoria TEXT,
                palabra TEXT
            )
        '''))
        conn.commit()
        
        res = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM public.diccionario_categorias")).fetchone()
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
                        "INSERT INTO public.diccionario_categorias (categoria, palabra) VALUES (:cat, :pal)"
                    ), {"cat": cat, "pal": palabra})
            conn.commit()

init_db()

class GastosInput(BaseModel):
    texto: str

def cargar_diccionario_db():
    try:
        df_dic = pd.read_sql("SELECT categoria, palabra FROM public.diccionario_categorias", con=engine)
        diccionario = {}
        for _, row in df_dic.iterrows():
            cat = row['categoria']
            if cat not in diccionario:
                diccionario[cat] = []
            diccionario[cat].append(row['palabra'])
        return diccionario
    except Exception:
        return {
            "Alimentos": ["super", "supermercado", "comida", "chori"],
            "Transporte": ["uber", "sube", "taxi", "bondi"]
        }

@app.post("/api/procesar-gastos")
def procesar_gastos(data: GastosInput):
    try:
        categorias_dinamicas = cargar_diccionario_db()
        gastos_procesados = []
        lineas = data.texto.split('\n')
        
        for linea in lineas:
            if not linea.strip(): continue
                
            es_innecesario = 1 if re.search(r'innecesari[oa]s?', linea, re.IGNORECASE) else 0
            linea_limpia = re.sub(r'innecesari[oa]s?', '', linea, flags=re.IGNORECASE).replace('  ', ' ').strip()
            
            partes = linea_limpia.split('-', 1)
            texto_principal = partes[0].strip()
            descripcion = partes[1].strip().capitalize() if len(partes) > 1 else ""
            
            texto_min = texto_principal.lower()
            numeros = re.findall(r'\d+', texto_min.replace('.', ''))
            if not numeros: continue
                
            monto = float(numeros[0])
            item = re.sub(r'[\d\.]+', '', texto_principal).strip().capitalize()
            if not item: item = "Gasto general"

            categoria_asignada = "Otros"
            for cat, palabras in categorias_dinamicas.items():
                if any(palabra in texto_min for palabra in palabras):
                    categoria_asignada = cat
                    break
            
            gastos_procesados.append({
                "item": item, "monto": monto, "categoria": categoria_asignada, 
                "descripcion": descripcion, "innecesario": es_innecesario
            })
        
        if not gastos_procesados:
            raise HTTPException(status_code=400, detail="No se detectaron gastos válidos.")
        
        fecha_actual = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y")
        with engine.connect() as conn:
            for g in gastos_procesados:
                conn.execute(sqlalchemy.text("""
                    INSERT INTO public.gastos (item, monto, categoria, fecha, descripcion, innecesario) 
                    VALUES (:item, :monto, :categoria, :fecha, :descripcion, :innecesario)
                """), {
                    "item": g['item'], "monto": g['monto'], "categoria": g['categoria'], 
                    "fecha": fecha_actual, "descripcion": g['descripcion'], "innecesario": g['innecesario']
                })
            conn.commit()

        return {"status": "success", "procesados": len(gastos_procesados)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
