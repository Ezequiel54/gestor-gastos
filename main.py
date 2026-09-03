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

DB_URL = "postgresql://postgres.jnwhwgzlbbzofizmwsyf:Sanson0007.@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
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

init_db()

class GastosInput(BaseModel):
    texto: str

class PresupuestoInput(BaseModel):
    mes_anio: str
    ingreso: float
    ahorro: float

@app.post("/api/procesar-gastos")
def procesar_gastos(data: GastosInput):
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

        gastos_procesados.append({
            "item": item, "monto": monto, "categoria": "Otros", 
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

@app.get("/api/balance")
def obtener_balance():
    with engine.connect() as conn:
        res = conn.execute(sqlalchemy.text("SELECT sum(monto) FROM public.gastos")).fetchone()
        total_gastado = float(res[0]) if res[0] else 0.0
    return {"total_gastado": total_gastado}

@app.get("/api/presupuesto/{mes_anio}")
def obtener_presupuesto(mes_anio: str):
    with engine.connect() as conn:
        res = conn.execute(sqlalchemy.text(
            "SELECT ingreso, ahorro FROM public.presupuestos_mensuales WHERE mes_anio = :ma"
        ), {"ma": mes_anio}).fetchone()
        if res:
            return {"ingreso": float(res[0]), "ahorro": float(res[1])}
    return {"ingreso": 0.0, "ahorro": 0.0}

@app.post("/api/presupuesto")
def guardar_presupuesto(data: PresupuestoInput):
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text('''
            INSERT INTO public.presupuestos_mensuales (mes_anio, ingreso, ahorro)
            VALUES (:ma, :ing, :aho)
            ON CONFLICT (mes_anio) 
            DO UPDATE SET ingreso = EXCLUDED.ingreso, ahorro = EXCLUDED.ahorro
        '''), {"ma": data.mes_anio, "ing": data.ingreso, "aho": data.ahorro})
        conn.commit()
    return {"status": "success"}
