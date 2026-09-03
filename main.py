from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlalchemy
import re
import io
import pandas as pd
from datetime import datetime, timedelta
from fastapi.responses import StreamingResponse

app = FastAPI(title="Finanzas KOVA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URL = "postgresql://postgres:TU_CONTRASENA_REAL@db.jnwhwgzlbbzofizmwsyf.supabase.co:5432/postgres"
engine = sqlalchemy.create_engine(DB_URL)

NOMBRES_MESES = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
                 7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

def init_db():
    with engine.connect() as conn:
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
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS presupuestos_mensuales (
                mes_anio TEXT PRIMARY KEY,
                ingreso REAL DEFAULT 0.0,
                ahorro REAL DEFAULT 0.0
            )
        '''))
        conn.execute(sqlalchemy.text('''
            CREATE TABLE IF NOT EXISTS diccionario_categorias (
                id SERIAL PRIMARY KEY,
                categoria TEXT,
                palabra TEXT
            )
        '''))
        conn.commit()
        
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

class GastosInput(BaseModel):
    texto: str

class PresupuestoInput(BaseModel):
    mes_anio: str
    ingreso: float
    ahorro: float

def cargar_diccionario_db():
    df_dic = pd.read_sql("SELECT categoria, palabra FROM diccionario_categorias", con=engine)
    diccionario = {}
    for _, row in df_dic.iterrows():
        cat = row['categoria']
        if cat not in diccionario:
            diccionario[cat] = []
        diccionario[cat].append(row['palabra'])
    return diccionario

@app.get("/api/gastos")
def obtener_gastos():
    df = pd.read_sql("SELECT id, fecha, item, descripcion, monto, categoria, innecesario FROM gastos", con=engine)
    return df.to_dict(orient="records")

@app.post("/api/procesar-gastos")
def procesar_gastos(data: GastosInput):
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
                INSERT INTO gastos (item, monto, categoria, fecha, descripcion, innecesario) 
                VALUES (:item, :monto, :categoria, :fecha, :descripcion, :innecesario)
            """), {
                "item": g['item'], "monto": g['monto'], "categoria": g['categoria'], 
                "fecha": fecha_actual, "descripcion": g['descripcion'], "innecesario": g['innecesario']
            })
        conn.commit()

    return {"status": "success", "procesados": len(gastos_procesados)}

@app.delete("/api/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int):
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM gastos WHERE id = :id"), {"id": gasto_id})
        conn.commit()
    return {"status": "success"}

@app.get("/api/presupuesto/{mes_anio}")
def obtener_presupuesto(mes_anio: str):
    with engine.connect() as conn:
        res = conn.execute(sqlalchemy.text(
            "SELECT ingreso, ahorro FROM presupuestos_mensuales WHERE mes_anio = :ma"
        ), {"ma": mes_anio}).fetchone()
        if res:
            return {"ingreso": float(res[0]), "ahorro": float(res[1])}
    return {"ingreso": 0.0, "ahorro": 0.0}

@app.post("/api/presupuesto")
def guardar_presupuesto(data: PresupuestoInput):
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text('''
            INSERT INTO presupuestos_mensuales (mes_anio, ingreso, ahorro)
            VALUES (:ma, :ing, :aho)
            ON CONFLICT (mes_anio) 
            DO UPDATE SET ingreso = EXCLUDED.ingreso, ahorro = EXCLUDED.ahorro
        '''), {"ma": data.mes_anio, "ing": data.ingreso, "aho": data.ahorro})
        conn.commit()
    return {"status": "success"}
