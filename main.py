from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlalchemy
import re
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
engine = sqlalchemy.create_engine(DB_URL)

# --- CREAR TABLAS SI NO EXISTEN ---
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
        conn.commit()

init_db()

class GastosInput(BaseModel):
    texto: str

@app.post("/api/procesar-gastos")
def procesar_gastos(data: GastosInput):
    texto_multilinea = data.texto
    gastos_procesados = []
    lineas = texto_multilinea.split('\n')
    
    categorias = {
        "Alimentos": ["super", "supermercado", "comida", "chino", "coto", "carrefour", "dia", "verduleria", "carniceria", "kiosco", "panaderia", "almuerzo", "chori"],
        "Transporte": ["uber", "sube", "taxi", "bondi", "colectivo", "tren", "nafta", "peaje", "viaje"],
        "Salidas/Ocio": ["boliche", "cine", "bar", "cerveza", "cena", "salida", "joda", "entrada", "recital", "juego", "steam", "partido"],
        "Servicios": ["luz", "gas", "agua", "internet", "telefono", "celular", "edenor", "edesur", "aysa", "netflix", "spotify", "hosting"],
        "Educación": ["facultad", "fadu", "uba", "apuntes", "materiales", "cuota", "maqueta"],
        "Impuestos": ["afip", "monotributo", "impuesto", "abl"]
    }
    
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
        for cat, palabras in categorias.items():
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

@app.get("/api/balance")
def obtener_balance():
    with engine.connect() as conn:
        res = conn.execute(sqlalchemy.text("SELECT sum(monto) FROM gastos")).fetchone()
        total_gastado = float(res[0]) if res[0] else 0.0
    return {"total_gastado": total_gastado}
